"""
Service métier — Rapports statistiques SIGMA (Étape 2.2).

Responsabilités :
- generate_or_update_daily_report : upsert du rapport journalier
- get_dashboard_kpis               : KPIs du jour en temps réel
- get_period_reports               : synthèse hebdomadaire / mensuelle

Formule CA net : gross_income - (expenses + credits)

Filtrage temporel : bornes UTC naïves compatibles SQLite (server_default=now())
et PostgreSQL (timestamp with timezone interprété en UTC).
"""
from __future__ import annotations

import asyncio
import uuid
from contextlib import asynccontextmanager
from datetime import date, datetime, timedelta, timezone
from typing import Sequence

from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.redis_client import get_redis_pool
from app.models.financial import Credit, Expense, Payment
from app.models.report import DailyReport
from app.models.service_order import OrderStatus, ServiceOrder


# ---------------------------------------------------------------------------
# Utilitaire interne : bornes UTC naïves d'une journée
# ---------------------------------------------------------------------------

@asynccontextmanager
async def _daily_report_lock(lock_key: str):
    """
    Verrou distribué via SET NX EX — compatible fakeredis (pas de Lua/EVALSHA requis).

    Sondage toutes les 50 ms pendant au maximum 5 secondes.
    L'expiration Redis (10 s) garantit qu'un crash du process libère le verrou.
    """
    redis = await get_redis_pool()
    acquired = False
    try:
        for _ in range(100):
            acquired = bool(await redis.set(lock_key, "1", nx=True, ex=10))
            if acquired:
                break
            await asyncio.sleep(0.05)
        yield
    finally:
        if acquired:
            await redis.delete(lock_key)


def _day_bounds(report_date: date) -> tuple[datetime, datetime]:
    """
    Retourne (début, fin) en datetime UTC naïf.

    Le format naïf est compatible avec les valeurs stockées par
    server_default=func.now() dans SQLite (pas de suffixe timezone).
    En PostgreSQL, les comparaisons avec timestamp with timezone sont correctes
    lorsque la session est configurée en UTC.
    """
    day_start = datetime(report_date.year, report_date.month, report_date.day)
    day_end = day_start + timedelta(days=1)
    return day_start, day_end


# ---------------------------------------------------------------------------
# Génération / mise à jour d'un rapport journalier (Upsert)
# ---------------------------------------------------------------------------

async def generate_or_update_daily_report(
    db: AsyncSession,
    business_id: uuid.UUID,
    report_date: date,
) -> DailyReport:
    """
    Calcule les métriques du jour et upsert la ligne DailyReport correspondante.

    Appelé automatiquement après chaque paiement, dépense ou créance enregistrés
    (déclencheur logique dans services/financials.py).

    Verrou distribué Redis : sérialise les écritures concurrentes sur la même
    ligne (business_id, date) pour éviter la race condition INSERT simultané
    qui provoquerait une IntegrityError non gérée.

    Upsert via SELECT-then-INSERT/UPDATE pour la portabilité SQLite/PostgreSQL.
    """
    lock_key = f"sigma:lock:daily_report:{business_id}:{report_date.isoformat()}"

    async with _daily_report_lock(lock_key):
        day_start, day_end = _day_bounds(report_date)

        # 1. Total commandes non annulées créées ce jour
        total_orders = (await db.execute(
            select(func.count(ServiceOrder.id)).where(
                ServiceOrder.business_id == business_id,
                ServiceOrder.created_at >= day_start,
                ServiceOrder.created_at < day_end,
                ServiceOrder.status != OrderStatus.CANCELLED.value,
            )
        )).scalar_one() or 0

        # 2. CA brut : somme des paiements encaissés ce jour (JOIN service_orders pour le tenant)
        gross_income = (await db.execute(
            select(func.coalesce(func.sum(Payment.amount), 0))
            .join(ServiceOrder, Payment.order_id == ServiceOrder.id)
            .where(
                ServiceOrder.business_id == business_id,
                Payment.paid_at >= day_start,
                Payment.paid_at < day_end,
            )
        )).scalar_one() or 0

        # 3. Dépenses opérationnelles du jour
        expenses = (await db.execute(
            select(func.coalesce(func.sum(Expense.amount), 0)).where(
                Expense.business_id == business_id,
                Expense.created_at >= day_start,
                Expense.created_at < day_end,
            )
        )).scalar_one() or 0

        # 4. Créances ouvertes créées ce jour (peu importe leur statut actuel)
        credits = (await db.execute(
            select(func.coalesce(func.sum(Credit.amount), 0)).where(
                Credit.business_id == business_id,
                Credit.created_at >= day_start,
                Credit.created_at < day_end,
            )
        )).scalar_one() or 0

        # 5. CA net
        net_income = gross_income - (expenses + credits)

        # 6. Upsert : charger le rapport existant ou en créer un nouveau
        existing = await db.execute(
            select(DailyReport).where(
                DailyReport.business_id == business_id,
                DailyReport.date == report_date,
            )
        )
        report = existing.scalar_one_or_none()
        now = datetime.now(timezone.utc)

        if report is None:
            report = DailyReport(
                id=uuid.uuid4(),
                business_id=business_id,
                date=report_date,
                total_orders=total_orders,
                gross_income=gross_income,
                expenses=expenses,
                credits=credits,
                net_income=net_income,
                generated_at=now,
            )
            db.add(report)
        else:
            report.total_orders = total_orders
            report.gross_income = gross_income
            report.expenses = expenses
            report.credits = credits
            report.net_income = net_income
            report.generated_at = now

        await db.flush()
        return report


# ---------------------------------------------------------------------------
# KPIs temps réel (dashboard OWNER)
# ---------------------------------------------------------------------------

async def get_dashboard_kpis(
    db: AsyncSession,
    business_id: uuid.UUID,
    report_date: date,
) -> dict:
    """
    Calcule les KPIs du jour directement depuis les tables sources (temps réel).
    Retourne un dict compatible avec DashboardResponse.
    """
    day_start, day_end = _day_bounds(report_date)

    # Toutes les commandes PENDING du commerce (quelle que soit leur date de création)
    pending_orders = (await db.execute(
        select(func.count(ServiceOrder.id)).where(
            ServiceOrder.business_id == business_id,
            ServiceOrder.status == OrderStatus.PENDING.value,
        )
    )).scalar_one() or 0

    # Commandes PAID complétées aujourd'hui (completed_at)
    paid_orders = (await db.execute(
        select(func.count(ServiceOrder.id)).where(
            ServiceOrder.business_id == business_id,
            ServiceOrder.completed_at >= day_start,
            ServiceOrder.completed_at < day_end,
            ServiceOrder.status == OrderStatus.PAID.value,
        )
    )).scalar_one() or 0

    # CA brut du jour
    gross_income = (await db.execute(
        select(func.coalesce(func.sum(Payment.amount), 0))
        .join(ServiceOrder, Payment.order_id == ServiceOrder.id)
        .where(
            ServiceOrder.business_id == business_id,
            Payment.paid_at >= day_start,
            Payment.paid_at < day_end,
        )
    )).scalar_one() or 0

    # Dépenses du jour
    total_expenses = (await db.execute(
        select(func.coalesce(func.sum(Expense.amount), 0)).where(
            Expense.business_id == business_id,
            Expense.created_at >= day_start,
            Expense.created_at < day_end,
        )
    )).scalar_one() or 0

    # Créances du jour
    total_credits = (await db.execute(
        select(func.coalesce(func.sum(Credit.amount), 0)).where(
            Credit.business_id == business_id,
            Credit.created_at >= day_start,
            Credit.created_at < day_end,
        )
    )).scalar_one() or 0

    return {
        "date": report_date,
        "net_income": gross_income - (total_expenses + total_credits),
        "gross_income": gross_income,
        "total_expenses": total_expenses,
        "total_credits": total_credits,
        "pending_orders": pending_orders,
        "paid_orders": paid_orders,
    }


# ---------------------------------------------------------------------------
# Listing des rapports journaliers
# ---------------------------------------------------------------------------

async def list_daily_reports(
    db: AsyncSession,
    business_id: uuid.UUID,
    limit: int = 30,
) -> Sequence[DailyReport]:
    """Retourne les rapports journaliers du commerce (max `limit`, ordre décroissant)."""
    result = await db.execute(
        select(DailyReport)
        .where(DailyReport.business_id == business_id)
        .order_by(DailyReport.date.desc())
        .limit(limit)
    )
    return result.scalars().all()


# ---------------------------------------------------------------------------
# Synthèse sur une période (weekly / monthly)
# ---------------------------------------------------------------------------

async def get_period_summary(
    db: AsyncSession,
    business_id: uuid.UUID,
    period_start: date,
    period_end: date,
) -> dict:
    """
    Agrège les rapports journaliers sur la période [period_start, period_end].
    Retourne un dict compatible avec PeriodSummaryResponse.
    """
    result = await db.execute(
        select(DailyReport)
        .where(
            DailyReport.business_id == business_id,
            DailyReport.date >= period_start,
            DailyReport.date <= period_end,
        )
        .order_by(DailyReport.date)
    )
    reports = list(result.scalars().all())

    return {
        "period_start": period_start,
        "period_end": period_end,
        "total_orders": sum(r.total_orders for r in reports),
        "gross_income": sum(r.gross_income for r in reports),
        "expenses": sum(r.expenses for r in reports),
        "credits": sum(r.credits for r in reports),
        "net_income": sum(r.net_income for r in reports),
        "days": reports,
    }
