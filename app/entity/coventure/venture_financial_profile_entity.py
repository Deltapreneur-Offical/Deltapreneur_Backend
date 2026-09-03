"""Financial profile for venture sale listings."""

from __future__ import annotations

import uuid
from typing import TYPE_CHECKING, Optional

from sqlalchemy import BigInteger, Float, ForeignKey, String, Text
from sqlalchemy.dialects.postgresql import UUID
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.entity.base import Base, TimestampMixin, UUIDPrimaryKeyMixin
from app.utils.venture_enums import CompanyType

if TYPE_CHECKING:
    from app.entity.coventure.venture_entity import Venture


class VentureFinancialProfile(UUIDPrimaryKeyMixin, TimestampMixin, Base):
    __tablename__ = "venture_financial_profiles"

    venture_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("ventures.id", ondelete="CASCADE"),
        nullable=False,
        unique=True,
    )
    registration_number: Mapped[Optional[str]] = mapped_column(String(128), nullable=True)
    company_type: Mapped[Optional[CompanyType]] = mapped_column(
        String(64),
        nullable=True,
    )
    market_cap_inr: Mapped[Optional[int]] = mapped_column(BigInteger, nullable=True)
    current_revenue_inr: Mapped[Optional[int]] = mapped_column(BigInteger, nullable=True)
    profitability_status: Mapped[Optional[str]] = mapped_column(String(64), nullable=True)
    profitability_amount_inr: Mapped[Optional[int]] = mapped_column(BigInteger, nullable=True)
    funding_info: Mapped[Optional[str]] = mapped_column(Text, nullable=True)
    desired_investment_inr: Mapped[Optional[int]] = mapped_column(BigInteger, nullable=True)
    desired_valuation_inr: Mapped[Optional[int]] = mapped_column(BigInteger, nullable=True)
    minimum_acceptable_offer_inr: Mapped[Optional[int]] = mapped_column(BigInteger, nullable=True)
    team_size: Mapped[Optional[int]] = mapped_column(BigInteger, nullable=True)
    traction_metrics: Mapped[Optional[str]] = mapped_column(Text, nullable=True)

    venture: Mapped["Venture"] = relationship(
        "Venture",
        back_populates="financial_profile",
        foreign_keys=[venture_id],
    )
