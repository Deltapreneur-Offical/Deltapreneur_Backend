"""Mocked unit tests — no database connection."""

from __future__ import annotations

from datetime import datetime, timedelta, timezone

from app.service.auction.winner_payment_lifecycle import (
    days_left_until,
    payment_due_label,
)
from app.utils.admin_fee_roles import role_waives_auction_platform_fees
from app.entity.user.user_role import UserRole


def test_admin_and_super_admin_waive_platform_fees():
    assert role_waives_auction_platform_fees(UserRole.ADMIN) is True
    assert role_waives_auction_platform_fees(UserRole.SUPER_ADMIN) is True
    assert role_waives_auction_platform_fees(UserRole.USER) is False
    assert role_waives_auction_platform_fees("ROLE_ADMIN") is True
    assert role_waives_auction_platform_fees("SUPER_ADMIN") is True


def test_payment_due_label_days():
    due = (datetime.now(timezone.utc) + timedelta(days=5)).isoformat()
    assert days_left_until(due) == 5
    assert payment_due_label(due) == "Payment due in 5 days"

    due_today = datetime.now(timezone.utc).isoformat()
    assert days_left_until(due_today) == 0
    assert payment_due_label(due_today) == "Payment due today"

    overdue = (datetime.now(timezone.utc) - timedelta(days=1)).isoformat()
    assert days_left_until(overdue) == -1
    assert payment_due_label(overdue) == "Payment overdue"
