"""
Service métier — Commandes de service SIGMA.

Responsabilités :
- Création d'une commande avec validation des items (tenant-isolated)
- Récupération et listing des commandes
- Annulation avec contrôle des droits selon le rôle
"""
from __future__ import annotations

import logging
import uuid
from typing import Sequence

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload

from app.models.business import Business
from app.models.item import BusinessItem
from app.models.service_order import OrderStatus, ServiceOrder, ServiceOrderItem
from app.models.user import User
from app.schemas.order import OrderCreate

logger = logging.getLogger(__name__)


# ---------------------------------------------------------------------------
# Création d'une commande
# ---------------------------------------------------------------------------

async def create_order(
    db: AsyncSession,
    business: Business,
    creator: User,
    data: OrderCreate,
) -> ServiceOrder:
    """
    Crée une commande de service pour le commerce donné.

    Validation par item :
    - L'item doit appartenir au commerce (isolation tenant) → 404
    - L'item doit être actif (is_active=True) → 400

    Les prix sont snapshotés depuis BusinessItem.custom_price au moment de
    la commande pour garantir l'immuabilité historique.

    Lève ValueError si une règle métier est violée (conversion en HTTPException
    dans le router).
    """
    order_items: list[ServiceOrderItem] = []

    for item_data in data.items:
        # Charger le BusinessItem et vérifier l'appartenance au commerce
        result = await db.execute(
            select(BusinessItem).where(BusinessItem.id == item_data.business_item_id)
        )
        business_item = result.scalar_one_or_none()

        if business_item is None or business_item.business_id != business.id:
            raise ValueError(
                f"Item {item_data.business_item_id} introuvable pour ce commerce."
            )

        if not business_item.is_active:
            raise ValueError(
                f"L'item '{business_item.custom_name}' est désactivé et ne peut pas "
                "être ajouté à une commande."
            )

        unit_price = business_item.custom_price
        total_price = item_data.quantity * unit_price

        order_items.append(ServiceOrderItem(
            id=uuid.uuid4(),
            business_item_id=business_item.id,
            quantity=item_data.quantity,
            unit_price=unit_price,
            total_price=total_price,
        ))

    subtotal = sum(oi.total_price for oi in order_items)

    if data.discount > subtotal:
        raise ValueError(
            f"La réduction ({data.discount} FCFA) ne peut pas dépasser "
            f"le sous-total de la commande ({subtotal} FCFA)."
        )

    total = subtotal - data.discount

    order = ServiceOrder(
        id=uuid.uuid4(),
        business_id=business.id,
        customer_name=data.customer_name,
        customer_phone=data.customer_phone,
        vehicle_number=data.vehicle_number,
        vehicle_color=data.vehicle_color,
        wash_type=data.wash_type,
        status=OrderStatus.PENDING.value,
        subtotal=subtotal,
        discount=data.discount,
        total=total,
        created_by=creator.id,
    )

    db.add(order)
    await db.flush()  # Obtenir order.id avant d'insérer les items

    for oi in order_items:
        oi.order_id = order.id
        db.add(oi)

    await db.flush()
    await db.refresh(order)

    logger.info(
        "[ORDER] Commande créée | id=%s | business=%s | creator=%s | total=%d",
        order.id, business.id, creator.id, order.total,
    )
    return order


# ---------------------------------------------------------------------------
# Récupération d'une commande (tenant-isolated)
# ---------------------------------------------------------------------------

async def get_order(
    db: AsyncSession,
    business_id: uuid.UUID,
    order_id: uuid.UUID,
) -> ServiceOrder | None:
    """
    Retourne la commande identifiée par order_id appartenant à business_id.
    Retourne None si la commande n'existe pas ou appartient à un autre commerce.
    Les items sont chargés via selectinload.
    """
    result = await db.execute(
        select(ServiceOrder)
        .where(
            ServiceOrder.id == order_id,
            ServiceOrder.business_id == business_id,
        )
        .options(selectinload(ServiceOrder.items))
    )
    return result.scalar_one_or_none()


# ---------------------------------------------------------------------------
# Listing des commandes (tenant-isolated)
# ---------------------------------------------------------------------------

async def list_orders(
    db: AsyncSession,
    business_id: uuid.UUID,
    status: str | None = None,
) -> Sequence[ServiceOrder]:
    """
    Retourne les commandes d'un commerce, triées par date décroissante (max 100).
    Le filtre status est optionnel (PENDING | PAID | CANCELLED).
    """
    stmt = (
        select(ServiceOrder)
        .where(ServiceOrder.business_id == business_id)
        .options(selectinload(ServiceOrder.items))
        .order_by(ServiceOrder.created_at.desc())
        .limit(100)
    )
    if status is not None:
        stmt = stmt.where(ServiceOrder.status == status)

    result = await db.execute(stmt)
    return result.scalars().all()


# ---------------------------------------------------------------------------
# Annulation d'une commande
# ---------------------------------------------------------------------------

async def cancel_order(
    db: AsyncSession,
    order: ServiceOrder,
    current_user: User,
    membership_role: str,
) -> ServiceOrder:
    """
    Annule une commande selon les règles de rôle.

    Règles :
    - La commande doit être en statut PENDING (lève ValueError si PAID ou CANCELLED).
    - OWNER peut annuler n'importe quelle commande du commerce.
    - MANAGER et WORKER ne peuvent annuler que leurs propres commandes
      (created_by == current_user.id).

    Lève ValueError avec un message clair si une règle est violée.
    """
    if order.status == OrderStatus.PAID.value:
        raise ValueError(
            "Impossible d'annuler une commande déjà payée (statut PAID)."
        )

    if order.status == OrderStatus.CANCELLED.value:
        raise ValueError(
            "Cette commande est déjà annulée (statut CANCELLED)."
        )

    # À ce stade order.status == PENDING
    role_upper = membership_role.upper()

    if role_upper != "OWNER":
        # MANAGER et WORKER ne peuvent annuler que leurs propres commandes
        if order.created_by != current_user.id:
            raise ValueError(
                "Vous n'êtes pas autorisé à annuler cette commande. "
                "Seul le propriétaire ou le créateur de la commande peut l'annuler."
            )

    order.status = OrderStatus.CANCELLED.value
    await db.flush()
    await db.refresh(order)

    logger.info(
        "[ORDER] Commande annulée | id=%s | by=%s | role=%s",
        order.id, current_user.id, membership_role,
    )
    return order
