"""
Router FastAPI — /api/v1/orders/*

Endpoints :
    POST   /                    → Crée une commande (tout membre avec un commerce)
    GET    /                    → Liste les commandes (filtre optionnel ?status=)
    GET    /{order_id}          → Détails d'une commande
    PATCH  /{order_id}/cancel   → Annule une commande
    POST   /{order_id}/pay      → Enregistre un paiement

Isolation multi-tenant : le business_id est TOUJOURS extrait du JWT
via get_current_business_user — jamais depuis un paramètre URL ou corps.
"""
from __future__ import annotations

import logging
import uuid
from typing import Optional

from fastapi import APIRouter, Depends, HTTPException, Query, status
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.deps import get_current_business_user, get_current_user
from app.db.session import get_db
from app.models.business import Business, BusinessUser
from app.models.user import User
from app.schemas.financial import PaymentCreate, PaymentResponse
from app.schemas.order import OrderCreate, OrderResponse
from app.services import orders as orders_svc
from app.services import financials as fin_svc

logger = logging.getLogger(__name__)

router = APIRouter(
    prefix="/orders",
    tags=["Commandes"],
)

_VALID_ORDER_STATUSES = frozenset({"PENDING", "PAID", "CANCELLED"})


# ---------------------------------------------------------------------------
# POST / — Créer une commande
# ---------------------------------------------------------------------------

@router.post(
    "/",
    response_model=OrderResponse,
    status_code=status.HTTP_201_CREATED,
    summary="Créer une commande",
    description=(
        "Crée une commande de service pour le commerce de l'utilisateur authentifié. "
        "Les prix des items sont snapshotés au moment de la création."
    ),
)
async def create_order(
    body: OrderCreate,
    business_and_membership: tuple[Business, BusinessUser] = Depends(get_current_business_user),
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
) -> OrderResponse:
    """
    Règles :
    - Chaque item doit appartenir au commerce et être actif.
    - Le business_id provient exclusivement du JWT (isolation tenant).
    """
    business, _ = business_and_membership

    try:
        order = await orders_svc.create_order(db, business, current_user, body)
    except ValueError as exc:
        detail = str(exc)
        # Erreurs de type "introuvable" → 404, erreurs métier → 422
        if "introuvable" in detail.lower():
            raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=detail)
        raise HTTPException(status_code=status.HTTP_422_UNPROCESSABLE_ENTITY, detail=detail)
    except IntegrityError as exc:
        await db.rollback()
        logger.exception("[ORDER] IntegrityError lors de la création : %s", exc)
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail="Conflit de données lors de la création de la commande.",
        )

    return OrderResponse.model_validate(order)


# ---------------------------------------------------------------------------
# GET / — Lister les commandes
# ---------------------------------------------------------------------------

@router.get(
    "/",
    response_model=list[OrderResponse],
    status_code=status.HTTP_200_OK,
    summary="Lister les commandes",
    description=(
        "Retourne les commandes du commerce (max 100, triées par date décroissante). "
        "Filtre optionnel : ?status=PENDING|PAID|CANCELLED."
    ),
)
async def list_orders(
    status_filter: Optional[str] = Query(
        default=None,
        alias="status",
        description="Filtre par statut : PENDING | PAID | CANCELLED.",
    ),
    business_and_membership: tuple[Business, BusinessUser] = Depends(get_current_business_user),
    db: AsyncSession = Depends(get_db),
) -> list[OrderResponse]:
    business, _ = business_and_membership

    if status_filter is not None:
        normalized = status_filter.strip().upper()
        if normalized not in _VALID_ORDER_STATUSES:
            raise HTTPException(
                status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
                detail=(
                    f"Statut invalide '{status_filter}'. "
                    f"Valeurs acceptées : {sorted(_VALID_ORDER_STATUSES)}."
                ),
            )
        status_filter = normalized

    orders = await orders_svc.list_orders(db, business.id, status=status_filter)
    return [OrderResponse.model_validate(order) for order in orders]


# ---------------------------------------------------------------------------
# GET /{order_id} — Détails d'une commande
# ---------------------------------------------------------------------------

@router.get(
    "/{order_id}",
    response_model=OrderResponse,
    status_code=status.HTTP_200_OK,
    summary="Détails d'une commande",
    description="Retourne la commande identifiée par order_id, si elle appartient au commerce.",
)
async def get_order(
    order_id: uuid.UUID,
    business_and_membership: tuple[Business, BusinessUser] = Depends(get_current_business_user),
    db: AsyncSession = Depends(get_db),
) -> OrderResponse:
    business, _ = business_and_membership
    order = await orders_svc.get_order(db, business.id, order_id)

    if order is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"Commande {order_id} introuvable pour ce commerce.",
        )

    return OrderResponse.model_validate(order)


# ---------------------------------------------------------------------------
# PATCH /{order_id}/cancel — Annuler une commande
# ---------------------------------------------------------------------------

@router.patch(
    "/{order_id}/cancel",
    response_model=OrderResponse,
    status_code=status.HTTP_200_OK,
    summary="Annuler une commande",
    description=(
        "Annule une commande en statut PENDING. "
        "L'OWNER peut annuler n'importe quelle commande ; "
        "les autres membres ne peuvent annuler que leurs propres commandes."
    ),
)
async def cancel_order(
    order_id: uuid.UUID,
    business_and_membership: tuple[Business, BusinessUser] = Depends(get_current_business_user),
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
) -> OrderResponse:
    business, membership = business_and_membership
    order = await orders_svc.get_order(db, business.id, order_id)

    if order is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"Commande {order_id} introuvable pour ce commerce.",
        )

    try:
        order = await orders_svc.cancel_order(db, order, current_user, membership.role)
    except ValueError as exc:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=str(exc))

    return OrderResponse.model_validate(order)


# ---------------------------------------------------------------------------
# POST /{order_id}/pay — Enregistrer un paiement
# ---------------------------------------------------------------------------

@router.post(
    "/{order_id}/pay",
    response_model=PaymentResponse,
    status_code=status.HTTP_201_CREATED,
    summary="Enregistrer un paiement",
    description=(
        "Enregistre un paiement pour une commande PENDING et la passe en PAID. "
        "Méthodes acceptées : CASH, MOBILE_MONEY, CHEQUE, CREDIT."
    ),
)
async def record_payment(
    order_id: uuid.UUID,
    body: PaymentCreate,
    business_and_membership: tuple[Business, BusinessUser] = Depends(get_current_business_user),
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
) -> PaymentResponse:
    business, _ = business_and_membership
    order = await orders_svc.get_order(db, business.id, order_id)

    if order is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"Commande {order_id} introuvable pour ce commerce.",
        )

    try:
        payment = await fin_svc.record_payment(db, order, current_user, body)
    except ValueError as exc:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=str(exc))
    except IntegrityError as exc:
        await db.rollback()
        logger.exception("[PAYMENT] IntegrityError : %s", exc)
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail="Conflit de données lors de l'enregistrement du paiement.",
        )

    return PaymentResponse.model_validate(payment)
