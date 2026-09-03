from unittest.mock import AsyncMock

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
