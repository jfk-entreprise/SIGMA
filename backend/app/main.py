"""
Point d'entrée principal de l'API SIGMA.

Initialise l'application FastAPI avec :
- Gestion du cycle de vie (lifespan) : Redis + SQLAlchemy + seed catalogue
- Middleware CORS
- Enregistrement des routers
- Métadonnées OpenAPI (Swagger / ReDoc)
"""
import logging
import sys
from contextlib import asynccontextmanager
from typing import AsyncGenerator

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse

from app.config import settings
from app.core.redis_client import close_redis_pool, init_redis_pool
from app.routers import auth as auth_router
from app.routers import business as business_router
from app.routers import orders as orders_router
from app.routers import financials as financials_router
from app.routers import reports as reports_router

logging.basicConfig(
    level=logging.DEBUG if settings.DEBUG else logging.INFO,
    format="%(asctime)s | %(levelname)-8s | %(name)s | %(message)s",
    datefmt="%Y-%m-%dT%H:%M:%S",
    stream=sys.stdout,
)
logger = logging.getLogger(__name__)


# ---------------------------------------------------------------------------
# Lifespan : démarrage / arrêt
# ---------------------------------------------------------------------------


@asynccontextmanager
async def lifespan(_app: FastAPI) -> AsyncGenerator[None, None]:
    """
    Startup  : Redis + création tables DB (dev) + seed catalogue items.
    Shutdown : fermeture pool Redis.
    """
    logger.info("🚀 Démarrage de %s v%s", settings.APP_NAME, settings.APP_VERSION)

    # 1. Redis
    try:
        await init_redis_pool()
    except Exception as e:
        logger.critical("❌ Impossible de se connecter à Redis : %s", e)
        raise

    # 2. SQLAlchemy — création des tables (dev/staging uniquement)
    #    En production : utiliser `alembic upgrade head`
    if settings.ENVIRONMENT != "production":
        from app.db.base import Base
        from app.db.session import engine
        import app.models  # noqa: F401 — charge tous les modèles
        async with engine.begin() as conn:
            await conn.run_sync(Base.metadata.create_all)
        logger.info("✅ Tables DB synchronisées (ENVIRONMENT=%s).", settings.ENVIRONMENT)

    # 3. Seed du catalogue central des items (idempotent)
    from app.db.session import AsyncSessionLocal
    from app.services.business import seed_item_definitions
    async with AsyncSessionLocal() as seed_session:
        await seed_item_definitions(seed_session)

    logger.info("✅ Application prête.")
    yield

    # Shutdown
    logger.info("🛑 Arrêt de l'application…")
    await close_redis_pool()
    logger.info("👋 Application arrêtée proprement.")


# ---------------------------------------------------------------------------
# Application FastAPI
# ---------------------------------------------------------------------------

_TAGS_METADATA = [
    {
        "name": "Authentification",
        "description": (
            "Gestion de l'identité : OTP, inscription, connexion. "
            "Flux : **OTP Request → OTP Verify → Register → Login**."
        ),
    },
    {
        "name": "Commerces",
        "description": (
            "Gestion des commerces, des prestations et des membres. "
            "Requiert un Access Token valide (Bearer)."
        ),
    },
    {
        "name": "Commandes",
        "description": (
            "Création, consultation, annulation et paiement des commandes de service. "
            "Requiert un Access Token valide (Bearer)."
        ),
    },
    {
        "name": "Finances",
        "description": (
            "Dépenses opérationnelles et créances clients. "
            "Requiert un Access Token valide (Bearer)."
        ),
    },
    {
        "name": "Rapports",
        "description": (
            "Rapports journaliers consolidés, tableau de bord temps réel et "
            "synthèses hebdomadaires / mensuelles (abonnés PREMIUM+). "
            "Requiert un Access Token valide (Bearer)."
        ),
    },
    {
        "name": "Santé",
        "description": "Endpoints de surveillance de l'état de l'API.",
    },
]

app = FastAPI(
    title=settings.APP_NAME,
    version=settings.APP_VERSION,
    description=(
        "## API SIGMA\n\n"
        "Backend RESTful pour l'application mobile **SIGMA** — "
        "Système Intégré de Gestion et de Management Administratif.\n\n"
        "### Flux d'authentification\n"
        "```\n"
        "1. POST /auth/otp/request   → SMS avec code OTP\n"
        "2. POST /auth/otp/verify    → Valide l'OTP → registration_token\n"
        "3. POST /auth/register      → Crée le compte (Bearer <registration_token>)\n"
        "4. POST /auth/login         → access_token + refresh_token\n"
        "```\n\n"
        "### Flux de création de commerce\n"
        "```\n"
        "5. POST /businesses/        → Crée le commerce → items initialisés auto\n"
        "6. GET  /businesses/items   → Liste des prestations\n"
        "7. POST /businesses/managers → Ajoute un gérant\n"
        "```"
    ),
    openapi_tags=_TAGS_METADATA,
    docs_url="/docs",
    redoc_url="/redoc",
    openapi_url="/openapi.json",
    lifespan=lifespan,
)

# ---------------------------------------------------------------------------
# Middleware CORS
# ---------------------------------------------------------------------------

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"] if settings.DEBUG else [],
    allow_credentials=True,
    allow_methods=["GET", "POST", "PUT", "PATCH", "DELETE", "OPTIONS"],
    allow_headers=["*"],
)

# ---------------------------------------------------------------------------
# Routers
# ---------------------------------------------------------------------------

app.include_router(auth_router.router, prefix="/api/v1")
app.include_router(business_router.router, prefix="/api/v1")
app.include_router(orders_router.router, prefix="/api/v1")
app.include_router(financials_router.router, prefix="/api/v1")
app.include_router(reports_router.router, prefix="/api/v1")

# ---------------------------------------------------------------------------
# Endpoints de base
# ---------------------------------------------------------------------------


@app.get("/", tags=["Santé"], include_in_schema=False)
async def root() -> JSONResponse:
    return JSONResponse(
        content={
            "message": f"Bienvenue sur {settings.APP_NAME} v{settings.APP_VERSION}",
            "docs": "/docs",
            "health": "/health",
        }
    )


@app.get("/health", tags=["Santé"], summary="Vérification de santé de l'API")
async def health_check() -> JSONResponse:
    from app.core.redis_client import get_redis_pool

    redis_status = "unknown"
    try:
        redis = await get_redis_pool()
        await redis.ping()
        redis_status = "ok"
    except Exception as e:
        redis_status = f"error: {e}"

    overall = "ok" if redis_status == "ok" else "degraded"
    return JSONResponse(
        status_code=200 if overall == "ok" else 503,
        content={
            "status": overall,
            "version": settings.APP_VERSION,
            "services": {"redis": redis_status},
        },
    )
