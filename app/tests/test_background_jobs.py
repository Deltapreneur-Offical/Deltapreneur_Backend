from unittest.mock import AsyncMock

from sqlalchemy import text

from app import background_jobs


def test_start_background_jobs_starts_the_timer_and_schedules_the_loop(monkeypatch) -> None:
    started = []
    scheduled = object()
    captured = {}

    monkeypatch.setattr(
        background_jobs.auction_timer_service,
        "start",
        lambda: started.append(True),
    )

    def fake_create_task(coro):
        captured["coro"] = coro
        return scheduled

    monkeypatch.setattr(background_jobs.asyncio, "create_task", fake_create_task)

    task = background_jobs.start_background_jobs()

    assert started == [True]
    assert task is scheduled
    assert captured["coro"].cr_code.co_name == "background_scheduler"
    captured["coro"].close()


async def test_stop_background_jobs_shuts_down_the_timer(monkeypatch) -> None:
    shutdown = AsyncMock()
    monkeypatch.setattr(background_jobs.auction_timer_service, "shutdown", shutdown)

    await background_jobs.stop_background_jobs()

    shutdown.assert_awaited_once()


class _FakeResult:
    def __init__(self, value=True):
        self._value = value

    def scalar(self):
        return self._value


class _FakeSession:
    def __init__(self, name: str, acquire_ok: bool = True):
        self.name = name
        self.acquire_ok = acquire_ok
        self.statements: list[str] = []
        self.closed = False

    async def execute(self, stmt, params=None):
        self.statements.append(str(stmt))
        sql = str(stmt).lower()
        if "pg_try_advisory_lock" in sql:
            return _FakeResult(self.acquire_ok)
        return _FakeResult(True)

    async def close(self):
        self.closed = True

    async def rollback(self):
        return None


class _SessionCM:
    def __init__(self, session: _FakeSession):
        self.session = session

    async def __aenter__(self):
        return self.session

    async def __aexit__(self, exc_type, exc, tb):
        await self.session.close()
        return False


def _install_session_factory(monkeypatch, sessions: list[_FakeSession]):
    remaining = list(sessions)

    def factory():
        return _SessionCM(remaining.pop(0))

    monkeypatch.setattr(background_jobs, "AsyncSessionLocal", factory)


async def test_scheduler_tick_skips_work_when_lock_is_held_elsewhere(monkeypatch) -> None:
    lock_session = _FakeSession("lock", acquire_ok=False)
    work_called = []

    _install_session_factory(monkeypatch, [lock_session])

    async def fake_work(session, tick):
        work_called.append(session)
        return tick + 1

    monkeypatch.setattr(background_jobs, "_run_locked_scheduler_work", fake_work)

    result = await background_jobs._scheduler_tick(3)

    assert result == 3
    assert work_called == []
    assert any("pg_try_advisory_lock" in stmt.lower() for stmt in lock_session.statements)
    assert not any("pg_advisory_unlock" in stmt.lower() for stmt in lock_session.statements)


async def test_scheduler_tick_holds_lock_session_idle_during_work(monkeypatch) -> None:
    lock_session = _FakeSession("lock")
    work_session = _FakeSession("work")
    observed = {}

    _install_session_factory(monkeypatch, [lock_session, work_session])

    async def fake_work(session, tick):
        observed["work_session"] = session
        observed["lock_closed_during_work"] = lock_session.closed
        observed["lock_statements_during_work"] = list(lock_session.statements)
        observed["work_is_lock"] = session is lock_session
        return tick + 1

    monkeypatch.setattr(background_jobs, "_run_locked_scheduler_work", fake_work)

    result = await background_jobs._scheduler_tick(0)

    assert result == 1
    assert observed["work_session"] is work_session
    assert observed["work_is_lock"] is False
    assert observed["lock_closed_during_work"] is False
    assert any(
        "pg_try_advisory_lock" in stmt.lower()
        for stmt in observed["lock_statements_during_work"]
    )
    assert not any(
        "pg_advisory_unlock" in stmt.lower()
        for stmt in observed["lock_statements_during_work"]
    )
    assert any("pg_advisory_unlock" in stmt.lower() for stmt in lock_session.statements)
    assert work_session.statements == []


async def test_scheduler_releases_lock_even_if_work_fails(monkeypatch) -> None:
    lock_session = _FakeSession("lock")
    work_session = _FakeSession("work")
    _install_session_factory(monkeypatch, [lock_session, work_session])

    async def exploding_work(session, tick):
        raise RuntimeError("registrar timeout")

    monkeypatch.setattr(background_jobs, "_run_locked_scheduler_work", exploding_work)

    try:
        await background_jobs._scheduler_tick(0)
        raise AssertionError("expected work failure to propagate")
    except RuntimeError as exc:
        assert "registrar timeout" in str(exc)

    assert any("pg_advisory_unlock" in stmt.lower() for stmt in lock_session.statements)


async def test_locked_work_constructs_openprovider_jobs_on_work_session(
    monkeypatch,
) -> None:
    work_session = _FakeSession("work")
    constructed = []

    class _FakeDomainOps:
        def __init__(self, session):
            constructed.append(("domain_ops", session))

        async def run_provision_retries(self):
            return 0

        async def expire_stale_orders(self):
            return 0

        async def recover_stale_registration_pending(self):
            return {}

        async def run_pending_reconcile(self):
            return 0

        async def run_transfer_reconcile(self):
            return 0

        async def run_stale_pending_alerts(self):
            return 0

    class _FakeTransferOps:
        def __init__(self, session):
            constructed.append(("transfer_ops", session))

        async def run_tick(self):
            return {}

    class _FakeShowcase:
        def __init__(self, session):
            constructed.append(("showcase", session))

        async def refresh_if_due(self):
            constructed.append(("showcase.refresh_if_due", work_session))
            return {"skipped": True}

    class _FakeSoftwareAuction:
        def __init__(self, session):
            constructed.append(("software_auction", session))

        async def end_expired_auctions(self):
            return 0

    class _FakePurchaseNotify:
        def __init__(self, session):
            constructed.append(("purchase_notify", session))

        async def notify_expiring_subscriptions(self):
            return 0

    class _FakeWinnerLifecycle:
        def __init__(self, session):
            constructed.append(("winner_lifecycle", session))

        async def process_reminders_and_forfeits(self):
            return {}

    class _FakeSyncSession:
        def __enter__(self):
            return self

        def __exit__(self, exc_type, exc, tb):
            return False

    monkeypatch.setattr(background_jobs, "DomainRegistrationOpsService", _FakeDomainOps)
    monkeypatch.setattr(background_jobs, "DomainTransferOpsService", _FakeTransferOps)
    monkeypatch.setattr(
        background_jobs.settings,
        "TECH_SUBSCRIPTION_RETRY_ENABLED",
        False,
    )
    monkeypatch.setattr(
        "app.service.domain.showcase_domain_service.ShowcaseDomainService",
        _FakeShowcase,
    )
    monkeypatch.setattr(
        "app.service.cocreation.software_auction_service.SoftwareAuctionService",
        _FakeSoftwareAuction,
    )
    monkeypatch.setattr(
        "app.service.cocreation.software_purchase_notification_service.SoftwarePurchaseNotificationService",
        _FakePurchaseNotify,
    )
    monkeypatch.setattr(
        "app.service.auction.winner_payment_lifecycle.WinnerPaymentLifecycleAsync",
        _FakeWinnerLifecycle,
    )
    monkeypatch.setattr(
        "app.service.community.community_auction_service.CommunityAuctionService.end_expired_auctions",
        lambda db: 0,
    )
    monkeypatch.setattr("app.core.database.SessionLocal", lambda: _FakeSyncSession())

    # tick 119 -> 120 triggers showcase refresh (OpenProvider HTTP).
    result = await background_jobs._run_locked_scheduler_work(work_session, 119)

    assert result == 120
    assert constructed
    assert all(session is work_session for _name, session in constructed)
    showcase_calls = [name for name, _session in constructed if name.startswith("showcase")]
    assert "showcase" in showcase_calls
    assert "showcase.refresh_if_due" in showcase_calls


def test_advisory_lock_sql_is_session_scoped() -> None:
    acquire = str(text("SELECT pg_try_advisory_lock(:key)"))
    release = str(text("SELECT pg_advisory_unlock(:key)"))
    assert "pg_try_advisory_lock" in acquire
    assert "pg_advisory_unlock" in release
    assert background_jobs._SCHEDULER_LOCK_KEY == 874_221_903
