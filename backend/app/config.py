"""
Configuration centralisée via Pydantic Settings.
Charge les variables d'environnement depuis le fichier .env.
"""
from functools import lru_cache
from pydantic import model_validator
from pydantic_settings import BaseSettings, SettingsConfigDict

_DEFAULT_JWT_SECRET = "change-me-in-production-use-a-long-random-string"


class Settings(BaseSettings):
    model_config = SettingsConfigDict(
        env_file=".env",
        env_file_encoding="utf-8",
        case_sensitive=False,
        extra="ignore",
    )

    # Application
    APP_NAME: str = "SIGMA API"
    APP_VERSION: str = "1.0.0"
    DEBUG: bool = False
    ENVIRONMENT: str = "development"

    # Base de données PostgreSQL
    DATABASE_URL: str = "postgresql+asyncpg://sigma_user:sigma_pass@localhost:5432/sigma_db"

    # Redis
    REDIS_URL: str = "redis://localhost:6379/0"

    # JWT
    JWT_SECRET_KEY: str = _DEFAULT_JWT_SECRET
    JWT_ALGORITHM: str = "HS256"
    ACCESS_TOKEN_EXPIRE_MINUTES: int = 30
    REFRESH_TOKEN_EXPIRE_DAYS: int = 7

    # OTP
    OTP_EXPIRE_SECONDS: int = 300  # 5 minutes
    OTP_LENGTH: int = 6

    # Token temporaire d'inscription (après vérification OTP)
    REGISTRATION_TOKEN_EXPIRE_MINUTES: int = 15

    @model_validator(mode="after")
    def validate_production_secrets(self) -> "Settings":
        """Bloque le démarrage en production si JWT_SECRET_KEY est la valeur par défaut."""
        if self.ENVIRONMENT == "production" and self.JWT_SECRET_KEY == _DEFAULT_JWT_SECRET:
            raise ValueError(
                "JWT_SECRET_KEY doit être changée depuis sa valeur par défaut "
                "avant tout déploiement en production. "
                "Définissez JWT_SECRET_KEY dans votre fichier .env ou variable d'environnement."
            )
        return self


@lru_cache
def get_settings() -> Settings:
    """Retourne une instance singleton des settings (mise en cache)."""
    return Settings()


settings = get_settings()
