"""Modèles SQLAlchemy — Rapports journaliers consolidés."""
from __future__ import annotations

import uuid
from datetime import date, datetime
from typing import TYPE_CHECKING

from sqlalchemy import Date, DateTime, ForeignKey, Integer, UniqueConstraint
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.db.base import Base

if TYPE_CHECKING:
    from app.models.business import Business


class DailyReport(Base):
    """
    Rapport journalier consolidé pour un commerce.
    Généré/mis à jour après chaque événement financier (paiement, dépense, créance).

    Formule : net_income = gross_income - (expenses + credits)

    Upsert garanti par UniqueConstraint(business_id, date).
    """
    __tablename__ = "daily_reports"
    __table_args__ = (
        UniqueConstraint("business_id", "date", name="uq_daily_report_business_date"),
    )

    id: Mapped[uuid.UUID] = mapped_column(
        primary_key=True, default=uuid.uuid4, nullable=False
    )
    business_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("businesses.id", ondelete="CASCADE"), nullable=False, index=True
    )
    date: Mapped[date] = mapped_column(Date, nullable=False)
    total_orders: Mapped[int] = mapped_column(Integer, default=0, nullable=False)
    gross_income: Mapped[int] = mapped_column(Integer, default=0, nullable=False)
    expenses: Mapped[int] = mapped_column(Integer, default=0, nullable=False)
    credits: Mapped[int] = mapped_column(Integer, default=0, nullable=False)
    net_income: Mapped[int] = mapped_column(Integer, default=0, nullable=False)
    generated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False
    )

    business: Mapped[Business] = relationship(
        "Business", foreign_keys=[business_id], lazy="selectin"
    )

    def __repr__(self) -> str:
        return (
            f"<DailyReport business={self.business_id} "
            f"date={self.date} net_income={self.net_income}>"
        )
