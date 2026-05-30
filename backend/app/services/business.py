"""
Service métier — Gestion des commerces SIGMA.

Responsabilités :
- Création d'un commerce avec validation des règles métier
- Initialisation automatique des items depuis le catalogue central
- Ajout de membres (Manager / Worker)
- Seed du catalogue item_definitions
"""
from __future__ import annotations

import logging
import uuid
from typing import Sequence

from sqlalchemy import select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.security import hash_password
from app.models.business import Business, BusinessUser, BusinessType, UserRole
from app.models.item import BusinessItem, ItemCategory, ItemDefinition
from app.models.user import User
from app.schemas.business import BusinessCreate, UserCreateManager, UserCreateWorker

logger = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# Données du catalogue central (seed) — Module WASH
# ---------------------------------------------------------------------------

_WASH_SEED: list[dict] = [
    # Véhicules — prix de base du lavage simple
    {"category": ItemCategory.VEHICLE, "name": "4x4",          "default_price": 4000, "display_order": 1, "icon_name": "suv"},
    {"category": ItemCategory.VEHICLE, "name": "Berline",       "default_price": 3000, "display_order": 2, "icon_name": "sedan"},
    {"category": ItemCategory.VEHICLE, "name": "Taxi",          "default_price": 2500, "display_order": 3, "icon_name": "taxi"},
    {"category": ItemCategory.VEHICLE, "name": "Moto",          "default_price": 1500, "display_order": 4, "icon_name": "moto"},
    {"category": ItemCategory.VEHICLE, "name": "Bus / Camion",  "default_price": 7000, "display_order": 5, "icon_name": "bus"},
    # Modificateurs de type de lavage (appliqués en supplément du véhicule)
    {"category": ItemCategory.WASH_TYPE, "name": "Lavage simple",   "default_price":    0, "display_order": 1, "icon_name": "wash_simple"},
    {"category": ItemCategory.WASH_TYPE, "name": "Lavage complet",  "default_price": 1000, "display_order": 2, "icon_name": "wash_full"},
    {"category": ItemCategory.WASH_TYPE, "name": "Lavage premium",  "default_price": 2000, "display_order": 3, "icon_name": "wash_premium"},
    {"category": ItemCategory.WASH_TYPE, "name": "Lavage aspiré",   "default_price": 1500, "display_order": 4, "icon_name": "wash_vacuum"},
    # Services complémentaires
    {"category": ItemCategory.ADDON, "name": "Aspirateur", "default_price": 1000, "display_order": 1, "icon_name": "vacuum"},
    {"category": ItemCategory.ADDON, "name": "Moteur",     "default_price": 2000, "display_order": 2, "icon_name": "engine"},
    {"category": ItemCategory.ADDON, "name": "Cire",       "default_price": 1500, "display_order": 3, "icon_name": "wax"},
    {"category": ItemCategory.ADDON, "name": "Parfum",     "default_price":  500, "display_order": 4, "icon_name": "perfume"},
]

_SEED_MAP: dict[str, list[dict]] = {
    BusinessType.WASH: _WASH_SEED,
}


# ---------------------------------------------------------------------------
# Seed catalogue (idempotent — INSERT uniquement si absent)
# ---------------------------------------------------------------------------

async def seed_item_definitions(db: AsyncSession) -> None:
    """
    Peuple la table item_definitions pour tous les types de commerce connus.
    Opération idempotente : n'insère que les définitions manquantes.
    Appelée au démarrage de l'application.
    """
    for btype, items in _SEED_MAP.items():
        for item in items:
            existing = await db.execute(
                select(ItemDefinition).where(
                    ItemDefinition.business_type == btype,
                    ItemDefinition.category == item["category"],
                    ItemDefinition.name == item["name"],
                )
            )
            if existing.scalar_one_or_none() is None:
                db.add(ItemDefinition(
                    id=uuid.uuid4(),
                    business_type=btype,
                    **item,
                ))
    await db.commit()
    logger.info("✅ Catalogue item_definitions synchronisé.")


# ---------------------------------------------------------------------------
# Création d'un commerce
# ---------------------------------------------------------------------------

async def create_business(
    db: AsyncSession,
    owner: User,
    data: BusinessCreate,
) -> Business:
    """
    Crée un commerce pour l'owner donné.

    Règles métier :
    - L'owner ne peut pas posséder plusieurs commerces actifs (409 géré dans le router).
    - Le type de commerce doit exister dans le catalogue (validé par Pydantic).
    - Copie automatique des items depuis item_definitions.

    Returns:
        Le Business créé avec ses items initialisés.
    """
    # 1. Créer le commerce
    business = Business(
        id=uuid.uuid4(),
        name=data.name,
        business_type=data.business_type,
        phone=data.phone,
        location=data.location,
        owner_id=owner.id,
        is_active=True,
    )
    db.add(business)
    await db.flush()  # Obtenir l'ID sans commit pour la FK des items

    # 2. Créer l'appartenance OWNER
    membership = BusinessUser(
        id=uuid.uuid4(),
        business_id=business.id,
        user_id=owner.id,
        role=UserRole.OWNER,
    )
    db.add(membership)

    # 3. Copier les items du catalogue vers le commerce
    await _initialize_business_items(db, business)

    await db.flush()
    await db.refresh(business)

    logger.info(
        "[BUSINESS] ✅ Commerce créé | id=%s | name=%s | type=%s | owner=%s",
        business.id, business.name, business.business_type, owner.id,
    )
    return business


async def _initialize_business_items(
    db: AsyncSession,
    business: Business,
) -> list[BusinessItem]:
    """
    Copie les ItemDefinition actives correspondant au type de commerce
    vers business_items avec custom_price = default_price.
    """
    result = await db.execute(
        select(ItemDefinition).where(
            ItemDefinition.business_type == business.business_type,
            ItemDefinition.is_active.is_(True),
        ).order_by(ItemDefinition.display_order)
    )
    definitions = result.scalars().all()

    created: list[BusinessItem] = []
    for defn in definitions:
        item = BusinessItem(
            id=uuid.uuid4(),
            business_id=business.id,
            item_definition_id=defn.id,
            custom_name=defn.name,
            custom_price=defn.default_price,
            is_active=True,
            display_order=defn.display_order,
        )
        db.add(item)
        created.append(item)

    logger.debug(
        "[BUSINESS] %d items initialisés pour le commerce %s (type=%s)",
        len(created), business.id, business.business_type,
    )
    return created


# ---------------------------------------------------------------------------
# Récupération du commerce de l'utilisateur
# ---------------------------------------------------------------------------

async def get_user_business(
    db: AsyncSession, user: User
) -> Business | None:
    """Retourne le premier commerce actif de l'utilisateur (owner ou membre)."""
    result = await db.execute(
        select(Business)
        .join(BusinessUser, BusinessUser.business_id == Business.id)
        .where(
            BusinessUser.user_id == user.id,
            Business.is_active.is_(True),
        )
        .order_by(BusinessUser.created_at)
        .limit(1)
    )
    return result.scalar_one_or_none()


# ---------------------------------------------------------------------------
# Récupération des items actifs d'un commerce
# ---------------------------------------------------------------------------

async def get_business_items(
    db: AsyncSession,
    business_id: uuid.UUID,
    active_only: bool = True,
) -> Sequence[BusinessItem]:
    """Retourne les items d'un commerce, triés par catégorie et ordre d'affichage."""
    stmt = (
        select(BusinessItem)
        .where(BusinessItem.business_id == business_id)
        .order_by(BusinessItem.display_order)
    )
    if active_only:
        stmt = stmt.where(BusinessItem.is_active.is_(True))
    result = await db.execute(stmt)
    return result.scalars().all()


# ---------------------------------------------------------------------------
# Mise à jour d'un item (Owner uniquement)
# ---------------------------------------------------------------------------

async def update_business_item(
    db: AsyncSession,
    business_id: uuid.UUID,
    item_id: uuid.UUID,
    custom_price: int | None,
    is_active: bool | None,
    custom_name: str | None,
) -> BusinessItem:
    """
    Met à jour le prix, l'état ou le nom personnalisé d'un item.
    Lève ValueError si l'item n'appartient pas au commerce.
    """
    item = await db.get(BusinessItem, item_id)

    if item is None or item.business_id != business_id:
        raise ValueError(f"Item {item_id} introuvable pour ce commerce.")

    if custom_price is not None:
        item.custom_price = custom_price
    if is_active is not None:
        item.is_active = is_active
    if custom_name is not None:
        item.custom_name = custom_name

    await db.flush()
    await db.refresh(item)
    return item


# ---------------------------------------------------------------------------
# Ajout d'un membre (Manager ou Worker)
# ---------------------------------------------------------------------------

async def add_staff_member(
    db: AsyncSession,
    business: Business,
    data: UserCreateManager | UserCreateWorker,
) -> BusinessUser:
    """
    Crée (ou retrouve) un utilisateur et l'associe au commerce avec le rôle donné.

    Comportement :
    - Si le numéro de téléphone est déjà enregistré, on réutilise l'utilisateur existant.
    - Si l'utilisateur est déjà membre du commerce, on lève IntegrityError (409 dans le router).
    """
    # 1. Chercher ou créer l'utilisateur
    result = await db.execute(
        select(User).where(User.phone_number == data.phone_number)
    )
    user = result.scalar_one_or_none()

    if user is None:
        hashed = hash_password(data.password) if isinstance(data, UserCreateManager) else hash_password(uuid.uuid4().hex)
        user = User(
            id=uuid.uuid4(),
            phone_number=data.phone_number,
            full_name=data.full_name,
            hashed_password=hashed,
            is_active=True,
        )
        db.add(user)
        await db.flush()

    # 2. Créer l'appartenance
    membership = BusinessUser(
        id=uuid.uuid4(),
        business_id=business.id,
        user_id=user.id,
        role=data.role,
    )
    db.add(membership)
    await db.flush()
    await db.refresh(membership)

    logger.info(
        "[BUSINESS] Membre ajouté | business=%s | user=%s | role=%s",
        business.id, user.id, data.role,
    )
    return membership
