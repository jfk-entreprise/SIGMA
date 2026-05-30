"""
Router FastAPI — /api/v1/reports/*

Endpoints :
    GET /daily    → Rapports journaliers consolidés (tous membres)
    GET /dashboard → KPIs du jour en temps réel (OWNER uniquement)
    GET /weekly   → Synthèse des 7 derniers jours (abonnés PREMIUM+)
    GET /monthly  → Synthèse du mois courant (abonnés PREMIUM+)

Isolation multi-tenant : business_id toujours extrait du JWT.
Barrière d'abonnement : /weekly et /monthly requièrent PREMIUM ou PREMIUM_PRO.
"""
from __future__ import annotations

import logging
from datetime import datetime, timedelta, timezone

from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.deps import get_current_business_user, require_owner
from app.db.session import get_db
from app.models.business import Business, BusinessUser, SubscriptionPlan
from app.schemas.report import DailyReportResponse, DashboardResponse, PeriodSummaryResponse
from app.services import reports as reports_svc

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/reports", tags=["Rapports"])

_PREMIUM_PLANS = frozenset({SubscriptionPlan.PREMIUM.value, SubscriptionPlan.PREMIUM_PRO.value})


# ---------------------------------------------------------------------------
# Dépendance : barrière d'abonnement PREMIUM
# ---------------------------------------------------------------------------

async def _require_premium(
    business_and_membership: tuple[Business, BusinessUser] = Depends(
        get_current_business_user
    ),
) -> tuple[Business, BusinessUser]:
    """
    Vérifie que le commerce est abonné à un plan PREMIUM ou PREMIUM_PRO.
    Lève 403 si le plan est FREE.
    """
    business, membership = business_and_membership
    if business.subscription_plan not in _PREMIUM_PLANS:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail=(
                "L'accès aux rapports consolidés (hebdomadaires / mensuels) "
                "requiert un abonnement PREMIUM. "
                f"Plan actuel du commerce : {business.subscription_plan}."
            ),
        )
    return business, membership


# ---------------------------------------------------------------------------
# GET /daily — Rapports journaliers (tous membres)
# ---------------------------------------------------------------------------

@router.get(
    "/daily",
    response_model=list[DailyReportResponse],
    status_code=status.HTTP_200_OK,
    summary="Rapports journaliers",
    description=(
        "Retourne les 30 derniers rapports journaliers consolidés du commerce "
        "(triés par date décroissante)."
    ),
)
async def list_daily_reports(
    business_and_membership: tuple[Business, BusinessUser] = Depends(get_current_business_user),
    db: AsyncSession = Depends(get_db),
) -> list[DailyReportResponse]:
    business, _ = business_and_membership
    reports = await reports_svc.list_daily_reports(db, business.id)
    return [DailyReportResponse.model_validate(r) for r in reports]


# ---------------------------------------------------------------------------
# GET /dashboard — KPIs temps réel (OWNER uniquement)
# ---------------------------------------------------------------------------

@router.get(
    "/dashboard",
    response_model=DashboardResponse,
    status_code=status.HTTP_200_OK,
    summary="Tableau de bord (temps réel)",
    description=(
        "Retourne les KPIs du jour calculés en temps réel : CA net, dépenses, "
        "créances, commandes PENDING et PAID. Réservé au Propriétaire du commerce."
    ),
)
async def get_dashboard(
    business_and_membership: tuple[Business, BusinessUser] = Depends(require_owner),
    db: AsyncSession = Depends(get_db),
) -> DashboardResponse:
    business, _ = business_and_membership
    today = datetime.now(timezone.utc).date()
    kpis = await reports_svc.get_dashboard_kpis(db, business.id, today)
    return DashboardResponse(**kpis)


# ---------------------------------------------------------------------------
# GET /weekly — Synthèse hebdomadaire (PREMIUM+)
# ---------------------------------------------------------------------------

@router.get(
    "/weekly",
    response_model=PeriodSummaryResponse,
    status_code=status.HTTP_200_OK,
    summary="Rapport hebdomadaire",
    description=(
        "Synthèse des 7 derniers jours (aujourd'hui inclus). "
        "Requiert un abonnement PREMIUM ou PREMIUM_PRO."
    ),
)
async def get_weekly_report(
    business_and_membership: tuple[Business, BusinessUser] = Depends(_require_premium),
    db: AsyncSession = Depends(get_db),
) -> PeriodSummaryResponse:
    business, _ = business_and_membership
    today = datetime.now(timezone.utc).date()
    period_start = today - timedelta(days=6)
    summary = await reports_svc.get_period_summary(db, business.id, period_start, today)
    return PeriodSummaryResponse(**summary)


# ---------------------------------------------------------------------------
# GET /monthly — Synthèse mensuelle (PREMIUM+)
# ---------------------------------------------------------------------------

@router.get(
    "/monthly",
    response_model=PeriodSummaryResponse,
    status_code=status.HTTP_200_OK,
    summary="Rapport mensuel",
    description=(
        "Synthèse du mois calendaire courant (du 1er à aujourd'hui). "
        "Requiert un abonnement PREMIUM ou PREMIUM_PRO."
    ),
)
async def get_monthly_report(
    business_and_membership: tuple[Business, BusinessUser] = Depends(_require_premium),
    db: AsyncSession = Depends(get_db),
) -> PeriodSummaryResponse:
    business, _ = business_and_membership
    today = datetime.now(timezone.utc).date()
    period_start = today.replace(day=1)
    summary = await reports_svc.get_period_summary(db, business.id, period_start, today)
    return PeriodSummaryResponse(**summary)
