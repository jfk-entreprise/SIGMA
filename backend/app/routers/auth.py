"""
Router d'authentification SIGMA — /auth/*

Endpoints :
    POST /auth/otp/request   → Demande d'OTP (simulation SMS)
    POST /auth/otp/verify    → Vérification OTP → token temporaire d'inscription
    POST /auth/register      → Création de compte utilisateur (SQLAlchemy)
    POST /auth/login         → Connexion → Access Token + Refresh Token (SQLAlchemy)
"""
import logging
import secrets
import uuid
from datetime import datetime, timezone

from fastapi import APIRouter, Depends, Header, HTTPException, status
from jose import JWTError
from redis.asyncio import Redis
from redis.exceptions import RedisError
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core import redis_client as rc
from app.core.security import (
    create_access_token,
    create_refresh_token,
    create_registration_token,
    decode_token,
    generate_otp,
    hash_password,
    verify_password,
)
from app.config import settings
from app.db.session import get_db
from app.models.business import BusinessUser, UserRole
from app.models.user import User
from app.schemas.auth import (
    OTPRequest,
    OTPRequestResponse,
    OTPVerify,
    OTPVerifyResponse,
    Token,
    UserLogin,
    UserRegister,
    UserResponse,
)

logger = logging.getLogger(__name__)

router = APIRouter(
    prefix="/auth",
    tags=["Authentification"],
)


# ---------------------------------------------------------------------------
# Helper : recherche utilisateur via SQLAlchemy
# ---------------------------------------------------------------------------


async def _get_user_by_phone(db: AsyncSession, phone_number: str) -> User | None:
    """Requête SELECT * FROM users WHERE phone_number = ?"""
    result = await db.execute(
        select(User).where(User.phone_number == phone_number)
    )
    return result.scalar_one_or_none()


# ---------------------------------------------------------------------------
# Endpoint 1 : POST /auth/otp/request
# ---------------------------------------------------------------------------


@router.post(
    "/otp/request",
    response_model=OTPRequestResponse,
    status_code=status.HTTP_200_OK,
    summary="Demander un OTP par SMS",
    description=(
        "Génère un code OTP à 6 chiffres pour le numéro de téléphone fourni, "
        "le stocke dans Redis avec une expiration de 5 minutes, "
        "et simule l'envoi d'un SMS."
    ),
)
async def request_otp(
    body: OTPRequest,
    redis: Redis = Depends(rc.get_redis),
) -> OTPRequestResponse:
    """
    Protections :
    - Cooldown 60 s pour limiter le spam SMS.
    - Résistance aux pannes Redis (503).
    """
    try:
        if await rc.is_otp_cooldown_active(redis, body.phone_number):
            raise HTTPException(
                status_code=status.HTTP_429_TOO_MANY_REQUESTS,
                detail="Demandes d'OTP trop rapprochées. Veuillez patienter 60 secondes.",
            )

        otp_code = generate_otp(length=settings.OTP_LENGTH)
        expire_seconds = settings.OTP_EXPIRE_SECONDS

        await rc.store_otp(redis, body.phone_number, otp_code, expire_seconds)
        await rc.store_otp_cooldown(redis, body.phone_number, expire_seconds=60)
    except RedisError as e:
        logger.error("Défaut Redis lors de la demande OTP pour %s : %s", body.phone_number, e)
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail="Service d'authentification temporairement indisponible. Veuillez réessayer plus tard.",
        )

    _simulate_sms(phone_number=body.phone_number, otp_code=otp_code)

    logger.info(
        "[OTP REQUEST] Numéro: %s | Expire dans: %ds | Heure: %s",
        body.phone_number,
        expire_seconds,
        datetime.now(timezone.utc).isoformat(),
    )

    return OTPRequestResponse(
        message=(
            f"Un code de vérification a été envoyé au {body.phone_number}. "
            f"Il expire dans {expire_seconds // 60} minutes."
        ),
        phone_number=body.phone_number,
        expires_in_seconds=expire_seconds,
    )


# ---------------------------------------------------------------------------
# Endpoint 2 : POST /auth/otp/verify
# ---------------------------------------------------------------------------


@router.post(
    "/otp/verify",
    response_model=OTPVerifyResponse,
    status_code=status.HTTP_200_OK,
    summary="Vérifier un OTP",
    description=(
        "Vérifie le code OTP soumis contre celui stocké dans Redis. "
        "En cas de succès, retourne un token temporaire d'inscription valable 15 minutes."
    ),
)
async def verify_otp(
    body: OTPVerify,
    redis: Redis = Depends(rc.get_redis),
) -> OTPVerifyResponse:
    """
    Protections :
    - TOCTOU corrigé : incrémentation atomique en tête de route.
    - Comparaison en temps constant (secrets.compare_digest).
    - OTP usage unique (supprimé après vérification réussie).
    - Résistance aux pannes Redis (503).
    """
    phone_number = body.phone_number

    try:
        attempts = await rc.increment_otp_attempts(redis, phone_number)

        if attempts > rc.MAX_OTP_ATTEMPTS:
            logger.warning(
                "[OTP VERIFY] Blocage : Trop de tentatives pour %s (%d/%d)",
                phone_number, attempts, rc.MAX_OTP_ATTEMPTS,
            )
            raise HTTPException(
                status_code=status.HTTP_429_TOO_MANY_REQUESTS,
                detail="Trop de tentatives OTP pour ce numéro. Veuillez demander un nouveau code.",
            )

        stored_otp = await rc.get_otp(redis, phone_number)
    except RedisError as e:
        logger.error("Défaut Redis lors de la vérification OTP pour %s : %s", phone_number, e)
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail="Service d'authentification temporairement indisponible. Veuillez réessayer plus tard.",
        )

    if stored_otp is None:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Aucun code OTP actif pour ce numéro. Veuillez en demander un nouveau.",
        )

    if not secrets.compare_digest(stored_otp, body.otp_code):
        remaining = rc.MAX_OTP_ATTEMPTS - attempts
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=(
                "Code OTP incorrect. "
                f"{'Dernière tentative.' if remaining <= 0 else f'Il vous reste {remaining} tentative(s).'}"
            ),
        )

    try:
        await rc.delete_otp(redis, phone_number)
        registration_token = create_registration_token(phone_number=phone_number)
        expire_seconds = settings.REGISTRATION_TOKEN_EXPIRE_MINUTES * 60
        await rc.store_registration_token(
            redis,
            token=registration_token,
            phone_number=phone_number,
            expire_seconds=expire_seconds,
        )
    except RedisError as e:
        logger.error("Défaut Redis lors de l'enregistrement du token pour %s : %s", phone_number, e)
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail="Service d'authentification temporairement indisponible. Veuillez réessayer plus tard.",
        )

    logger.info("[OTP VERIFY] ✅ Vérification réussie pour %s | Token d'inscription délivré", phone_number)

    return OTPVerifyResponse(
        registration_token=registration_token,
        token_type="bearer",
        expires_in_seconds=expire_seconds,
        message=(
            "Numéro de téléphone vérifié avec succès. "
            "Utilisez ce token pour finaliser votre inscription."
        ),
    )


# ---------------------------------------------------------------------------
# Endpoint 3 : POST /auth/register
# ---------------------------------------------------------------------------


@router.post(
    "/register",
    response_model=UserResponse,
    status_code=status.HTTP_201_CREATED,
    summary="Créer un compte utilisateur",
    description=(
        "Finalise la création du compte utilisateur. "
        "Requiert le token temporaire d'inscription obtenu après vérification OTP."
    ),
)
async def register_user(
    body: UserRegister,
    redis: Redis = Depends(rc.get_redis),
    db: AsyncSession = Depends(get_db),
    authorization: str = Header(
        ...,
        alias="Authorization",
        description="Token d'inscription sous la forme : Bearer <registration_token>",
        examples=["Bearer eyJhbGciOiJIUzI1NiIsInR5cCI6IkpXVCJ9..."],
    ),
) -> UserResponse:
    # 1. Extraire le token
    if not authorization.startswith("Bearer "):
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Format d'autorisation invalide. Utilisez: Bearer <token>",
            headers={"WWW-Authenticate": "Bearer"},
        )
    raw_token = authorization.removeprefix("Bearer ").strip()

    # 2. Décoder et valider le JWT d'inscription
    try:
        token_payload = decode_token(raw_token)
    except JWTError:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Token d'inscription invalide ou expiré.",
            headers={"WWW-Authenticate": "Bearer"},
        )

    if token_payload.token_type != "registration":
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Ce token n'est pas un token d'inscription valide.",
        )

    # 3. Cohérence du numéro
    if token_payload.phone_number != body.phone_number:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail=(
                "Le numéro de téléphone ne correspond pas à celui vérifié lors de l'étape OTP."
            ),
        )

    # 4. Vérifier que le token existe encore dans Redis (non révoqué)
    try:
        stored_phone = await rc.get_registration_token_phone(redis, raw_token)
    except RedisError as e:
        logger.error(
            "Défaut Redis lors de la validation du token d'inscription pour %s : %s",
            body.phone_number, e,
        )
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail="Service d'authentification temporairement indisponible. Veuillez réessayer plus tard.",
        )

    if stored_phone is None:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Token d'inscription introuvable ou déjà utilisé.",
            headers={"WWW-Authenticate": "Bearer"},
        )

    # 5. Vérifier l'unicité du numéro en DB
    existing_user = await _get_user_by_phone(db, body.phone_number)
    if existing_user:
        # Vérifier si le compte possède un rôle privilégié (OWNER ou MANAGER).
        # Si oui → 409 : l'utilisateur doit se connecter normalement.
        # Si non (WORKER ou aucune appartenance) → parcours "claim" :
        # l'OTP prouve que le téléphone lui appartient, on finalise le compte.
        privileged = await db.execute(
            select(BusinessUser).where(
                BusinessUser.user_id == existing_user.id,
                BusinessUser.role.in_([UserRole.OWNER, UserRole.MANAGER]),
            )
        )
        if privileged.scalar_one_or_none() is not None:
            raise HTTPException(
                status_code=status.HTTP_409_CONFLICT,
                detail=(
                    f"Un compte actif existe déjà pour le numéro {body.phone_number}. "
                    "Veuillez vous connecter."
                ),
            )

        # Compte Worker ou sans commerce → mise à jour des credentials
        existing_user.full_name = body.full_name
        existing_user.email = body.email
        existing_user.hashed_password = hash_password(body.password)
        existing_user.is_active = True
        await db.flush()
        new_user = existing_user
        logger.info(
            "[REGISTER] ✅ Compte Worker finalisé | id=%s | phone=%s",
            new_user.id, new_user.phone_number,
        )
    else:
        # 6. Créer l'utilisateur en base de données
        new_user = User(
            id=uuid.uuid4(),
            phone_number=body.phone_number,
            full_name=body.full_name,
            email=body.email,
            hashed_password=hash_password(body.password),
            is_active=True,
        )
        db.add(new_user)
        await db.flush()
        logger.info(
            "[REGISTER] ✅ Compte créé | id=%s | phone=%s | name=%s",
            new_user.id, new_user.phone_number, new_user.full_name,
        )

    # 7. Invalider le token d'inscription (usage unique)
    try:
        await rc.delete_registration_token(redis, raw_token)
    except RedisError as e:
        logger.error("Défaut Redis lors de la suppression du token d'inscription : %s", e)

    return UserResponse(
        id=new_user.id,
        phone_number=new_user.phone_number,
        full_name=new_user.full_name,
        email=new_user.email,
        is_active=new_user.is_active,
    )


# ---------------------------------------------------------------------------
# Endpoint 4 : POST /auth/login
# ---------------------------------------------------------------------------


@router.post(
    "/login",
    response_model=Token,
    status_code=status.HTTP_200_OK,
    summary="Connexion et génération des tokens JWT",
    description=(
        "Authentifie l'utilisateur avec son numéro de téléphone et son mot de passe. "
        "En cas de succès, retourne un Access Token (30 min) et un Refresh Token (7 jours)."
    ),
)
async def login(
    body: UserLogin,
    redis: Redis = Depends(rc.get_redis),
    db: AsyncSession = Depends(get_db),
) -> Token:
    """
    Protections :
    - Rate limiting Redis (max 5 tentatives / 15 min) — fail-open si Redis KO.
    - Anti-énumération : message d'erreur identique pour tous les cas d'échec.
    - Anti-timing : vérification bcrypt même si l'utilisateur n'existe pas.
    - is_active vérifié APRÈS le mot de passe pour ne pas fuiter l'état du compte.
    """
    _INVALID_CREDENTIALS_MSG = "Numéro de téléphone ou mot de passe incorrect."

    # 0. Rate limiting (fail-open)
    try:
        attempts = await rc.increment_login_attempts(redis, body.phone_number)
        if attempts > rc.MAX_LOGIN_ATTEMPTS:
            logger.warning(
                "[LOGIN] Trop de tentatives pour %s (%d/%d) — bloqué 15 min",
                body.phone_number, attempts, rc.MAX_LOGIN_ATTEMPTS,
            )
            raise HTTPException(
                status_code=status.HTTP_429_TOO_MANY_REQUESTS,
                detail="Trop de tentatives de connexion. Veuillez réessayer dans 15 minutes.",
            )
    except RedisError as e:
        logger.warning(
            "[LOGIN] Rate limiting indisponible pour %s (Redis KO) : %s — fail-open",
            body.phone_number, e,
        )

    # 1. Rechercher l'utilisateur
    user = await _get_user_by_phone(db, body.phone_number)

    if not user:
        logger.warning("[LOGIN] Tentative avec numéro inconnu: %s", body.phone_number)
        verify_password(body.password, "$2b$12$Lpy8yHn04s4e613K3l4P3e1B1G2H3I4J5K6L7M8N9O0P1Q2R3S4Tu")
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail=_INVALID_CREDENTIALS_MSG,
            headers={"WWW-Authenticate": "Bearer"},
        )

    # 2. Vérifier le mot de passe
    if not verify_password(body.password, user.hashed_password):
        logger.warning("[LOGIN] Mot de passe incorrect pour %s", body.phone_number)
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail=_INVALID_CREDENTIALS_MSG,
            headers={"WWW-Authenticate": "Bearer"},
        )

    # 3. Vérifier is_active (après mot de passe — anti-énumération)
    if not user.is_active:
        logger.warning(
            "[LOGIN] Connexion refusée — compte désactivé (mot de passe valide): %s",
            body.phone_number,
        )
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail=_INVALID_CREDENTIALS_MSG,
            headers={"WWW-Authenticate": "Bearer"},
        )

    # 4. Connexion réussie — réinitialiser compteur
    try:
        await rc.reset_login_attempts(redis, body.phone_number)
    except RedisError as e:
        logger.warning("[LOGIN] Impossible de réinitialiser le compteur : %s", e)

    # 5. Générer les tokens JWT
    access_token = create_access_token(
        user_id=str(user.id),
        phone_number=user.phone_number,
    )
    refresh_token = create_refresh_token(user_id=str(user.id))

    logger.info("[LOGIN] ✅ Connexion réussie | id=%s | phone=%s", user.id, user.phone_number)

    return Token(
        access_token=access_token,
        refresh_token=refresh_token,
        token_type="bearer",
        expires_in=settings.ACCESS_TOKEN_EXPIRE_MINUTES * 60,
    )


# ---------------------------------------------------------------------------
# Helper interne : simulation SMS
# ---------------------------------------------------------------------------


def _simulate_sms(phone_number: str, otp_code: str) -> None:
    """
    Simule l'envoi d'un SMS OTP.
    En production, remplacer par Twilio / Orange API / Africa's Talking.
    """
    if settings.ENVIRONMENT == "development":
        logger.info(
            "📱 [SMS SIMULÉ] → Destinataire: %s | Code: %s | Expire: %s",
            phone_number, otp_code,
            datetime.now(timezone.utc).isoformat(),
        )
        print(f"\n{'='*60}")
        print(f"  📱 SMS SIMULÉ → {phone_number}")
        print(f"  🔑 Code OTP   : {otp_code}")
        print(f"  ⏱️  Expire dans : 5 minutes")
        print(f"{'='*60}\n")
    else:
        logger.info("📱 [SMS] Envoi déclenché pour %s (OTP masqué en production)", phone_number)
