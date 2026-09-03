import uuid
import pytest
from unittest.mock import AsyncMock, MagicMock, patch
from app.entity.user.app_user import AppUser
from app.entity.user.edge_points_redemption import EdgePointsRedemption, RedemptionStatus
from app.entity.user.edge_points_history import EdgePointsHistory, EdgePointsTransactionType
from app.entity.user.referral_track import ReferralTrack
from app.service.user.edge_points_service import EdgePointsService
from app.tests.entity_registry import ensure_entities_imported

ensure_entities_imported()


def _mock_scalar(val):
    mock_res = MagicMock()
    mock_res.scalar.return_value = val
    mock_res.scalar_one_or_none.return_value = val
    return mock_res


@pytest.mark.asyncio
async def test_calculate_redemption_not_requested() -> None:
    session = AsyncMock()
    user = AppUser(edge_points=1000)
    final_amount, points_redeemed = await EdgePointsService.calculate_redemption(
        session, user, order_amount_inr=150.0, redeem_requested=False
    )
    assert final_amount == 150.0
    assert points_redeemed == 0


@pytest.mark.asyncio
async def test_calculate_redemption_zero_points() -> None:
    session = AsyncMock()
    session.execute.return_value = _mock_scalar(0)
    user = AppUser(edge_points=0)
    final_amount, points_redeemed = await EdgePointsService.calculate_redemption(
        session, user, order_amount_inr=150.0, redeem_requested=True
    )
    assert final_amount == 150.0
    assert points_redeemed == 0


@pytest.mark.asyncio
async def test_calculate_redemption_partial_points() -> None:
    # User has 3000 points (worth ₹300). Order is ₹1000.
    session = AsyncMock()
    session.execute.return_value = _mock_scalar(0)

    user = AppUser(edge_points=3000)
    final_amount, points_redeemed = await EdgePointsService.calculate_redemption(
        session, user, order_amount_inr=1000.0, redeem_requested=True
    )
    assert final_amount == 700.0
    assert points_redeemed == 3000


@pytest.mark.asyncio
async def test_calculate_redemption_capped_at_500_rupees() -> None:
    # User has 8000 points (worth ₹800). Max discount is capped at ₹500 (5000 points).
    session = AsyncMock()
    session.execute.return_value = _mock_scalar(0)

    user = AppUser(edge_points=8000)
    final_amount, points_redeemed = await EdgePointsService.calculate_redemption(
        session, user, order_amount_inr=1000.0, redeem_requested=True
    )
    assert final_amount == 500.0
    assert points_redeemed == 5000


@pytest.mark.asyncio
async def test_calculate_redemption_prevent_double_spending() -> None:
    # User has 5000 points but 2000 are pending in another order.
    # Available is 3000 points (worth ₹300).
    session = AsyncMock()
    session.execute.return_value = _mock_scalar(2000)

    user = AppUser(edge_points=5000)
    final_amount, points_redeemed = await EdgePointsService.calculate_redemption(
        session, user, order_amount_inr=500.0, redeem_requested=True
    )
    assert final_amount == 200.0
    assert points_redeemed == 3000


@pytest.mark.asyncio
async def test_calculate_redemption_capped_by_order_value() -> None:
    # User has 5000 points (worth ₹500). Order is ₹100.
    # Maximum points that can be redeemed is 1000 points (worth ₹100).
    session = AsyncMock()
    session.execute.return_value = _mock_scalar(0)

    user = AppUser(edge_points=5000)
    final_amount, points_redeemed = await EdgePointsService.calculate_redemption(
        session, user, order_amount_inr=100.0, redeem_requested=True
    )
    assert final_amount == 0.0
    assert points_redeemed == 1000


@pytest.mark.asyncio
async def test_track_referral_referrer_not_found() -> None:
    session = AsyncMock()
    session.execute.return_value = _mock_scalar(None)

    ref_id = uuid.uuid4()
    list_id = uuid.uuid4()
    result = await EdgePointsService.track_referral(
        session, referrer_id=ref_id, listing_id=list_id, listing_type="domain", visitor_ip="127.0.0.1"
    )
    assert result["success"] is False
    assert "Referrer not found" in result["message"]


@pytest.mark.asyncio
async def test_track_referral_self_referral() -> None:
    session = AsyncMock()
    referrer = AppUser(id=uuid.uuid4(), edge_points=0)
    session.execute.return_value = _mock_scalar(referrer)

    result = await EdgePointsService.track_referral(
        session, referrer_id=referrer.id, listing_id=uuid.uuid4(), listing_type="domain", visitor_ip="127.0.0.1", visitor_user=referrer
    )
    assert result["success"] is False
    assert "Self-referrals are not rewarded" in result["message"]


@pytest.mark.asyncio
async def test_track_referral_duplicate_visitor_ip() -> None:
    session = AsyncMock()
    session.add = MagicMock()
    referrer = AppUser(id=uuid.uuid4(), edge_points=100)

    # Duplicate is detected by the database: the guarded INSERT returns no row.
    dup_result = MagicMock()
    dup_result.first.return_value = None
    session.execute.side_effect = [
        _mock_scalar(referrer),
        dup_result,
    ]

    result = await EdgePointsService.track_referral(
        session, referrer_id=referrer.id, listing_id=uuid.uuid4(), listing_type="domain", visitor_ip="127.0.0.1"
    )
    assert result["success"] is True
    assert result["points_awarded"] == 0
    assert referrer.edge_points == 100  # no points added


@pytest.mark.asyncio
@patch("app.service.user.edge_points_service.notification_connection_manager")
async def test_track_referral_success(mock_ws_manager) -> None:
    session = AsyncMock()
    session.add = MagicMock()
    referrer = AppUser(id=uuid.uuid4(), edge_points=100)

    # Atomic INSERT succeeds and returns the new row id.
    inserted_result = MagicMock()
    inserted_result.first.return_value = (uuid.uuid4(),)
    session.execute.side_effect = [
        _mock_scalar(referrer),
        inserted_result,
    ]

    result = await EdgePointsService.track_referral(
        session, referrer_id=referrer.id, listing_id=uuid.uuid4(), listing_type="domain", visitor_ip="127.0.0.1"
    )
    assert result["success"] is True
    assert result["points_awarded"] == 20
    assert referrer.edge_points == 120
    session.add.assert_any_call(referrer)
