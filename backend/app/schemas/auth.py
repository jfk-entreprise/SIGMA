"""
Schémas Pydantic pour le module d'authentification SIGMA.

Définit et valide les données entrantes et sortantes pour :
- La demande d'OTP
- La vérification d'OTP
- L'inscription utilisateur
- La connexion
- Les tokens JWT
"""
import re
import uuid
from typing import Optional

from pydantic import BaseModel, ConfigDict, EmailStr, Field, field_validator, model_validator


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

PHONE_REGEX = re.compile(r"^\+?[1-9]\d{7,14}$")
"""Numéro de téléphone E.164 simplifié : +22370000000 → accepté."""


def _validate_phone(value: str) -> str:
    cleaned = value.strip().replace(" ", "").replace("-", "")
    if not PHONE_REGEX.match(cleaned):
        raise ValueError(
            "Le numéro de téléphone doit être au format international E.164 "
            "(ex: +22370000000)."
        )
    return cleaned


def _validate_password_strength(value: str) -> str:
    errors: list[str] = []
    if len(value) < 8:
        errors.append("au moins 8 caractères")
    if not re.search(r"[A-Z]", value):
        errors.append("au moins une lettre majuscule")
    if not re.search(r"[a-z]", value):
        errors.append("au moins une lettre minuscule")
    if not re.search(r"\d", value):
        errors.append("au moins un chiffre")
    if errors:
        raise ValueError(
            f"Le mot de passe doit contenir : {', '.join(errors)}."
        )
    return value


# ---------------------------------------------------------------------------
# Schémas d'entrée (Request)
# ---------------------------------------------------------------------------


class OTPRequest(BaseModel):
    """Corps de la requête POST /auth/otp/request."""

    phone_number: str = Field(
        ...,
        examples=["+22370000000"],
        description="Numéro de téléphone au format international E.164.",
    )

    @field_validator("phone_number")
    @classmethod
    def validate_phone(cls, v: str) -> str:
        return _validate_phone(v)


class OTPVerify(BaseModel):
    """Corps de la requête POST /auth/otp/verify."""

    phone_number: str = Field(
        ...,
        examples=["+22370000000"],
        description="Numéro de téléphone ayant reçu l'OTP.",
    )
    otp_code: str = Field(
        ...,
        min_length=6,
        max_length=6,
        pattern=r"^\d{6}$",
        examples=["123456"],
        description="Code OTP à 6 chiffres reçu par SMS.",
    )

    @field_validator("phone_number")
    @classmethod
    def validate_phone(cls, v: str) -> str:
        return _validate_phone(v)


class UserRegister(BaseModel):
    """Corps de la requête POST /auth/register."""

    phone_number: str = Field(
        ...,
        examples=["+22370000000"],
        description="Numéro de téléphone vérifié (doit correspondre au token d'inscription).",
    )
    full_name: str = Field(
        ...,
        min_length=2,
        max_length=100,
        examples=["Amadou Diallo"],
        description="Nom complet de l'utilisateur.",
    )
    email: Optional[EmailStr] = Field(
        default=None,
        examples=["amadou@example.com"],
        description="Adresse e-mail optionnelle.",
    )
    password: str = Field(
        ...,
        min_length=8,
        max_length=72,
        examples=["Str0ngPass!"],
        description="Mot de passe (min. 8 car., 1 majuscule, 1 minuscule, 1 chiffre).",
    )
    confirm_password: str = Field(
        ...,
        max_length=72,
        examples=["Str0ngPass!"],
        description="Confirmation du mot de passe (doit être identique à `password`).",
    )

    @field_validator("phone_number")
    @classmethod
    def validate_phone(cls, v: str) -> str:
        return _validate_phone(v)

    @field_validator("password")
    @classmethod
    def validate_password(cls, v: str) -> str:
        return _validate_password_strength(v)

    @model_validator(mode="after")
    def passwords_match(self) -> "UserRegister":
        if self.password != self.confirm_password:
            raise ValueError("Les mots de passe ne correspondent pas.")
        return self


class UserLogin(BaseModel):
    """Corps de la requête POST /auth/login."""

    phone_number: str = Field(
        ...,
        examples=["+22370000000"],
        description="Numéro de téléphone enregistré.",
    )
    password: str = Field(
        ...,
        max_length=72,
        examples=["Str0ngPass!"],
        description="Mot de passe du compte.",
    )

    @field_validator("phone_number")
    @classmethod
    def validate_phone(cls, v: str) -> str:
        return _validate_phone(v)



# ---------------------------------------------------------------------------
# Schémas de sortie (Response)
# ---------------------------------------------------------------------------


class OTPRequestResponse(BaseModel):
    """Réponse de POST /auth/otp/request."""

    message: str
    phone_number: str
    expires_in_seconds: int


class OTPVerifyResponse(BaseModel):
    """Réponse de POST /auth/otp/verify (token temporaire d'inscription)."""

    registration_token: str
    token_type: str = "bearer"
    expires_in_seconds: int
    message: str


class Token(BaseModel):
    """Réponse de POST /auth/login (tokens JWT Access + Refresh)."""

    access_token: str
    refresh_token: str
    token_type: str = "bearer"
    expires_in: int = Field(description="Durée de validité de l'access token en secondes.")


class TokenPayload(BaseModel):
    """Payload décodé d'un token JWT SIGMA."""

    sub: str = Field(description="Identifiant unique de l'utilisateur (user_id).")
    phone_number: Optional[str] = None
    token_type: str = Field(description="'access' | 'refresh' | 'registration'.")
    exp: Optional[int] = None
    iat: Optional[int] = None


class UserResponse(BaseModel):
    """Représentation publique d'un utilisateur (sans données sensibles)."""

    model_config = ConfigDict(from_attributes=True)

    id: uuid.UUID
    phone_number: str
    full_name: str
    email: Optional[str] = None
    is_active: bool = True
