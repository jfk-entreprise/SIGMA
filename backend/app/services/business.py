"""
Service métier — Gestion des commerces SIGMA.

Responsabilités :
- Création d'un commerce avec validation des règles métier
- Initialisation automatique des items depuis le catalogue central
- Ajout de membres (Manager / Worker)
- Seed idempotent du catalogue item_definitions
"""
from __future__ import annotations

import logging
import uuid
from typing import Sequence

from sqlalchemy import select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.security import hash_password
from app.models.business import Business, BusinessType, BusinessUser, UserRole
from app.models.item import BusinessItem, ItemCategory, ItemDefinition
from app.models.user import User
from app.schemas.business import BusinessCreate, UserCreateManager, UserCreateWorker

logger = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# Données du catalogue central (seed) — Module WASH
# ---------------------------------------------------------------------------

_WASH_SEED: list[dict] = [
    # Véhicules — prix de base du lavage simple
    {"category": ItemCategory.VEHICLE, "name": "4x4",         "default_price": 4000, "display_order": 1, "icon_name": "suv"},
    {"category": ItemCategory.VEHICLE, "name": "Berline",      "default_price": 3000, "display_order": 2, "icon_name": "sedan"},
    {"category": ItemCategory.VEHICLE, "name": "Taxi",         "default_price": 2500, "display_order": 3, "icon_name": "taxi"},
    {"category": ItemCategory.VEHICLE, "name": "Moto",         "default_price": 1500, "display_order": 4, "icon_name": "moto"},
    {"category": ItemCategory.VEHICLE, "name": "Bus / Camion", "default_price": 7000, "display_order": 5, "icon_name": "bus"},
    # Modificateurs de type de lavage (supplément par rapport au prix du véhicule)
    {"category": ItemCategory.WASH_TYPE, "name": "Lavage simple",  "default_price":    0, "display_order": 1, "icon_name": "wash_simple"},
    {"category": ItemCategory.WASH_TYPE, "name": "Lavage complet", "default_price": 1000, "display_order": 2, "icon_name": "wash_full"},
    {"category": ItemCategory.WASH_TYPE, "name": "Lavage premium", "default_price": 2000, "display_order": 3, "icon_name": "wash_premium"},
    {"category": ItemCategory.WASH_TYPE, "name": "Lavage aspiré",  "default_price": 1500, "display_order": 4, "icon_name": "wash_vacuum"},
    # Services complémentaires (add-ons)
    {"category": ItemCategory.ADDON, "name": "Aspirateur", "default_price": 1000, "display_order": 1, "icon_name": "vacuum"},
    {"category": ItemCategory.ADDON, "name": "Moteur",     "default_price": 2000, "display_order": 2, "icon_name": "engine"},
    {"category": ItemCategory.ADDON, "name": "Cire",       "default_price": 1500, "display_order": 3, "icon_name": "wax"},
    {"category": ItemCategory.ADDON, "name": "Parfum",     "default_price":  500, "display_order": 4, "icon_name": "perfume"},
]

_LAUNDRY_SEED: list[dict] = [
    {"category": ItemCategory.GARMENT, "name": "Chemise",        "default_price": 1000, "display_order": 1, "icon_name": "shirt"},
    {"category": ItemCategory.GARMENT, "name": "Pantalon",       "default_price": 1000, "display_order": 2, "icon_name": "pants"},
    {"category": ItemCategory.GARMENT, "name": "Robe",           "default_price": 1500, "display_order": 3, "icon_name": "dress"},
    {"category": ItemCategory.GARMENT, "name": "Couette / Drap", "default_price": 3000, "display_order": 4, "icon_name": "bedding"},
    {"category": ItemCategory.GARMENT, "name": "Repassage seul", "default_price":  500, "display_order": 5, "icon_name": "iron"},
]

_PRESSING_SEED: list[dict] = [
    {"category": ItemCategory.GARMENT, "name": "Costume complet", "default_price": 4000, "display_order": 1, "icon_name": "suit"},
    {"category": ItemCategory.GARMENT, "name": "Veste",           "default_price": 2000, "display_order": 2, "icon_name": "jacket"},
    {"category": ItemCategory.GARMENT, "name": "Robe de soirée",  "default_price": 3500, "display_order": 3, "icon_name": "evening_dress"},
    {"category": ItemCategory.GARMENT, "name": "Manteau",         "default_price": 5000, "display_order": 4, "icon_name": "coat"},
]

_SEED_MAP: dict[BusinessType, list[dict]] = {
    BusinessType.WASH:     _WASH_SEED,
    BusinessType.LAUNDRY:  _LAUNDRY_SEED,
    BusinessType.PRESSING: _PRESSING_SEED,
}


# ---------------------------------------------------------------------------
# Seed catalogue (idempotent — INSERT uniquement si absent)
# ---------------------------------------------------------------------------

async def seed_item_definitions(db: AsyncSession) -> None:
    """
    Peuple la table item_definitions pour tous les types de commerce connus.

    Idempotence :
    - Chaque item est inséré uniquement s'il est absent (SELECT-then-INSERT).
    - La contrainte uq_item_definition_type_cat_name protège des doublons en cas
      de démarrage concurrent : l'IntegrityError au commit est capturée et ignorée.
    - Appelée au démarrage de l'application (main.py lifespan).
    """
    added = 0
    for btype, items in _SEED_MAP.items():
        for item in items:
            result = await db.execute(
                select(ItemDefinition).where(
                    ItemDefinition.business_type == btype,
                    ItemDefinition.category == item["category"],
                    ItemDefinition.name == item["name"],
                )
            )
            if result.scalar_one_or_none() is None:
                db.add(ItemDefinition(
                    id=uuid.uuid4(),
                    business_type=btype,
                    **item,
                ))
                added += 1

    if added > 0:
        try:
            await db.commit()
            logger.info("✅ Catalogue item_definitions : %d item(s) ajouté(s).", added)
        except IntegrityError:
            # Démarrage concurrent : une autre instance a inséré en premier — aucun doublon.
            await db.rollback()
            logger.info(
                "✅ Catalogue item_definitions déjà à jour "
                "(conflit de démarrage concurrent ignoré)."
            )
    else:
        logger.info("✅ Catalogue item_definitions déjà à jour (aucun ajout nécessaire).")


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
    - Copie automatique des items depuis item_definitions.

    Returns:
        Le Business créé avec ses items initialisés.
    """
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
    await db.flush()

    db.add(BusinessUser(
        id=uuid.uuid4(),
        business_id=business.id,
        user_id=owner.id,
        role=UserRole.OWNER,
    ))

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
    Copie les ItemDefinition actives du catalogue vers business_items.
    custom_price hérite de default_price.
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

async def get_user_business(db: AsyncSession, user: User) -> Business | None:
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
# Récupération des items d'un commerce
# ---------------------------------------------------------------------------

async def get_business_items(
    db: AsyncSession,
    business_id: uuid.UUID,
    active_only: bool = True,
) -> Sequence[BusinessItem]:
    """Retourne les items d'un commerce, triés par ordre d'affichage."""
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
    - Numéro déjà enregistré → réutilise le compte existant sans modifier le mot de passe.
    - Numéro nouveau → crée un compte avec mot de passe fourni (MANAGER) ou aléatoire (WORKER).
      Un Worker peut ultérieurement finaliser son compte via /auth/register (flux OTP).
    - Doublon d'appartenance → IntegrityError levée (capturée dans le router → 409).
    """
    result = await db.execute(
        select(User).where(User.phone_number == data.phone_number)
    )
    user = result.scalar_one_or_none()

    if user is None:
        hashed = (
            hash_password(data.password)
            if isinstance(data, UserCreateManager)
            else hash_password(uuid.uuid4().hex)  # Mot de passe temporaire pour WORKER
        )
        user = User(
            id=uuid.uuid4(),
            phone_number=data.phone_number,
            full_name=data.full_name,
            hashed_password=hashed,
            is_active=True,
        )
        db.add(user)
        await db.flush()

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
