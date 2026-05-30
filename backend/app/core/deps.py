"""
Dépendances FastAPI partagées — Authentification & Autorisation SIGMA.

Hiérarchie :
    get_current_user        → décode le JWT, charge l'utilisateur depuis la DB
    get_current_active_user → vérifie is_active
    get_current_owner       → vérifie le rôle OWNER sur son commerce
"""
import logging
import uuid

from fastapi import Depends, Header, HTTPException, status
from jose import JWTError
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.security import decode_token
from app.db.session import get_db
from app.models.business import Business, BusinessUser, UserRole
from app.models.user import User

logger = logging.getLogger(__name__)

_UNAUTHORIZED = HTTPException(
    status_code=status.HTTP_401_UNAUTHORIZED,
    detail="Session invalide ou expirée. Veuillez vous reconnecter.",
    headers={"WWW-Authenticate": "Bearer"},
)


# ---------------------------------------------------------------------------
# Résolution de l'utilisateur courant depuis le JWT
# ---------------------------------------------------------------------------


async def get_current_user(
    authorization: str = Header(
        ...,
        alias="Authorization",
        description="Token d'accès sous la forme : Bearer <access_token>",
    ),
    db: AsyncSession = Depends(get_db),
) -> User:
    """
    Décode le JWT d'accès, charge et retourne l'utilisateur depuis la DB.
    Lève 401 si le token est invalide, expiré, ou l'utilisateur inexistant.
    """
    if not authorization.startswith("Bearer "):
        raise _UNAUTHORIZED

    token = authorization.removeprefix("Bearer ").strip()

    try:
        payload = decode_token(token)
    except JWTError:
        raise _UNAUTHORIZED

    if payload.token_type != "access":
        raise _UNAUTHORIZED

    try:
        user_id = uuid.UUID(payload.sub)
    except (ValueError, AttributeError):
        raise _UNAUTHORIZED

    user = await db.get(User, user_id)
    if user is None or not user.is_active:
        raise _UNAUTHORIZED

    return user


# ---------------------------------------------------------------------------
# Résolution du commerce courant + rôle de l'utilisateur
# ---------------------------------------------------------------------------


async def get_current_business_user(
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
) -> tuple[Business, BusinessUser]:
    """
    Retourne le commerce actif de l'utilisateur ainsi que son appartenance (rôle).
    Lève 404 si l'utilisateur n'est associé à aucun commerce.
    """
    result = await db.execute(
        select(BusinessUser)
        .where(BusinessUser.user_id == current_user.id)
        .join(BusinessUser.business)
        .where(Business.is_active.is_(True))
        .order_by(BusinessUser.created_at)
        .limit(1)
    )
    membership = result.scalar_one_or_none()

    if membership is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Aucun commerce actif associé à ce compte.",
        )

    return membership.business, membership


# ---------------------------------------------------------------------------
# Garde OWNER (seul l'owner d'un commerce peut accéder)
# ---------------------------------------------------------------------------


async def require_owner(
    business_and_membership: tuple[Business, BusinessUser] = Depends(
        get_current_business_user
    ),
) -> tuple[Business, BusinessUser]:
    """
    Vérifie que l'utilisateur courant est l'OWNER du commerce.
    Lève 403 sinon.
    """
    business, membership = business_and_membership
    if membership.role != UserRole.OWNER:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Cette action est réservée au Propriétaire du commerce.",
        )
    return business, membership
