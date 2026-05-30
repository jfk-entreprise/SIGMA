"""Modèles SQLAlchemy — Finance : paiements, dépenses, créances."""
from __future__ import annotations

import enum
import uuid
from datetime import datetime
from typing import TYPE_CHECKING

from sqlalchemy import DateTime, ForeignKey, Integer, String, UniqueConstraint, func
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.db.base import Base

if TYPE_CHECKING:
    from app.models.business import Business
    from app.models.service_order import ServiceOrder
    from app.models.user import User


# ---------------------------------------------------------------------------
# Énumérations
# ---------------------------------------------------------------------------

class PaymentMethod(str, enum.Enum):
    CASH         = "CASH"
    MOBILE_MONEY = "MOBILE_MONEY"
    CHEQUE       = "CHEQUE"
    CREDIT       = "CREDIT"


class CreditStatus(str, enum.Enum):
    OUTSTANDING = "OUTSTANDING"
    REPAID      = "REPAID"


# ---------------------------------------------------------------------------
# Paiement lié à une commande
# ---------------------------------------------------------------------------

class Payment(Base):
    """
    Enregistre un encaissement pour une ServiceOrder.
    Un paiement de type CREDIT signale que la créance est enregistrée
    dans la table Credits ; les autres méthodes sont immédiatement soldées.
    """
    __tablename__ = "payments"
    __table_args__ = (
        # Interdit physiquement les doublons de paiement sur une même commande
        UniqueConstraint("order_id", name="uq_payment_order"),
    )

    id: Mapped[uuid.UUID] = mapped_column(
        primary_key=True, default=uuid.uuid4, nullable=False
    )
    order_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("service_orders.id", ondelete="RESTRICT"), nullable=False, index=True
    )
    payment_method: Mapped[str] = mapped_column(String(30), nullable=False)
    amount: Mapped[int] = mapped_column(Integer, nullable=False)
    reference: Mapped[str | None] = mapped_column(
        String(100), nullable=True  # référence mobile money / numéro chèque
    )
    paid_by: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("users.id", ondelete="RESTRICT"), nullable=False
    )
    paid_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False
    )

    # Relations
    order: Mapped[ServiceOrder] = relationship(
        "ServiceOrder", foreign_keys=[order_id], lazy="selectin"
    )
    payer: Mapped[User] = relationship(
        "User", foreign_keys=[paid_by], lazy="selectin"
    )

    def __repr__(self) -> str:
        return (
            f"<Payment id={self.id} order={self.order_id} "
            f"method={self.payment_method} amount={self.amount}>"
        )


# ---------------------------------------------------------------------------
# Dépense opérationnelle
# ---------------------------------------------------------------------------

class Expense(Base):
    """
    Dépense interne d'un commerce (achat matériel, salaire, etc.).
    Pas liée à une commande — constitue le passif du tableau de bord.
    """
    __tablename__ = "expenses"

    id: Mapped[uuid.UUID] = mapped_column(
        primary_key=True, default=uuid.uuid4, nullable=False
    )
    business_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("businesses.id", ondelete="CASCADE"), nullable=False, index=True
    )
    reason: Mapped[str] = mapped_column(String(255), nullable=False)
    amount: Mapped[int] = mapped_column(Integer, nullable=False)
    created_by: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("users.id", ondelete="RESTRICT"), nullable=False
    )
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False
    )

    # Relations
    business: Mapped[Business] = relationship(
        "Business", foreign_keys=[business_id], lazy="selectin"
    )
    creator: Mapped[User] = relationship(
        "User", foreign_keys=[created_by], lazy="selectin"
    )

    def __repr__(self) -> str:
        return f"<Expense id={self.id} business={self.business_id} amount={self.amount}>"


# ---------------------------------------------------------------------------
# Créance client
# ---------------------------------------------------------------------------

class Credit(Base):
    """
    Créance ouverte pour un client d'un commerce.
    Passage à REPAID via repaid_by / repaid_at lorsque le client rembourse.
    """
    __tablename__ = "credits"

    id: Mapped[uuid.UUID] = mapped_column(
        primary_key=True, default=uuid.uuid4, nullable=False
    )
    business_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("businesses.id", ondelete="CASCADE"), nullable=False, index=True
    )
    customer_name: Mapped[str] = mapped_column(String(100), nullable=False)
    customer_phone: Mapped[str | None] = mapped_column(String(20), nullable=True)
    amount: Mapped[int] = mapped_column(Integer, nullable=False)
    reason: Mapped[str | None] = mapped_column(String(255), nullable=True)
    status: Mapped[str] = mapped_column(
        String(20), default=CreditStatus.OUTSTANDING.value, nullable=False
    )
    created_by: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("users.id", ondelete="RESTRICT"), nullable=False
    )
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False
    )
    repaid_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True
    )
    repaid_by: Mapped[uuid.UUID | None] = mapped_column(
        ForeignKey("users.id", ondelete="RESTRICT"), nullable=True
    )

    # Relations
    business: Mapped[Business] = relationship(
        "Business", foreign_keys=[business_id], lazy="selectin"
    )
    creator: Mapped[User] = relationship(
        "User", foreign_keys=[created_by], lazy="selectin"
    )
    repayer: Mapped[User | None] = relationship(
        "User", foreign_keys=[repaid_by], lazy="selectin"
    )

    def __repr__(self) -> str:
        return (
            f"<Credit id={self.id} customer={self.customer_name} "
            f"amount={self.amount} status={self.status}>"
        )
