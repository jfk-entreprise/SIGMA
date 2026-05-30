"""Modèles SQLAlchemy — Catalogue central et items par commerce."""
from __future__ import annotations

import uuid
from datetime import datetime
from typing import TYPE_CHECKING

from sqlalchemy import Boolean, DateTime, ForeignKey, Integer, String, UniqueConstraint, func
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.db.base import Base

if TYPE_CHECKING:
    from app.models.business import Business


# ---------------------------------------------------------------------------
# Catégories d'items (constantes)
# ---------------------------------------------------------------------------

class ItemCategory:
    VEHICLE   = "VEHICLE"    # Type de véhicule (4x4, Berline…)
    WASH_TYPE = "WASH_TYPE"  # Modificateur de lavage (Simple, Complet…)
    ADDON     = "ADDON"      # Service complémentaire (Aspirateur, Moteur…)

    ALL = [VEHICLE, WASH_TYPE, ADDON]


# ---------------------------------------------------------------------------
# Catalogue central des items (une ligne par type de commerce)
# ---------------------------------------------------------------------------

class ItemDefinition(Base):
    """
    Table centrale immuable : référentiel des prestations par type de commerce.
    Peuplée via seed, non modifiable par les utilisateurs.
    """
    __tablename__ = "item_definitions"

    id: Mapped[uuid.UUID] = mapped_column(
        primary_key=True, default=uuid.uuid4, nullable=False
    )
    business_type: Mapped[str] = mapped_column(String(20), nullable=False, index=True)
    category: Mapped[str] = mapped_column(String(20), nullable=False)
    name: Mapped[str] = mapped_column(String(100), nullable=False)
    default_price: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    display_order: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    is_active: Mapped[bool] = mapped_column(Boolean, default=True, nullable=False)
    icon_name: Mapped[str | None] = mapped_column(String(50), nullable=True)

    # Relations
    business_items: Mapped[list[BusinessItem]] = relationship(
        "BusinessItem", back_populates="definition", lazy="selectin"
    )

    def __repr__(self) -> str:
        return f"<ItemDefinition {self.business_type}/{self.category}/{self.name}>"


# ---------------------------------------------------------------------------
# Items activés par commerce (copie personnalisable du catalogue)
# ---------------------------------------------------------------------------

class BusinessItem(Base):
    """
    Copie de ItemDefinition pour un commerce donné.
    L'owner peut modifier custom_price et is_active.
    """
    __tablename__ = "business_items"
    __table_args__ = (
        UniqueConstraint(
            "business_id", "item_definition_id",
            name="uq_business_item_definition"
        ),
    )

    id: Mapped[uuid.UUID] = mapped_column(
        primary_key=True, default=uuid.uuid4, nullable=False
    )
    business_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("businesses.id", ondelete="CASCADE"), nullable=False, index=True
    )
    item_definition_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("item_definitions.id", ondelete="RESTRICT"), nullable=False
    )
    # Nom personnalisable (hérite du catalogue par défaut)
    custom_name: Mapped[str] = mapped_column(String(100), nullable=False)
    # Prix personnalisable (hérite de default_price au moment de la création)
    custom_price: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    is_active: Mapped[bool] = mapped_column(Boolean, default=True, nullable=False)
    display_order: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False
    )

    # Relations
    business: Mapped[Business] = relationship(
        "Business", back_populates="items"
    )
    definition: Mapped[ItemDefinition] = relationship(
        "ItemDefinition", back_populates="business_items", lazy="selectin"
    )

    @property
    def category(self) -> str:
        return self.definition.category if self.definition else ""

    def __repr__(self) -> str:
        return f"<BusinessItem business={self.business_id} item={self.custom_name}>"
