"""Modèles SQLAlchemy — Commandes de service (WASH, LAUNDRY, PRESSING)."""
from __future__ import annotations

import enum
import uuid
from datetime import datetime
from typing import TYPE_CHECKING

from sqlalchemy import DateTime, ForeignKey, Integer, String, func
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.db.base import Base

if TYPE_CHECKING:
    from app.models.business import Business
    from app.models.item import BusinessItem
    from app.models.user import User


# ---------------------------------------------------------------------------
# Énumération statuts de commande
# ---------------------------------------------------------------------------

class OrderStatus(str, enum.Enum):
    PENDING   = "PENDING"
    PAID      = "PAID"
    CANCELLED = "CANCELLED"


# ---------------------------------------------------------------------------
# Commande de service
# ---------------------------------------------------------------------------

class ServiceOrder(Base):
    """
    Regroupe les items commandés pour une prestation (lavage, blanchisserie…).
    Les champs vehicle_* sont nullable pour supporter LAUNDRY/PRESSING.
    subtotal = Σ(item.total_price) ; total = subtotal - discount.
    """
    __tablename__ = "service_orders"

    id: Mapped[uuid.UUID] = mapped_column(
        primary_key=True, default=uuid.uuid4, nullable=False
    )
    business_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("businesses.id", ondelete="CASCADE"), nullable=False, index=True
    )
    customer_name: Mapped[str | None] = mapped_column(String(100), nullable=True)
    customer_phone: Mapped[str | None] = mapped_column(String(20), nullable=True)

    # Champs spécifiques WASH — nullable pour supporter LAUNDRY/PRESSING
    vehicle_number: Mapped[str | None] = mapped_column(String(20), nullable=True)
    vehicle_color: Mapped[str | None] = mapped_column(String(50), nullable=True)
    wash_type: Mapped[str | None] = mapped_column(String(50), nullable=True)

    status: Mapped[str] = mapped_column(
        String(20), default=OrderStatus.PENDING.value, nullable=False
    )
    subtotal: Mapped[int] = mapped_column(Integer, nullable=False)
    discount: Mapped[int] = mapped_column(Integer, default=0, nullable=False)
    total: Mapped[int] = mapped_column(Integer, nullable=False)

    created_by: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("users.id", ondelete="RESTRICT"), nullable=False, index=True
    )
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False
    )
    completed_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True
    )

    # Relations
    business: Mapped[Business] = relationship(
        "Business", foreign_keys=[business_id], lazy="selectin"
    )
    creator: Mapped[User] = relationship(
        "User", foreign_keys=[created_by], lazy="selectin"
    )
    items: Mapped[list[ServiceOrderItem]] = relationship(
        "ServiceOrderItem", back_populates="order", lazy="selectin"
    )

    def __repr__(self) -> str:
        return (
            f"<ServiceOrder id={self.id} business={self.business_id} "
            f"status={self.status} total={self.total}>"
        )


# ---------------------------------------------------------------------------
# Ligne de commande
# ---------------------------------------------------------------------------

class ServiceOrderItem(Base):
    """
    Snapshot d'un item au moment de la commande.
    unit_price est copié depuis BusinessItem.custom_price à la création
    pour garantir l'immuabilité historique même si le prix change ultérieurement.
    """
    __tablename__ = "service_order_items"

    id: Mapped[uuid.UUID] = mapped_column(
        primary_key=True, default=uuid.uuid4, nullable=False
    )
    order_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("service_orders.id", ondelete="CASCADE"), nullable=False, index=True
    )
    business_item_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("business_items.id", ondelete="RESTRICT"), nullable=False
    )
    quantity: Mapped[int] = mapped_column(Integer, default=1, nullable=False)
    unit_price: Mapped[int] = mapped_column(Integer, nullable=False)   # snapshot prix
    total_price: Mapped[int] = mapped_column(Integer, nullable=False)  # quantity × unit_price

    # Relations
    order: Mapped[ServiceOrder] = relationship(
        "ServiceOrder", back_populates="items"
    )
    item: Mapped[BusinessItem] = relationship(
        "BusinessItem", foreign_keys=[business_item_id], lazy="selectin"
    )

    def __repr__(self) -> str:
        return (
            f"<ServiceOrderItem order={self.order_id} "
            f"item={self.business_item_id} qty={self.quantity}>"
        )
