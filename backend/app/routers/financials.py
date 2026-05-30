"""
Router FastAPI — /api/v1/financials/*

Endpoints :
    POST   /expenses/                   → Enregistre une dépense opérationnelle
    GET    /expenses/                   → Liste les dépenses du commerce
    POST   /credits/                    → Enregistre une créance client
    GET    /credits/                    → Liste les créances (?status=OUTSTANDING|REPAID)
    PATCH  /credits/{credit_id}/repay   → Marque une créance comme remboursée

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
from app.schemas.financial import (
    CreditCreate,
    CreditResponse,
    ExpenseCreate,
    ExpenseResponse,
)
from app.services import financials as fin_svc

logger = logging.getLogger(__name__)

router = APIRouter(
    prefix="/financials",
    tags=["Finances"],
)

_VALID_CREDIT_STATUSES = frozenset({"OUTSTANDING", "REPAID"})


# ---------------------------------------------------------------------------
# POST /expenses/ — Enregistrer une dépense
# ---------------------------------------------------------------------------

@router.post(
    "/expenses/",
    response_model=ExpenseResponse,
    status_code=status.HTTP_201_CREATED,
    summary="Enregistrer une dépense",
    description="Enregistre une dépense opérationnelle pour le commerce de l'utilisateur.",
)
async def record_expense(
    body: ExpenseCreate,
    business_and_membership: tuple[Business, BusinessUser] = Depends(get_current_business_user),
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
) -> ExpenseResponse:
    business, _ = business_and_membership

    try:
        expense = await fin_svc.record_expense(db, business.id, current_user, body)
    except ValueError as exc:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=str(exc))
    except IntegrityError as exc:
        await db.rollback()
        logger.exception("[EXPENSE] IntegrityError : %s", exc)
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail="Conflit de données lors de l'enregistrement de la dépense.",
        )

    return ExpenseResponse.model_validate(expense)


# ---------------------------------------------------------------------------
# GET /expenses/ — Lister les dépenses
# ---------------------------------------------------------------------------

@router.get(
    "/expenses/",
    response_model=list[ExpenseResponse],
    status_code=status.HTTP_200_OK,
    summary="Lister les dépenses",
    description=(
        "Retourne les dépenses opérationnelles du commerce "
        "(max 100, triées par date décroissante)."
    ),
)
async def list_expenses(
    business_and_membership: tuple[Business, BusinessUser] = Depends(get_current_business_user),
    db: AsyncSession = Depends(get_db),
) -> list[ExpenseResponse]:
    business, _ = business_and_membership
    expenses = await fin_svc.list_expenses(db, business.id)
    return [ExpenseResponse.model_validate(e) for e in expenses]


# ---------------------------------------------------------------------------
# POST /credits/ — Enregistrer une créance
# ---------------------------------------------------------------------------

@router.post(
    "/credits/",
    response_model=CreditResponse,
    status_code=status.HTTP_201_CREATED,
    summary="Enregistrer une créance",
    description=(
        "Crée une créance client en statut OUTSTANDING pour le commerce. "
        "Utilisé lorsqu'un client repart sans payer (paiement différé)."
    ),
)
async def record_credit(
    body: CreditCreate,
    business_and_membership: tuple[Business, BusinessUser] = Depends(get_current_business_user),
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
) -> CreditResponse:
    business, _ = business_and_membership

    try:
        credit = await fin_svc.record_credit(db, business.id, current_user, body)
    except ValueError as exc:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=str(exc))
    except IntegrityError as exc:
        await db.rollback()
        logger.exception("[CREDIT] IntegrityError : %s", exc)
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail="Conflit de données lors de l'enregistrement de la créance.",
        )

    return CreditResponse.model_validate(credit)


# ---------------------------------------------------------------------------
# GET /credits/ — Lister les créances
# ---------------------------------------------------------------------------

@router.get(
    "/credits/",
    response_model=list[CreditResponse],
    status_code=status.HTTP_200_OK,
    summary="Lister les créances",
    description=(
        "Retourne les créances du commerce (max 100, triées par date décroissante). "
        "Filtre optionnel : ?status=OUTSTANDING|REPAID."
    ),
)
async def list_credits(
    status_filter: Optional[str] = Query(
        default=None,
        alias="status",
        description="Filtre par statut : OUTSTANDING | REPAID.",
    ),
    business_and_membership: tuple[Business, BusinessUser] = Depends(get_current_business_user),
    db: AsyncSession = Depends(get_db),
) -> list[CreditResponse]:
    business, _ = business_and_membership

    if status_filter is not None:
        normalized = status_filter.strip().upper()
        if normalized not in _VALID_CREDIT_STATUSES:
            raise HTTPException(
                status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
                detail=(
                    f"Statut invalide '{status_filter}'. "
                    f"Valeurs acceptées : {sorted(_VALID_CREDIT_STATUSES)}."
                ),
            )
        status_filter = normalized

    credits = await fin_svc.list_credits(db, business.id, status=status_filter)
    return [CreditResponse.model_validate(c) for c in credits]


# ---------------------------------------------------------------------------
# PATCH /credits/{credit_id}/repay — Rembourser une créance
# ---------------------------------------------------------------------------

@router.patch(
    "/credits/{credit_id}/repay",
    response_model=CreditResponse,
    status_code=status.HTTP_200_OK,
    summary="Rembourser une créance",
    description=(
        "Marque une créance comme remboursée (OUTSTANDING → REPAID). "
        "Lève 404 si la créance n'existe pas, 400 si déjà remboursée."
    ),
)
async def repay_credit(
    credit_id: uuid.UUID,
    business_and_membership: tuple[Business, BusinessUser] = Depends(get_current_business_user),
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
) -> CreditResponse:
    business, _ = business_and_membership

    try:
        credit = await fin_svc.repay_credit(db, business.id, credit_id, current_user)
    except ValueError as exc:
        detail = str(exc)
        # "introuvable" → 404, déjà remboursée → 400
        if "introuvable" in detail.lower():
            raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=detail)
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=detail)
    except IntegrityError as exc:
        await db.rollback()
        logger.exception("[CREDIT] IntegrityError lors du remboursement : %s", exc)
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail="Conflit de données lors du remboursement de la créance.",
        )

    return CreditResponse.model_validate(credit)
