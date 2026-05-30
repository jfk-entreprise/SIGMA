"""
Service métier — Finance SIGMA : paiements, dépenses, créances.

Responsabilités :
- Enregistrement d'un paiement et passage de la commande en PAID
- Enregistrement et listing des dépenses opérationnelles
- Création, listing et remboursement des créances clients

Toutes les fonctions lèvent ValueError (pas HTTPException) — la conversion
est gérée dans les routers.
"""
from __future__ import annotations

import logging
import uuid
from datetime import datetime, timezone
from typing import Sequence

from app.services import reports as reports_svc

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.financial import Credit, CreditStatus, Expense, Payment, PaymentMethod
from app.models.service_order import OrderStatus, ServiceOrder
from app.models.user import User
from app.schemas.financial import CreditCreate, ExpenseCreate, PaymentCreate

logger = logging.getLogger(__name__)


# ---------------------------------------------------------------------------
# Enregistrement d'un paiement
# ---------------------------------------------------------------------------

async def record_payment(
    db: AsyncSession,
    order: ServiceOrder,
    recorder: User,
    data: PaymentCreate,
) -> Payment:
    """
    Enregistre un paiement pour une commande en attente et la passe en PAID.

    Règle : la commande doit être en statut PENDING. Un paiement ne peut être
    effectué que sur une commande ouverte (PAID → doublon, CANCELLED → invalide).

    Lève ValueError si la commande n'est pas en statut PENDING.
    """
    # Verrou pessimiste : FOR UPDATE sur PostgreSQL, no-op sur SQLite (dialecte SQLite
    # surcharge for_update_clause() → chaîne vide, donc aucune erreur en test).
    await db.refresh(order, with_for_update=True)

    if order.status != OrderStatus.PENDING.value:
        raise ValueError(
            f"Impossible d'enregistrer un paiement : la commande est en statut "
            f"'{order.status}'. Seules les commandes PENDING peuvent être payées."
        )

    # Pour les paiements hors-crédit, le montant doit couvrir le total de la commande.
    if data.payment_method != PaymentMethod.CREDIT.value and data.amount < order.total:
        raise ValueError(
            f"Le montant encaissé ({data.amount} FCFA) est insuffisant. "
            f"Le total de la commande est de {order.total} FCFA."
        )

    payment = Payment(
        id=uuid.uuid4(),
        order_id=order.id,
        payment_method=data.payment_method,
        amount=data.amount,
        reference=data.reference,
        paid_by=recorder.id,
    )

    order.status = OrderStatus.PAID.value
    order.completed_at = datetime.now(timezone.utc)

    db.add(payment)
    await db.flush()
    await db.refresh(payment)

    logger.info(
        "[PAYMENT] Paiement enregistré | id=%s | order=%s | method=%s | amount=%d",
        payment.id, order.id, data.payment_method, data.amount,
    )
    await reports_svc.generate_or_update_daily_report(
        db, order.business_id, datetime.now(timezone.utc).date()
    )
    return payment


# ---------------------------------------------------------------------------
# Dépenses opérationnelles
# ---------------------------------------------------------------------------

async def record_expense(
    db: AsyncSession,
    business_id: uuid.UUID,
    creator: User,
    data: ExpenseCreate,
) -> Expense:
    """
    Enregistre une dépense opérationnelle pour le commerce donné.
    """
    expense = Expense(
        id=uuid.uuid4(),
        business_id=business_id,
        reason=data.reason,
        amount=data.amount,
        created_by=creator.id,
    )

    db.add(expense)
    await db.flush()
    await db.refresh(expense)

    logger.info(
        "[EXPENSE] Dépense enregistrée | id=%s | business=%s | amount=%d",
        expense.id, business_id, data.amount,
    )
    await reports_svc.generate_or_update_daily_report(
        db, business_id, datetime.now(timezone.utc).date()
    )
    return expense


async def list_expenses(
    db: AsyncSession,
    business_id: uuid.UUID,
) -> Sequence[Expense]:
    """
    Retourne les dépenses d'un commerce, triées par date décroissante (max 100).
    """
    result = await db.execute(
        select(Expense)
        .where(Expense.business_id == business_id)
        .order_by(Expense.created_at.desc())
        .limit(100)
    )
    return result.scalars().all()


# ---------------------------------------------------------------------------
# Créances clients
# ---------------------------------------------------------------------------

async def record_credit(
    db: AsyncSession,
    business_id: uuid.UUID,
    creator: User,
    data: CreditCreate,
) -> Credit:
    """
    Crée une créance client en statut OUTSTANDING pour le commerce donné.
    """
    credit = Credit(
        id=uuid.uuid4(),
        business_id=business_id,
        customer_name=data.customer_name,
        customer_phone=data.customer_phone,
        amount=data.amount,
        reason=data.reason,
        status=CreditStatus.OUTSTANDING.value,
        created_by=creator.id,
    )

    db.add(credit)
    await db.flush()
    await db.refresh(credit)

    logger.info(
        "[CREDIT] Créance enregistrée | id=%s | business=%s | customer=%s | amount=%d",
        credit.id, business_id, data.customer_name, data.amount,
    )
    await reports_svc.generate_or_update_daily_report(
        db, business_id, datetime.now(timezone.utc).date()
    )
    return credit


async def list_credits(
    db: AsyncSession,
    business_id: uuid.UUID,
    status: str | None = None,
) -> Sequence[Credit]:
    """
    Retourne les créances d'un commerce, triées par date décroissante (max 100).
    Le filtre status est optionnel (OUTSTANDING | REPAID).
    """
    stmt = (
        select(Credit)
        .where(Credit.business_id == business_id)
        .order_by(Credit.created_at.desc())
        .limit(100)
    )
    if status is not None:
        stmt = stmt.where(Credit.status == status)

    result = await db.execute(stmt)
    return result.scalars().all()


async def repay_credit(
    db: AsyncSession,
    business_id: uuid.UUID,
    credit_id: uuid.UUID,
    repayer: User,
) -> Credit:
    """
    Marque une créance comme remboursée (OUTSTANDING → REPAID).

    Isolation tenant : vérifie que la créance appartient bien au commerce.
    Lève ValueError si :
    - La créance n'existe pas ou appartient à un autre commerce (404-equivalent)
    - La créance est déjà remboursée (400-equivalent)
    """
    result = await db.execute(
        select(Credit)
        .where(
            Credit.id == credit_id,
            Credit.business_id == business_id,
        )
        .with_for_update()
    )
    credit = result.scalar_one_or_none()

    if credit is None:
        raise ValueError(
            f"Créance {credit_id} introuvable pour ce commerce."
        )

    if credit.status == CreditStatus.REPAID.value:
        raise ValueError(
            f"La créance de '{credit.customer_name}' est déjà marquée comme remboursée."
        )

    credit.status = CreditStatus.REPAID.value
    credit.repaid_at = datetime.now(timezone.utc)
    credit.repaid_by = repayer.id

    await db.flush()
    await db.refresh(credit)

    logger.info(
        "[CREDIT] Créance remboursée | id=%s | business=%s | by=%s",
        credit.id, business_id, repayer.id,
    )
    return credit
