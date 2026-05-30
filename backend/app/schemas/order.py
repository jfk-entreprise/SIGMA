"""
Schémas Pydantic pour le module Commandes SIGMA.

Couvre :
- Création d'une ligne de commande (OrderItemCreate)
- Création d'une commande de service (OrderCreate)
- Représentation publique d'une ligne (OrderItemResponse)
- Représentation publique d'une commande (OrderResponse)
"""
import uuid
from datetime import datetime
from typing import Optional

from pydantic import BaseModel, ConfigDict, Field


# ---------------------------------------------------------------------------
# Ligne de commande — Création
# ---------------------------------------------------------------------------

class OrderItemCreate(BaseModel):
    """Un item et sa quantité souhaitée dans la commande."""

    business_item_id: uuid.UUID = Field(
        ...,
        description="Identifiant de la prestation (BusinessItem) du commerce.",
    )
    quantity: int = Field(
        default=1,
        ge=1,
        le=100,
        description="Quantité commandée (1 – 100).",
    )


# ---------------------------------------------------------------------------
# Commande — Création
# ---------------------------------------------------------------------------

class OrderCreate(BaseModel):
    """
    Corps de la requête POST /orders/.

    Les champs vehicle_* ne sont pertinents que pour le type WASH ;
    ils restent nullable pour les commerces LAUNDRY/PRESSING.
    Au moins un item doit être fourni.
    """

    # Informations client (optionnelles)
    customer_name: Optional[str] = Field(
        default=None,
        max_length=100,
        examples=["Mamadou Diarra"],
        description="Nom du client (optionnel).",
    )
    customer_phone: Optional[str] = Field(
        default=None,
        max_length=20,
        examples=["+22370000000"],
        description="Numéro de téléphone du client (optionnel).",
    )

    # Informations véhicule — WASH uniquement, nullable pour LAUNDRY/PRESSING
    vehicle_number: Optional[str] = Field(
        default=None,
        max_length=20,
        examples=["AB-1234-BA"],
        description="Immatriculation du véhicule (WASH uniquement, optionnel).",
    )
    vehicle_color: Optional[str] = Field(
        default=None,
        max_length=50,
        examples=["Blanc"],
        description="Couleur du véhicule (WASH uniquement, optionnel).",
    )
    wash_type: Optional[str] = Field(
        default=None,
        max_length=50,
        examples=["Intérieur + Extérieur"],
        description="Type de lavage (WASH uniquement, optionnel).",
    )

    # Items (au moins 1 requis)
    items: list[OrderItemCreate] = Field(
        ...,
        min_length=1,
        description="Liste des prestations commandées (au moins 1 item).",
    )

    # Réduction appliquée en FCFA
    discount: int = Field(
        default=0,
        ge=0,
        description="Réduction accordée en FCFA (≥ 0, 0 par défaut).",
    )


# ---------------------------------------------------------------------------
# Ligne de commande — Réponse
# ---------------------------------------------------------------------------

class OrderItemResponse(BaseModel):
    """Représentation publique d'une ligne de commande (snapshot prix)."""

    model_config = ConfigDict(from_attributes=True)

    id: uuid.UUID
    business_item_id: uuid.UUID
    quantity: int
    unit_price: int = Field(description="Prix unitaire snapshot au moment de la commande (FCFA).")
    total_price: int = Field(description="quantity × unit_price (FCFA).")


# ---------------------------------------------------------------------------
# Commande — Réponse
# ---------------------------------------------------------------------------

class OrderResponse(BaseModel):
    """Représentation publique d'une commande de service."""

    model_config = ConfigDict(from_attributes=True)

    id: uuid.UUID
    business_id: uuid.UUID

    # Client
    customer_name: Optional[str] = None
    customer_phone: Optional[str] = None

    # Véhicule
    vehicle_number: Optional[str] = None
    vehicle_color: Optional[str] = None
    wash_type: Optional[str] = None

    # Statut & montants
    status: str = Field(description="Statut de la commande : PENDING | PAID | CANCELLED.")
    subtotal: int = Field(description="Somme des total_price des lignes (FCFA).")
    discount: int = Field(description="Réduction appliquée (FCFA).")
    total: int = Field(description="subtotal - discount (FCFA).")

    # Audit
    created_by: uuid.UUID
    created_at: datetime
    completed_at: Optional[datetime] = None

    # Lignes de commande
    items: list[OrderItemResponse] = []
