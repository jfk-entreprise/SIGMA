"""Schémas Pydantic — Rapports statistiques SIGMA (Étape 2.2)."""
import uuid
from datetime import date, datetime

from pydantic import BaseModel, ConfigDict, Field


class DailyReportResponse(BaseModel):
    """Rapport journalier consolidé d'un commerce."""

    model_config = ConfigDict(from_attributes=True)

    id: uuid.UUID
    business_id: uuid.UUID
    date: date
    total_orders: int = Field(description="Commandes du jour hors CANCELLED.")
    gross_income: int = Field(description="Somme des paiements encaissés (FCFA).")
    expenses: int = Field(description="Somme des dépenses opérationnelles (FCFA).")
    credits: int = Field(description="Somme des créances ouvertes (FCFA).")
    net_income: int = Field(description="CA net = gross_income - (expenses + credits).")
    generated_at: datetime


class DashboardResponse(BaseModel):
    """KPIs du jour calculés en temps réel (accès OWNER uniquement)."""

    date: date
    net_income: int
    gross_income: int
    total_expenses: int
    total_credits: int
    pending_orders: int = Field(description="Commandes créées aujourd'hui, encore PENDING.")
    paid_orders: int = Field(description="Commandes complétées aujourd'hui (PAID).")


class PeriodSummaryResponse(BaseModel):
    """Synthèse agrégée sur une période (hebdomadaire ou mensuelle)."""

    period_start: date
    period_end: date
    total_orders: int
    gross_income: int
    expenses: int
    credits: int
    net_income: int
    days: list[DailyReportResponse] = Field(
        description="Détail journalier de la période."
    )
