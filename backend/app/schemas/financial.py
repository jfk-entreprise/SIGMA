"""
Schémas Pydantic pour le module Finances SIGMA.

Couvre :
- Création / réponse d'un paiement (Payment)
- Création / réponse d'une dépense opérationnelle (Expense)
- Création / réponse d'une créance client (Credit)
"""
import uuid
from datetime import datetime
from typing import Optional

from pydantic import BaseModel, ConfigDict, Field, field_validator


# ---------------------------------------------------------------------------
# Constantes partagées
# ---------------------------------------------------------------------------

_ALLOWED_PAYMENT_METHODS = {"CASH", "MOBILE_MONEY", "CHEQUE", "CREDIT"}


# ---------------------------------------------------------------------------
# Paiement — Création
# ---------------------------------------------------------------------------

class PaymentCreate(BaseModel):
    """
    Corps de la requête POST /orders/{order_id}/payments.

    Le champ `reference` est obligatoire pour MOBILE_MONEY et CHEQUE ;
    cette contrainte métier est validée au niveau du service.
    """

    payment_method: str = Field(
        ...,
        examples=["CASH", "MOBILE_MONEY", "CHEQUE", "CREDIT"],
        description=(
            f"Méthode de paiement. Valeurs acceptées : "
            f"{', '.join(sorted(_ALLOWED_PAYMENT_METHODS))}."
        ),
    )
    amount: int = Field(
        ...,
        gt=0,
        description="Montant encaissé en FCFA (strictement positif).",
    )
    reference: Optional[str] = Field(
        default=None,
        max_length=100,
        examples=["TXN-20240101-001"],
        description="Référence de transaction (numéro mobile money, chèque…).",
    )

    @field_validator("payment_method")
    @classmethod
    def validate_method(cls, v: str) -> str:
        """Normalise en majuscules et rejette les méthodes inconnues."""
        upper = v.strip().upper()
        if upper not in _ALLOWED_PAYMENT_METHODS:
            raise ValueError(
                f"Méthode de paiement invalide : '{v}'. "
                f"Valeurs acceptées : {', '.join(sorted(_ALLOWED_PAYMENT_METHODS))}."
            )
        return upper


# ---------------------------------------------------------------------------
# Paiement — Réponse
# ---------------------------------------------------------------------------

class PaymentResponse(BaseModel):
    """Représentation publique d'un paiement."""

    model_config = ConfigDict(from_attributes=True)

    id: uuid.UUID
    order_id: uuid.UUID
    payment_method: str
    amount: int
    reference: Optional[str] = None
    paid_by: uuid.UUID
    paid_at: datetime


# ---------------------------------------------------------------------------
# Dépense opérationnelle — Création
# ---------------------------------------------------------------------------

class ExpenseCreate(BaseModel):
    """Corps de la requête POST /businesses/{business_id}/expenses."""

    reason: str = Field(
        ...,
        min_length=2,
        max_length=255,
        examples=["Achat de produits nettoyants"],
        description="Motif de la dépense.",
    )
    amount: int = Field(
        ...,
        gt=0,
        description="Montant de la dépense en FCFA (strictement positif).",
    )


# ---------------------------------------------------------------------------
# Dépense opérationnelle — Réponse
# ---------------------------------------------------------------------------

class ExpenseResponse(BaseModel):
    """Représentation publique d'une dépense opérationnelle."""

    model_config = ConfigDict(from_attributes=True)

    id: uuid.UUID
    business_id: uuid.UUID
    reason: str
    amount: int
    created_by: uuid.UUID
    created_at: datetime


# ---------------------------------------------------------------------------
# Créance client — Création
# ---------------------------------------------------------------------------

class CreditCreate(BaseModel):
    """Corps de la requête POST /businesses/{business_id}/credits."""

    customer_name: str = Field(
        ...,
        min_length=2,
        max_length=100,
        examples=["Oumar Coulibaly"],
        description="Nom du client débiteur.",
    )
    customer_phone: Optional[str] = Field(
        default=None,
        max_length=20,
        examples=["+22370000000"],
        description="Numéro de téléphone du client (optionnel).",
    )
    amount: int = Field(
        ...,
        gt=0,
        description="Montant de la créance en FCFA (strictement positif).",
    )
    reason: Optional[str] = Field(
        default=None,
        max_length=255,
        examples=["Lavage véhicule AB-1234-BA"],
        description="Motif ou description de la créance (optionnel).",
    )


# ---------------------------------------------------------------------------
# Créance client — Réponse
# ---------------------------------------------------------------------------

class CreditResponse(BaseModel):
    """Représentation publique d'une créance client."""

    model_config = ConfigDict(from_attributes=True)

    id: uuid.UUID
    business_id: uuid.UUID
    customer_name: str
    customer_phone: Optional[str] = None
    amount: int
    reason: Optional[str] = None
    status: str = Field(description="Statut de la créance : OUTSTANDING | REPAID.")
    created_by: uuid.UUID
    created_at: datetime
    repaid_at: Optional[datetime] = None
    repaid_by: Optional[uuid.UUID] = None
