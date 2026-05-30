"""
Client Redis asynchrone pour SIGMA.

Fournit un pool de connexions Redis partagé via aioredis,
avec des helpers spécifiques aux besoins de l'application
(OTP, tokens temporaires, blacklist JWT…).
"""
import logging
from typing import Optional

import redis.asyncio as aioredis
from redis.asyncio import Redis
from redis.exceptions import RedisError

from app.config import settings

logger = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# Pool de connexions global (initialisé au démarrage de l'app)
# ---------------------------------------------------------------------------

_redis_pool: Optional[Redis] = None


async def get_redis_pool() -> Redis:
    """
    Retourne le pool Redis global.
    Lève une RuntimeError si le pool n'a pas encore été initialisé.
    """
    if _redis_pool is None:
        raise RuntimeError(
            "Le pool Redis n'est pas initialisé. "
            "Appelez `init_redis_pool()` au démarrage de l'application."
        )
    return _redis_pool


async def init_redis_pool() -> None:
    """Initialise le pool de connexions Redis. À appeler dans le lifespan FastAPI."""
    global _redis_pool
    _redis_pool = await aioredis.from_url(
        settings.REDIS_URL,
        encoding="utf-8",
        decode_responses=True,
        socket_connect_timeout=5,
        socket_timeout=5,
        retry_on_timeout=True,
        health_check_interval=30,
    )
    # Vérification de la connectivité
    await _redis_pool.ping()
    logger.info("✅ Pool Redis initialisé : %s", settings.REDIS_URL)


async def close_redis_pool() -> None:
    """Ferme proprement le pool Redis. À appeler dans le shutdown de l'app."""
    global _redis_pool
    if _redis_pool is not None:
        await _redis_pool.aclose()
        _redis_pool = None
        logger.info("🔌 Pool Redis fermé.")


# ---------------------------------------------------------------------------
# Dépendance FastAPI
# ---------------------------------------------------------------------------


async def get_redis() -> Redis:
    """
    Dépendance FastAPI qui injecte le client Redis dans les endpoints.

    Usage:
        @router.post("/example")
        async def example(redis: Redis = Depends(get_redis)):
            ...
    """
    return await get_redis_pool()


# ---------------------------------------------------------------------------
# Helpers OTP
# ---------------------------------------------------------------------------

OTP_KEY_PREFIX = "sigma:otp:"
OTP_ATTEMPTS_PREFIX = "sigma:otp_attempts:"
MAX_OTP_ATTEMPTS = 5


def _otp_key(phone_number: str) -> str:
    """Clé Redis pour l'OTP d'un numéro de téléphone."""
    return f"{OTP_KEY_PREFIX}{phone_number}"


def _otp_attempts_key(phone_number: str) -> str:
    """Clé Redis pour le compteur de tentatives OTP."""
    return f"{OTP_ATTEMPTS_PREFIX}{phone_number}"


async def store_otp(
    redis: Redis,
    phone_number: str,
    otp_code: str,
    expire_seconds: int,
) -> None:
    """
    Stocke un code OTP dans Redis avec une expiration donnée.

    Args:
        redis: Client Redis injecté.
        phone_number: Numéro de téléphone associé à l'OTP.
        otp_code: Code OTP à 6 chiffres.
        expire_seconds: Durée de validité en secondes.
    """
    key = _otp_key(phone_number)
    try:
        await redis.set(key, otp_code, ex=expire_seconds)
        # Réinitialise le compteur de tentatives lors d'un nouvel OTP
        await redis.delete(_otp_attempts_key(phone_number))
        logger.debug("OTP stocké pour %s (expire dans %ds)", phone_number, expire_seconds)
    except RedisError as e:
        logger.error("Erreur Redis lors du stockage de l'OTP : %s", e)
        raise


async def get_otp(redis: Redis, phone_number: str) -> Optional[str]:
    """
    Récupère l'OTP stocké pour un numéro de téléphone.

    Returns:
        Le code OTP si trouvé et non expiré, None sinon.
    """
    key = _otp_key(phone_number)
    try:
        return await redis.get(key)
    except RedisError as e:
        logger.error("Erreur Redis lors de la lecture de l'OTP : %s", e)
        raise


async def delete_otp(redis: Redis, phone_number: str) -> None:
    """Supprime l'OTP d'un numéro de téléphone (après vérification réussie)."""
    try:
        await redis.delete(_otp_key(phone_number))
        await redis.delete(_otp_attempts_key(phone_number))
    except RedisError as e:
        logger.error("Erreur Redis lors de la suppression de l'OTP : %s", e)
        raise


async def increment_otp_attempts(redis: Redis, phone_number: str) -> int:
    """
    Incrémente le compteur de tentatives OTP échouées.

    Returns:
        Le nombre total de tentatives après incrémentation.
    """
    key = _otp_attempts_key(phone_number)
    try:
        attempts = await redis.incr(key)
        # L'expiration du compteur suit celle de l'OTP
        await redis.expire(key, settings.OTP_EXPIRE_SECONDS)
        return attempts
    except RedisError as e:
        logger.error("Erreur Redis (compteur tentatives OTP) : %s", e)
        raise


async def get_otp_ttl(redis: Redis, phone_number: str) -> int:
    """
    Retourne le TTL restant (en secondes) de l'OTP.

    Returns:
        TTL en secondes, ou -2 si la clé n'existe pas, -1 si pas d'expiration.
    """
    try:
        return await redis.ttl(_otp_key(phone_number))
    except RedisError as e:
        logger.error("Erreur Redis (TTL OTP) : %s", e)
        raise


# ---------------------------------------------------------------------------
# Helpers Cooldown OTP
# ---------------------------------------------------------------------------

OTP_COOLDOWN_PREFIX = "sigma:otp_cooldown:"


def _otp_cooldown_key(phone_number: str) -> str:
    """Clé Redis pour le cooldown OTP."""
    return f"{OTP_COOLDOWN_PREFIX}{phone_number}"


async def store_otp_cooldown(
    redis: Redis, phone_number: str, expire_seconds: int = 60
) -> None:
    """Pose un verrou temporaire pour limiter le spam de demandes d'OTP (anti-spam)."""
    key = _otp_cooldown_key(phone_number)
    try:
        await redis.set(key, "1", ex=expire_seconds)
        logger.debug("Cooldown OTP posé pour %s (%ds)", phone_number, expire_seconds)
    except RedisError as e:
        logger.error("Erreur Redis (stockage cooldown OTP) : %s", e)
        raise


async def is_otp_cooldown_active(redis: Redis, phone_number: str) -> bool:
    """Vérifie si le cooldown de demande d'OTP est encore actif."""
    key = _otp_cooldown_key(phone_number)
    try:
        return await redis.exists(key) > 0
    except RedisError as e:
        logger.error("Erreur Redis (lecture cooldown OTP) : %s", e)
        raise



# ---------------------------------------------------------------------------
# Helpers Token d'inscription temporaire
# ---------------------------------------------------------------------------

REGISTRATION_TOKEN_PREFIX = "sigma:reg_token:"


def _registration_token_key(token: str) -> str:
    return f"{REGISTRATION_TOKEN_PREFIX}{token}"


async def store_registration_token(
    redis: Redis,
    token: str,
    phone_number: str,
    expire_seconds: int,
) -> None:
    """
    Stocke un token temporaire d'autorisation d'inscription.
    La valeur est le numéro de téléphone vérifié.
    """
    key = _registration_token_key(token)
    try:
        await redis.set(key, phone_number, ex=expire_seconds)
        logger.debug(
            "Token d'inscription stocké pour %s (expire dans %ds)",
            phone_number,
            expire_seconds,
        )
    except RedisError as e:
        logger.error("Erreur Redis (stockage token inscription) : %s", e)
        raise


async def get_registration_token_phone(
    redis: Redis, token: str
) -> Optional[str]:
    """
    Vérifie et retourne le numéro de téléphone associé à un token d'inscription.

    Returns:
        Le numéro de téléphone si le token est valide, None sinon.
    """
    key = _registration_token_key(token)
    try:
        return await redis.get(key)
    except RedisError as e:
        logger.error("Erreur Redis (lecture token inscription) : %s", e)
        raise


async def delete_registration_token(redis: Redis, token: str) -> None:
    """Invalide un token d'inscription après utilisation."""
    try:
        await redis.delete(_registration_token_key(token))
    except RedisError as e:
        logger.error("Erreur Redis (suppression token inscription) : %s", e)
        raise


# ---------------------------------------------------------------------------
# Helpers Rate Limiting — Connexion (/auth/login)
# ---------------------------------------------------------------------------

LOGIN_ATTEMPTS_PREFIX = "sigma:login_limit:"
MAX_LOGIN_ATTEMPTS = 5
LOGIN_WINDOW_SECONDS = 15 * 60  # 15 minutes


def _login_attempts_key(phone_number: str) -> str:
    """Clé Redis pour le compteur de tentatives de connexion."""
    return f"{LOGIN_ATTEMPTS_PREFIX}{phone_number}"


async def increment_login_attempts(redis: Redis, phone_number: str) -> int:
    """
    Incrémente atomiquement le compteur de tentatives de connexion échouées.
    L'expiration (fenêtre glissante de 15 min) est posée uniquement à la première tentative.

    Returns:
        Nombre total de tentatives après incrémentation.
    """
    key = _login_attempts_key(phone_number)
    try:
        attempts = await redis.incr(key)
        if attempts == 1:
            await redis.expire(key, LOGIN_WINDOW_SECONDS)
        return attempts
    except RedisError as e:
        logger.error("Erreur Redis (compteur tentatives login) : %s", e)
        raise


async def reset_login_attempts(redis: Redis, phone_number: str) -> None:
    """Réinitialise le compteur après une connexion réussie."""
    try:
        await redis.delete(_login_attempts_key(phone_number))
        logger.debug("Compteur login réinitialisé pour %s", phone_number)
    except RedisError as e:
        logger.error("Erreur Redis (reset compteur login) : %s", e)
        raise
