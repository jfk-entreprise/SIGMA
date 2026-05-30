"""
Schémas Pydantic pour le module Business SIGMA.

Couvre :
- Création / réponse de commerce
- Items de prestation (BusinessItem)
- Création de staff (Manager / Worker) par l'Owner
"""
import uuid
from datetime import datetime
from typing import Literal, Optional

from pydantic import BaseModel, ConfigDict, Field

from app.models.business import BusinessType, UserRole
from app.schemas.auth import _validate_phone, _validate_password_strength


# ---------------------------------------------------------------------------
# Commerce — Création
# ---------------------------------------------------------------------------

class BusinessCreate(BaseModel):
    """Corps de la requête POST /businesses/"""

    name: str = Field(
        ...,
        min_length=2,
        max_length=100,
        examples=["Lavage Express Bamako"],
        description="Nom du commerce.",
    )
    business_type: str = Field(
        ...,
        examples=["WASH"],
        description=f"Type de commerce : {', '.join(BusinessType.ALL)}.",
    )
    phone: Optional[str] = Field(
        default=None,
        examples=["+22370000000"],
        description="Numéro de téléphone du commerce (optionnel).",
    )
    location: Optional[str] = Field(
        default=None,
        max_length=255,
        examples=["Quartier du Fleuve, Bamako"],
        description="Adresse ou description de localisation.",
    )

    def model_post_init(self, __context: object) -> None:
        if self.business_type not in BusinessType.ALL:
            raise ValueError(
                f"Type de commerce invalide '{self.business_type}'. "
                f"Valeurs acceptées : {', '.join(BusinessType.ALL)}."
            )


# ---------------------------------------------------------------------------
# Commerce — Réponse
# ---------------------------------------------------------------------------

class BusinessResponse(BaseModel):
    """Représentation publique d'un commerce."""

    model_config = ConfigDict(from_attributes=True)

    id: uuid.UUID
    name: str
    business_type: str
    phone: Optional[str] = None
    location: Optional[str] = None
    is_active: bool
    owner_id: uuid.UUID
    created_at: datetime


# ---------------------------------------------------------------------------
# Item de prestation — Réponse
# ---------------------------------------------------------------------------

class BusinessItemResponse(BaseModel):
    """Représentation publique d'un item de prestation d'un commerce."""

    model_config = ConfigDict(from_attributes=True)

    id: uuid.UUID
    business_id: uuid.UUID
    item_definition_id: uuid.UUID
    custom_name: str
    custom_price: int
    is_active: bool
    display_order: int
    category: str  # Propriété calculée depuis definition.category


# ---------------------------------------------------------------------------
# Item de prestation — Mise à jour partielle
# ---------------------------------------------------------------------------

class BusinessItemUpdate(BaseModel):
    """Corps de la requête PATCH /businesses/items/{item_id}"""

    custom_price: Optional[int] = Field(
        default=None,
        ge=0,
        description="Prix personnalisé en unité monétaire locale (ex: FCFA).",
    )
    is_active: Optional[bool] = Field(
        default=None,
        description="Active ou désactive la prestation pour ce commerce.",
    )
    custom_name: Optional[str] = Field(
        default=None,
        min_length=1,
        max_length=100,
        description="Nom personnalisé de la prestation (optionnel).",
    )


# ---------------------------------------------------------------------------
# Création de staff (Manager / Worker) par l'Owner
# ---------------------------------------------------------------------------

class UserCreateManager(BaseModel):
    """
    Corps de la requête POST /businesses/managers.
    Permet à l'Owner de créer un Gérant (MANAGER) avec accès applicatif complet.
    """

    full_name: str = Field(
        ...,
        min_length=2,
        max_length=100,
        examples=["Ibrahim Touré"],
        description="Nom complet du gérant.",
    )
    phone_number: str = Field(
        ...,
        examples=["+22370000001"],
        description="Numéro de téléphone (identifiant de connexion).",
    )
    password: str = Field(
        ...,
        min_length=8,
        max_length=72,
        examples=["SecurePass1!"],
        description="Mot de passe initial du gérant.",
    )
    role: Literal["MANAGER"] = UserRole.MANAGER

    def model_post_init(self, __context: object) -> None:
        _validate_phone(self.phone_number)
        _validate_password_strength(self.password)


class UserCreateWorker(BaseModel):
    """
    Corps de la requête POST /businesses/workers.
    Permet à l'Owner de créer un Travailleur (WORKER) — accès limité, sans mot de passe applicatif.
    """

    full_name: str = Field(
        ...,
        min_length=2,
        max_length=100,
        examples=["Moussa Koné"],
        description="Nom complet du travailleur.",
    )
    phone_number: str = Field(
        ...,
        examples=["+22370000002"],
        description="Numéro de téléphone du travailleur.",
    )
    role: Literal["WORKER"] = UserRole.WORKER

    def model_post_init(self, __context: object) -> None:
        _validate_phone(self.phone_number)


# ---------------------------------------------------------------------------
# Réponse membre du commerce
# ---------------------------------------------------------------------------

class BusinessMemberResponse(BaseModel):
    """Représentation publique d'un membre du commerce."""

    model_config = ConfigDict(from_attributes=True)

    id: uuid.UUID
    user_id: uuid.UUID
    full_name: str
    phone_number: str
    role: str
    created_at: datetime
