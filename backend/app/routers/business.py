"""
Router FastAPI — /api/v1/businesses/*

Endpoints :
    POST   /                    → Crée un commerce (Owner)
    GET    /my                  → Détails du commerce de l'utilisateur connecté
    GET    /items               → Liste des prestations actives du commerce
    PATCH  /items/{item_id}     → Modifie un item (Owner uniquement)
    POST   /managers            → Ajoute un gérant (Owner uniquement)
"""
from __future__ import annotations

import logging
import uuid

from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy import select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.deps import (
    get_current_business_user,
    get_current_user,
    require_owner,
)
from app.db.session import get_db
from app.models.business import Business, BusinessUser
from app.models.user import User
from app.schemas.business import (
    BusinessCreate,
    BusinessItemResponse,
    BusinessItemUpdate,
    BusinessMemberResponse,
    BusinessResponse,
    UserCreateManager,
)
from app.services import business as biz_svc

logger = logging.getLogger(__name__)

router = APIRouter(
    prefix="/businesses",
    tags=["Commerces"],
)


# ---------------------------------------------------------------------------
# POST / — Créer un commerce
# ---------------------------------------------------------------------------

@router.post(
    "/",
    response_model=BusinessResponse,
    status_code=status.HTTP_201_CREATED,
    summary="Créer un commerce",
    description=(
        "Crée un nouveau commerce pour l'utilisateur authentifié qui en devient l'Owner. "
        "Initialise automatiquement les prestations depuis le catalogue central."
    ),
)
async def create_business(
    body: BusinessCreate,
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
) -> BusinessResponse:
    """
    Règles :
    - Un utilisateur ne peut être Owner que d'un seul commerce actif.
    - Le catalogue d'items est copié automatiquement selon le type de commerce.
    """
    # Vérifier qu'il n'y a pas déjà un commerce actif pour cet owner
    existing = await db.execute(
        select(Business).where(
            Business.owner_id == current_user.id,
            Business.is_active.is_(True),
        )
    )
    if existing.scalar_one_or_none():
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail="Vous possédez déjà un commerce actif. Un seul commerce par propriétaire.",
        )

    try:
        business = await biz_svc.create_business(db, current_user, body)
    except ValueError as e:
        raise HTTPException(status_code=status.HTTP_422_UNPROCESSABLE_ENTITY, detail=str(e))

    return BusinessResponse.model_validate(business)


# ---------------------------------------------------------------------------
# GET /my — Commerce de l'utilisateur connecté
# ---------------------------------------------------------------------------

@router.get(
    "/my",
    response_model=BusinessResponse,
    status_code=status.HTTP_200_OK,
    summary="Mon commerce",
    description="Retourne les détails du commerce auquel l'utilisateur est rattaché.",
)
async def get_my_business(
    business_and_membership: tuple[Business, BusinessUser] = Depends(get_current_business_user),
) -> BusinessResponse:
    business, _ = business_and_membership
    return BusinessResponse.model_validate(business)


# ---------------------------------------------------------------------------
# GET /items — Liste des prestations du commerce
# ---------------------------------------------------------------------------

@router.get(
    "/items",
    response_model=list[BusinessItemResponse],
    status_code=status.HTTP_200_OK,
    summary="Prestations du commerce",
    description="Retourne les prestations actives du commerce, triées par ordre d'affichage.",
)
async def list_business_items(
    business_and_membership: tuple[Business, BusinessUser] = Depends(get_current_business_user),
    db: AsyncSession = Depends(get_db),
) -> list[BusinessItemResponse]:
    business, _ = business_and_membership
    items = await biz_svc.get_business_items(db, business.id, active_only=True)
    return [BusinessItemResponse.model_validate(item) for item in items]


# ---------------------------------------------------------------------------
# PATCH /items/{item_id} — Modifier une prestation (Owner uniquement)
# ---------------------------------------------------------------------------

@router.patch(
    "/items/{item_id}",
    response_model=BusinessItemResponse,
    status_code=status.HTTP_200_OK,
    summary="Modifier une prestation",
    description=(
        "Permet à l'Owner de modifier le prix personnalisé, le nom "
        "ou l'état actif/inactif d'une prestation."
    ),
)
async def update_business_item(
    item_id: uuid.UUID,
    body: BusinessItemUpdate,
    owner_data: tuple[Business, BusinessUser] = Depends(require_owner),
    db: AsyncSession = Depends(get_db),
) -> BusinessItemResponse:
    business, _ = owner_data

    if body.custom_price is None and body.is_active is None and body.custom_name is None:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            detail="Au moins un champ (custom_price, is_active, custom_name) doit être fourni.",
        )

    try:
        item = await biz_svc.update_business_item(
            db,
            business_id=business.id,
            item_id=item_id,
            custom_price=body.custom_price,
            is_active=body.is_active,
            custom_name=body.custom_name,
        )
    except ValueError as e:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=str(e))

    return BusinessItemResponse.model_validate(item)


# ---------------------------------------------------------------------------
# POST /managers — Ajouter un gérant (Owner uniquement)
# ---------------------------------------------------------------------------

@router.post(
    "/managers",
    response_model=BusinessMemberResponse,
    status_code=status.HTTP_201_CREATED,
    summary="Ajouter un gérant",
    description=(
        "Permet au Propriétaire d'ajouter un Gérant (MANAGER) à son commerce. "
        "Si le numéro de téléphone correspond à un compte existant, "
        "le compte est réutilisé ; sinon un nouveau compte est créé."
    ),
)
async def add_manager(
    body: UserCreateManager,
    owner_data: tuple[Business, BusinessUser] = Depends(require_owner),
    db: AsyncSession = Depends(get_db),
) -> BusinessMemberResponse:
    business, _ = owner_data

    try:
        membership = await biz_svc.add_staff_member(db, business, body)
    except IntegrityError as exc:
        await db.rollback()
        # Distinguer la contrainte violée pour fournir un message précis.
        # SQLite : "UNIQUE constraint failed: <table>.<col>, ..."
        # PostgreSQL : "duplicate key value violates unique constraint "<name>""
        orig = str(exc.orig).lower() if exc.orig else str(exc).lower()
        if "business_users" in orig or "uq_business_user" in orig:
            detail = f"Le numéro {body.phone_number} est déjà membre de ce commerce."
        elif "phone" in orig:
            detail = (
                f"Le numéro {body.phone_number} est déjà associé à un autre compte "
                "utilisateur dans le système."
            )
        else:
            detail = "Conflit de données. Veuillez vérifier les informations saisies."
        raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail=detail)

    return BusinessMemberResponse(
        id=membership.id,
        user_id=membership.user_id,
        full_name=membership.user.full_name,
        phone_number=membership.user.phone_number,
        role=membership.role,
        created_at=membership.created_at,
    )
