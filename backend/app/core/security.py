"""
Utilitaires de sécurité SIGMA.

Responsabilités :
- Hachage et vérification des mots de passe (bcrypt via passlib)
- Génération et décodage des tokens JWT (Access & Refresh)
- Génération des codes OTP
- Génération des tokens temporaires d'inscription
"""
import logging
import secrets
import string
from datetime import datetime, timedelta, timezone
from typing import Optional

from jose import JWTError, jwt
from passlib.context import CryptContext

from app.config import settings
from app.schemas.auth import TokenPayload

logger = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# Hachage de mots de passe (bcrypt)
# ---------------------------------------------------------------------------

pwd_context = CryptContext(
    schemes=["bcrypt"],
    deprecated="auto",
    bcrypt__rounds=12,  # Bon équilibre sécurité / performance en 2024+
)


def hash_password(plain_password: str) -> str:
    """
    Hache un mot de passe en clair avec bcrypt.

    Args:
        plain_password: Mot de passe en clair.

    Returns:
        Hash bcrypt du mot de passe.
    """
    return pwd_context.hash(plain_password)


def verify_password(plain_password: str, hashed_password: str) -> bool:
    """
    Vérifie un mot de passe en clair contre un hash bcrypt.

    Args:
        plain_password: Mot de passe saisi par l'utilisateur.
        hashed_password: Hash stocké en base de données.

    Returns:
        True si le mot de passe correspond, False sinon.
    """
    return pwd_context.verify(plain_password, hashed_password)


# ---------------------------------------------------------------------------
# Génération OTP
# ---------------------------------------------------------------------------


def generate_otp(length: int = 6) -> str:
    """
    Génère un code OTP numérique cryptographiquement sûr.

    Args:
        length: Nombre de chiffres du code (défaut: 6).

    Returns:
        Code OTP sous forme de chaîne (avec zéros de tête si nécessaire).
    """
    digits = string.digits
    otp = "".join(secrets.choice(digits) for _ in range(length))
    logger.debug("OTP généré (longueur: %d)", length)
    return otp


# ---------------------------------------------------------------------------
# JWT — Tokens d'accès et de rafraîchissement
# ---------------------------------------------------------------------------


def _create_token(
    subject: str,
    token_type: str,
    expires_delta: timedelta,
    extra_claims: Optional[dict] = None,
) -> str:
    """
    Fonction interne de création d'un token JWT signé.

    Args:
        subject: Identifiant de l'utilisateur (user_id).
        token_type: Type du token ('access', 'refresh', 'registration').
        expires_delta: Durée de validité.
        extra_claims: Revendications supplémentaires à inclure dans le payload.

    Returns:
        Token JWT encodé (string).
    """
    now = datetime.now(timezone.utc)
    payload: dict = {
        "sub": str(subject),
        "token_type": token_type,
        "iat": now,
        "exp": now + expires_delta,
    }
    if extra_claims:
        payload.update(extra_claims)

    encoded = jwt.encode(
        payload,
        settings.JWT_SECRET_KEY,
        algorithm=settings.JWT_ALGORITHM,
    )
    logger.debug("Token JWT '%s' créé pour sub=%s", token_type, subject)
    return encoded


def create_access_token(
    user_id: str,
    phone_number: Optional[str] = None,
    extra_claims: Optional[dict] = None,
) -> str:
    """
    Crée un Access Token JWT (courte durée de vie).

    Args:
        user_id: Identifiant unique de l'utilisateur.
        phone_number: Numéro de téléphone (ajouté au payload pour facilité).
        extra_claims: Revendications supplémentaires.

    Returns:
        Access token JWT encodé.
    """
    claims = extra_claims or {}
    if phone_number:
        claims["phone_number"] = phone_number

    return _create_token(
        subject=user_id,
        token_type="access",
        expires_delta=timedelta(minutes=settings.ACCESS_TOKEN_EXPIRE_MINUTES),
        extra_claims=claims,
    )


def create_refresh_token(
    user_id: str,
    extra_claims: Optional[dict] = None,
) -> str:
    """
    Crée un Refresh Token JWT (longue durée de vie).

    Args:
        user_id: Identifiant unique de l'utilisateur.
        extra_claims: Revendications supplémentaires.

    Returns:
        Refresh token JWT encodé.
    """
    return _create_token(
        subject=user_id,
        token_type="refresh",
        expires_delta=timedelta(days=settings.REFRESH_TOKEN_EXPIRE_DAYS),
        extra_claims=extra_claims,
    )


def create_registration_token(
    phone_number: str,
    extra_claims: Optional[dict] = None,
) -> str:
    """
    Crée un token JWT temporaire accordé après vérification OTP.
    Ce token autorise exclusivement l'appel à /auth/register.

    Args:
        phone_number: Numéro de téléphone vérifié.
        extra_claims: Revendications supplémentaires.

    Returns:
        Token d'inscription JWT encodé.
    """
    claims = {"phone_number": phone_number, **(extra_claims or {})}
    return _create_token(
        subject=phone_number,
        token_type="registration",
        expires_delta=timedelta(minutes=settings.REGISTRATION_TOKEN_EXPIRE_MINUTES),
        extra_claims=claims,
    )


def decode_token(token: str) -> TokenPayload:
    """
    Décode et valide un token JWT SIGMA.

    Args:
        token: Token JWT à décoder.

    Returns:
        Payload structuré sous forme de TokenPayload.

    Raises:
        JWTError: Si le token est invalide, expiré, ou mal formé.
    """
    try:
        raw_payload = jwt.decode(
            token,
            settings.JWT_SECRET_KEY,
            algorithms=[settings.JWT_ALGORITHM],
        )
        return TokenPayload(**raw_payload)
    except JWTError as e:
        logger.warning("Échec du décodage JWT : %s", e)
        raise


def generate_secure_token(nbytes: int = 32) -> str:
    """
    Génère un token aléatoire cryptographiquement sûr (URL-safe base64).
    Utile pour les identifiants opaques (ex: clé Redis).

    Args:
        nbytes: Nombre d'octets d'entropie (défaut: 32 → ~43 caractères).

    Returns:
        Chaîne URL-safe base64.
    """
    return secrets.token_urlsafe(nbytes)
