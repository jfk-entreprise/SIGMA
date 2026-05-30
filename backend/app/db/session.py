"""
Moteur et fabrique de sessions SQLAlchemy asynchrones.

Usage dans les endpoints FastAPI :
    async def my_route(db: AsyncSession = Depends(get_db)):
        ...
"""
from typing import AsyncGenerator

from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine

from app.config import settings

_connect_args: dict = {}
if not settings.DATABASE_URL.startswith("sqlite"):
    _connect_args = {"server_settings": {"TimeZone": "UTC"}}

engine = create_async_engine(
    settings.DATABASE_URL,
    echo=settings.DEBUG,
    pool_pre_ping=True,
    pool_size=10,
    max_overflow=20,
    connect_args=_connect_args,
)

AsyncSessionLocal = async_sessionmaker(
    engine,
    class_=AsyncSession,
    expire_on_commit=False,
    autoflush=False,
)


async def get_db() -> AsyncGenerator[AsyncSession, None]:
    """
    Dépendance FastAPI : fournit une session de base de données par requête.
    Commit automatique en fin de requête ; rollback sur exception.
    """
    async with AsyncSessionLocal() as session:
        try:
            yield session
            await session.commit()
        except Exception:
            await session.rollback()
            raise
