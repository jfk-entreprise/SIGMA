"""
Configuration globale pytest pour SIGMA Backend.

Fixtures fournies :
- mock_redis_lifecycle  : empêche le lifespan de se connecter à un vrai Redis (session)
- fake_redis            : FakeRedis async + injection via dependency_overrides (function, autouse)
- db_environment        : SQLite in-memory, tables fraîches + override get_db (function, autouse)
- db_session            : AsyncSession directe pour le seeding dans les tests
"""
import pytest
import pytest_asyncio
from unittest.mock import AsyncMock, patch
import fakeredis.aioredis
from sqlalchemy.ext.asyncio import (
    AsyncSession,
    async_sessionmaker,
    create_async_engine,
)

import app.core.redis_client as rc_module
import app.models  # noqa: F401 — enregistre tous les modèles auprès de Base.metadata
from app.db.base import Base
from app.db.session import get_db
from app.main import app as fastapi_app

# ---------------------------------------------------------------------------
# Constante
# ---------------------------------------------------------------------------

TEST_DATABASE_URL = "sqlite+aiosqlite:///:memory:"


# ---------------------------------------------------------------------------
# Fixture session : empêche le lifespan de démarrer Redis
# ---------------------------------------------------------------------------


@pytest.fixture(autouse=True, scope="session")
def mock_redis_lifecycle():
    """Patch init/close Redis pour que le lifespan ne tente pas de connexion réelle."""
    with (
        patch("app.core.redis_client.init_redis_pool", new_callable=AsyncMock),
        patch("app.core.redis_client.close_redis_pool", new_callable=AsyncMock),
    ):
        yield


# ---------------------------------------------------------------------------
# Fixture session : moteur SQLite in-memory partagé
# ---------------------------------------------------------------------------


@pytest_asyncio.fixture(scope="session")
async def test_engine():
    """Moteur SQLite in-memory partagé sur toute la session de tests."""
    engine = create_async_engine(TEST_DATABASE_URL, echo=False)
    yield engine
    await engine.dispose()


# ---------------------------------------------------------------------------
# Fixture function (autouse) : tables fraîches + override get_db
# ---------------------------------------------------------------------------


@pytest_asyncio.fixture(autouse=True)
async def db_environment(test_engine):
    """
    Pour chaque test :
    1. Recrée toutes les tables (isolation totale).
    2. Seed le catalogue item_definitions.
    3. Injecte la fabrique de sessions via dependency_overrides[get_db].

    Retourne la fabrique de sessions pour les tests qui souhaitent insérer des données.
    """
    from app.services.business import seed_item_definitions

    # Réinitialisation des tables
    async with test_engine.begin() as conn:
        await conn.run_sync(Base.metadata.drop_all)
        await conn.run_sync(Base.metadata.create_all)

    # Fabrique de sessions pointant sur le SQLite de test
    TestSessionFactory = async_sessionmaker(
        test_engine,
        class_=AsyncSession,
        expire_on_commit=False,
        autoflush=False,
    )

    # Seed du catalogue (idempotent, rapide)
    async with TestSessionFactory() as seed_session:
        await seed_item_definitions(seed_session)

    # Override de la dépendance FastAPI
    async def _override_get_db():
        async with TestSessionFactory() as session:
            try:
                yield session
                await session.commit()
            except Exception:
                await session.rollback()
                raise

    fastapi_app.dependency_overrides[get_db] = _override_get_db
    yield TestSessionFactory
    del fastapi_app.dependency_overrides[get_db]


# ---------------------------------------------------------------------------
# Fixture function : session directe pour le seeding dans les tests
# ---------------------------------------------------------------------------


@pytest_asyncio.fixture
async def db_session(db_environment):
    """AsyncSession directe pour insérer des données de test en amont des requêtes HTTP."""
    TestSessionFactory = db_environment
    async with TestSessionFactory() as session:
        yield session
        await session.commit()


# ---------------------------------------------------------------------------
# Fixture function (autouse) : FakeRedis + override rc.get_redis
# ---------------------------------------------------------------------------


@pytest_asyncio.fixture(autouse=True)
async def fake_redis():
    """
    FakeRedis async isolé par test (decode_responses=True pour correspondre
    au comportement du pool Redis réel).

    Double injection :
    - dependency_overrides[get_redis] : pour les endpoints FastAPI (Depends)
    - rc_module._redis_pool           : pour get_redis_pool() appelé depuis les
      services (ex. generate_or_update_daily_report) sans passer par Depends.

    Chaque test part d'un état Redis vierge.
    """
    r = fakeredis.aioredis.FakeRedis(decode_responses=True)
    fastapi_app.dependency_overrides[rc_module.get_redis] = lambda: r
    rc_module._redis_pool = r
    yield r
    del fastapi_app.dependency_overrides[rc_module.get_redis]
    rc_module._redis_pool = None
    await r.aclose()


# ---------------------------------------------------------------------------
# Helpers de fixtures réutilisables (importables dans les modules de test)
# ---------------------------------------------------------------------------


def pytest_configure(config):
    """Enregistre les markers personnalisés."""
    config.addinivalue_line(
        "markers", "asyncio: mark test as async (handled by pytest-asyncio)"
    )
