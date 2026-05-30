"""Modèles SQLAlchemy — Commerce et appartenance utilisateur-commerce."""
from __future__ import annotations

import enum
import uuid
from datetime import datetime
from typing import TYPE_CHECKING

from sqlalchemy import (
    Boolean, DateTime, ForeignKey, String, UniqueConstraint, func
)
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.db.base import Base

if TYPE_CHECKING:
    from app.models.user import User
    from app.models.item import BusinessItem


# ---------------------------------------------------------------------------
# Énumérations — str, enum.Enum garantit l'immutabilité et le typage fort.
# Stockées comme String en base pour la portabilité multi-backend.
# ---------------------------------------------------------------------------

class BusinessType(str, enum.Enum):
    WASH     = "WASH"
    LAUNDRY  = "LAUNDRY"
    PRESSING = "PRESSING"


class UserRole(str, enum.Enum):
    OWNER   = "OWNER"
    MANAGER = "MANAGER"
    WORKER  = "WORKER"


# ---------------------------------------------------------------------------
# Modèle Commerce
# ---------------------------------------------------------------------------

class Business(Base):
    __tablename__ = "businesses"

    id: Mapped[uuid.UUID] = mapped_column(
        primary_key=True, default=uuid.uuid4, nullable=False
    )
    name: Mapped[str] = mapped_column(String(100), nullable=False)
    business_type: Mapped[str] = mapped_column(String(20), nullable=False, index=True)
    phone: Mapped[str | None] = mapped_column(String(20), nullable=True)
    location: Mapped[str | None] = mapped_column(String(255), nullable=True)
    is_active: Mapped[bool] = mapped_column(Boolean, default=True, nullable=False)
    owner_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("users.id", ondelete="RESTRICT"), nullable=False, index=True
    )
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False
    )

    # Relations
    owner: Mapped[User] = relationship(
        "User", foreign_keys=[owner_id], lazy="selectin"
    )
    memberships: Mapped[list[BusinessUser]] = relationship(
        "BusinessUser", back_populates="business", lazy="selectin"
    )
    items: Mapped[list[BusinessItem]] = relationship(
        "BusinessItem", back_populates="business", lazy="selectin"
    )

    def __repr__(self) -> str:
        return f"<Business id={self.id} name={self.name} type={self.business_type}>"


# ---------------------------------------------------------------------------
# Modèle Appartenance (User ↔ Business avec rôle)
# ---------------------------------------------------------------------------

class BusinessUser(Base):
    __tablename__ = "business_users"
    __table_args__ = (
        UniqueConstraint("business_id", "user_id", name="uq_business_user"),
    )

    id: Mapped[uuid.UUID] = mapped_column(
        primary_key=True, default=uuid.uuid4, nullable=False
    )
    business_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("businesses.id", ondelete="CASCADE"), nullable=False, index=True
    )
    user_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("users.id", ondelete="CASCADE"), nullable=False, index=True
    )
    role: Mapped[str] = mapped_column(String(20), nullable=False)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False
    )

    # Relations
    business: Mapped[Business] = relationship(
        "Business", back_populates="memberships", lazy="selectin"
    )
    user: Mapped[User] = relationship(
        "User", back_populates="business_memberships", lazy="selectin"
    )

    def __repr__(self) -> str:
        return f"<BusinessUser user={self.user_id} role={self.role}>"
