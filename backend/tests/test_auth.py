"""
Tests d'intégration — Module d'authentification SIGMA.

Stack de test :
- httpx ASGI transport (pas de serveur réel)
- fakeredis (TTL + atomicité INCR réels, in-memory)
- SQLite in-memory via aiosqlite (via conftest.db_environment autouse)

Lancer avec :
    cd backend
    pytest tests/test_auth.py -v --tb=short
"""
import uuid

import pytest
import pytest_asyncio
from httpx import ASGITransport, AsyncClient
from unittest.mock import AsyncMock, patch

from app.main import app


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------


@pytest_asyncio.fixture
async def client():
    """Client HTTP lié à l'app SIGMA via ASGI transport."""
    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as c:
        yield c


@pytest_asyncio.fixture
async def seeded_user(db_session):
    """
    Insère un utilisateur actif en base SQLite pour les tests de login.
    Retourne un dict avec les données brutes (mot de passe en clair conservé pour les assertions).
    """
    from app.core.security import hash_password
    from app.models.user import User

    user = User(
        id=uuid.uuid4(),
        phone_number="+22370000099",
        full_name="Test User",
        hashed_password=hash_password("Str0ngPass!"),
        is_active=True,
    )
    db_session.add(user)
    await db_session.flush()

    return {
        "id": user.id,
        "phone_number": user.phone_number,
        "full_name": user.full_name,
        "plain_password": "Str0ngPass!",
        "is_active": user.is_active,
    }


@pytest_asyncio.fixture
async def inactive_user(db_session):
    """Insère un utilisateur inactif en base SQLite."""
    from app.core.security import hash_password
    from app.models.user import User

    user = User(
        id=uuid.uuid4(),
        phone_number="+22370000098",
        full_name="Inactive User",
        hashed_password=hash_password("Str0ngPass!"),
        is_active=False,
    )
    db_session.add(user)
    await db_session.flush()
    return user


# ---------------------------------------------------------------------------
# Tests : POST /api/v1/auth/otp/request
# ---------------------------------------------------------------------------


class TestOTPRequest:
    """Tests pour l'endpoint de demande d'OTP."""

    @pytest.mark.asyncio
    async def test_otp_request_valid_phone(self, client, fake_redis):
        """Un numéro valide doit recevoir une réponse 200 avec les métadonnées OTP."""
        response = await client.post(
            "/api/v1/auth/otp/request",
            json={"phone_number": "+22370000000"},
        )
        assert response.status_code == 200
        data = response.json()
        assert "message" in data
        assert data["phone_number"] == "+22370000000"
        assert data["expires_in_seconds"] == 300

    @pytest.mark.asyncio
    async def test_otp_request_cooldown(self, client, fake_redis):
        """Si le cooldown est actif, l'endpoint doit retourner 429."""
        await fake_redis.set("sigma:otp_cooldown:+22370000000", "1", ex=60)
        response = await client.post(
            "/api/v1/auth/otp/request",
            json={"phone_number": "+22370000000"},
        )
        assert response.status_code == 429
        assert "trop rapprochées" in response.json()["detail"].lower()

    @pytest.mark.asyncio
    async def test_otp_request_redis_error(self, client, fake_redis):
        """En cas de panne Redis, l'endpoint doit renvoyer 503."""
        from redis.exceptions import RedisError
        fake_redis.exists = AsyncMock(side_effect=RedisError("Connection lost"))
        response = await client.post(
            "/api/v1/auth/otp/request",
            json={"phone_number": "+22370000000"},
        )
        assert response.status_code == 503
        assert "temporairement indisponible" in response.json()["detail"].lower()

    @pytest.mark.asyncio
    async def test_otp_request_invalid_phone(self, client):
        response = await client.post(
            "/api/v1/auth/otp/request",
            json={"phone_number": "not-a-phone"},
        )
        assert response.status_code == 422

    @pytest.mark.asyncio
    async def test_otp_request_short_phone(self, client):
        response = await client.post(
            "/api/v1/auth/otp/request",
            json={"phone_number": "+123"},
        )
        assert response.status_code == 422

    @pytest.mark.asyncio
    async def test_otp_request_missing_body(self, client):
        response = await client.post("/api/v1/auth/otp/request", json={})
        assert response.status_code == 422


# ---------------------------------------------------------------------------
# Tests : POST /api/v1/auth/otp/verify
# ---------------------------------------------------------------------------


class TestOTPVerify:
    """Tests pour l'endpoint de vérification d'OTP."""

    @pytest.mark.asyncio
    async def test_otp_verify_success(self, client, fake_redis):
        """Un OTP valide doit retourner un registration_token."""
        await fake_redis.set("sigma:otp:+22370000000", "123456", ex=300)
        response = await client.post(
            "/api/v1/auth/otp/verify",
            json={"phone_number": "+22370000000", "otp_code": "123456"},
        )
        assert response.status_code == 200
        data = response.json()
        assert "registration_token" in data
        assert data["token_type"] == "bearer"

    @pytest.mark.asyncio
    async def test_otp_verify_wrong_code(self, client, fake_redis):
        await fake_redis.set("sigma:otp:+22370000000", "654321", ex=300)
        response = await client.post(
            "/api/v1/auth/otp/verify",
            json={"phone_number": "+22370000000", "otp_code": "000000"},
        )
        assert response.status_code == 400
        assert "incorrect" in response.json()["detail"].lower()

    @pytest.mark.asyncio
    async def test_otp_verify_expired(self, client, fake_redis):
        """OTP absent de Redis → 400."""
        response = await client.post(
            "/api/v1/auth/otp/verify",
            json={"phone_number": "+22370000000", "otp_code": "123456"},
        )
        assert response.status_code == 400

    @pytest.mark.asyncio
    async def test_otp_verify_too_many_attempts(self, client, fake_redis):
        """Après MAX_OTP_ATTEMPTS, le blocage doit renvoyer 429."""
        await fake_redis.set("sigma:otp_attempts:+22370000000", "5", ex=300)
        response = await client.post(
            "/api/v1/auth/otp/verify",
            json={"phone_number": "+22370000000", "otp_code": "000000"},
        )
        assert response.status_code == 429
        assert "trop de tentatives" in response.json()["detail"].lower()

    @pytest.mark.asyncio
    async def test_otp_verify_redis_error(self, client, fake_redis):
        from redis.exceptions import RedisError
        fake_redis.incr = AsyncMock(side_effect=RedisError("Redis disconnected"))
        response = await client.post(
            "/api/v1/auth/otp/verify",
            json={"phone_number": "+22370000000", "otp_code": "123456"},
        )
        assert response.status_code == 503
        assert "temporairement indisponible" in response.json()["detail"].lower()

    @pytest.mark.asyncio
    async def test_otp_verify_invalid_format(self, client):
        response = await client.post(
            "/api/v1/auth/otp/verify",
            json={"phone_number": "+22370000000", "otp_code": "ABC"},
        )
        assert response.status_code == 422


# ---------------------------------------------------------------------------
# Tests : POST /api/v1/auth/register
# ---------------------------------------------------------------------------


class TestRegister:
    """Tests pour l'endpoint d'inscription."""

    def _make_registration_token(self, phone: str = "+22370000000") -> str:
        from app.core.security import create_registration_token
        return create_registration_token(phone_number=phone)

    @pytest.mark.asyncio
    async def test_register_success(self, client, fake_redis):
        """Une inscription valide doit créer l'utilisateur et retourner 201."""
        token = self._make_registration_token("+22370000001")
        await fake_redis.set(f"sigma:reg_token:{token}", "+22370000001", ex=900)

        response = await client.post(
            "/api/v1/auth/register",
            headers={"Authorization": f"Bearer {token}"},
            json={
                "phone_number": "+22370000001",
                "full_name": "Amadou Diallo",
                "email": "amadou@example.com",
                "password": "Str0ngPass!",
                "confirm_password": "Str0ngPass!",
            },
        )
        assert response.status_code == 201
        data = response.json()
        assert data["phone_number"] == "+22370000001"
        assert data["full_name"] == "Amadou Diallo"
        assert "id" in data
        assert "hashed_password" not in data

    @pytest.mark.asyncio
    async def test_register_duplicate_phone(self, client, fake_redis, seeded_user):
        """Réinscription avec un numéro déjà existant → 409."""
        phone = seeded_user["phone_number"]
        token = self._make_registration_token(phone)
        await fake_redis.set(f"sigma:reg_token:{token}", phone, ex=900)

        response = await client.post(
            "/api/v1/auth/register",
            headers={"Authorization": f"Bearer {token}"},
            json={
                "phone_number": phone,
                "full_name": "Autre",
                "password": "Str0ngPass!",
                "confirm_password": "Str0ngPass!",
            },
        )
        assert response.status_code == 409

    @pytest.mark.asyncio
    async def test_register_missing_auth_header(self, client):
        response = await client.post(
            "/api/v1/auth/register",
            json={
                "phone_number": "+22370000000",
                "full_name": "Test",
                "password": "Str0ngPass!",
                "confirm_password": "Str0ngPass!",
            },
        )
        assert response.status_code == 422

    @pytest.mark.asyncio
    async def test_register_invalid_token(self, client):
        response = await client.post(
            "/api/v1/auth/register",
            headers={"Authorization": "Bearer invalid.token.here"},
            json={
                "phone_number": "+22370000000",
                "full_name": "Test User",
                "password": "Str0ngPass!",
                "confirm_password": "Str0ngPass!",
            },
        )
        assert response.status_code == 401

    @pytest.mark.asyncio
    async def test_register_password_mismatch(self, client):
        token = self._make_registration_token("+22370000002")
        response = await client.post(
            "/api/v1/auth/register",
            headers={"Authorization": f"Bearer {token}"},
            json={
                "phone_number": "+22370000002",
                "full_name": "Test",
                "password": "Str0ngPass!",
                "confirm_password": "Different1!",
            },
        )
        assert response.status_code == 422

    @pytest.mark.asyncio
    async def test_register_weak_password(self, client):
        token = self._make_registration_token("+22370000003")
        response = await client.post(
            "/api/v1/auth/register",
            headers={"Authorization": f"Bearer {token}"},
            json={
                "phone_number": "+22370000003",
                "full_name": "Test",
                "password": "weak",
                "confirm_password": "weak",
            },
        )
        assert response.status_code == 422

    @pytest.mark.asyncio
    async def test_register_too_long_password(self, client):
        """Mot de passe > 72 chars → 422 (protection DoS bcrypt)."""
        token = self._make_registration_token("+22370000004")
        long_pass = "A" * 73
        response = await client.post(
            "/api/v1/auth/register",
            headers={"Authorization": f"Bearer {token}"},
            json={
                "phone_number": "+22370000004",
                "full_name": "Test",
                "password": long_pass,
                "confirm_password": long_pass,
            },
        )
        assert response.status_code == 422

    @pytest.mark.asyncio
    async def test_register_redis_error(self, client, fake_redis):
        """Panne Redis lors de la validation du token → 503."""
        from redis.exceptions import RedisError
        token = self._make_registration_token("+22370000005")
        fake_redis.get = AsyncMock(side_effect=RedisError("Redis dead"))
        response = await client.post(
            "/api/v1/auth/register",
            headers={"Authorization": f"Bearer {token}"},
            json={
                "phone_number": "+22370000005",
                "full_name": "Test",
                "password": "Str0ngPass!",
                "confirm_password": "Str0ngPass!",
            },
        )
        assert response.status_code == 503
        assert "temporairement indisponible" in response.json()["detail"].lower()


# ---------------------------------------------------------------------------
# Tests : POST /api/v1/auth/login
# ---------------------------------------------------------------------------


class TestLogin:
    """Tests pour l'endpoint de connexion — utilisateurs en base SQLite réelle."""

    @pytest.mark.asyncio
    async def test_login_success(self, client, seeded_user):
        """Identifiants valides → 200 avec access_token + refresh_token."""
        response = await client.post(
            "/api/v1/auth/login",
            json={
                "phone_number": seeded_user["phone_number"],
                "password": seeded_user["plain_password"],
            },
        )
        assert response.status_code == 200
        data = response.json()
        assert "access_token" in data
        assert "refresh_token" in data
        assert data["token_type"] == "bearer"
        assert data["expires_in"] == 30 * 60

    @pytest.mark.asyncio
    async def test_login_wrong_password(self, client, seeded_user):
        """Mauvais mot de passe → 401."""
        response = await client.post(
            "/api/v1/auth/login",
            json={
                "phone_number": seeded_user["phone_number"],
                "password": "WrongPass99",
            },
        )
        assert response.status_code == 401
        assert "incorrect" in response.json()["detail"].lower()

    @pytest.mark.asyncio
    async def test_login_unknown_phone(self, client):
        """Numéro inexistant → 401 avec même message (anti-énumération)."""
        response = await client.post(
            "/api/v1/auth/login",
            json={"phone_number": "+22300000000", "password": "AnyPass1!"},
        )
        assert response.status_code == 401
        assert "incorrect" in response.json()["detail"].lower()

    @pytest.mark.asyncio
    async def test_login_inactive_account(self, client, inactive_user):
        """Compte désactivé → 401 avec message générique (anti-énumération)."""
        response = await client.post(
            "/api/v1/auth/login",
            json={
                "phone_number": inactive_user.phone_number,
                "password": "Str0ngPass!",
            },
        )
        assert response.status_code == 401
        assert "incorrect" in response.json()["detail"].lower()

    @pytest.mark.asyncio
    async def test_login_too_many_attempts(self, client, fake_redis):
        """Après MAX_LOGIN_ATTEMPTS → 429."""
        await fake_redis.set("sigma:login_limit:+22370000099", "5", ex=900)
        response = await client.post(
            "/api/v1/auth/login",
            json={"phone_number": "+22370000099", "password": "AnyPass1!"},
        )
        assert response.status_code == 429
        assert "trop de tentatives" in response.json()["detail"].lower()

    @pytest.mark.asyncio
    async def test_login_rate_limit_resets_on_success(self, client, fake_redis, seeded_user):
        """Connexion réussie → compteur Redis supprimé."""
        phone = seeded_user["phone_number"]
        await fake_redis.set(f"sigma:login_limit:{phone}", "3", ex=900)

        response = await client.post(
            "/api/v1/auth/login",
            json={"phone_number": phone, "password": seeded_user["plain_password"]},
        )
        assert response.status_code == 200
        counter = await fake_redis.get(f"sigma:login_limit:{phone}")
        assert counter is None

    @pytest.mark.asyncio
    async def test_login_rate_limit_redis_error_fail_open(self, client, fake_redis, seeded_user):
        """Panne Redis sur le rate limiting → connexion toujours possible (fail-open)."""
        from redis.exceptions import RedisError
        fake_redis.incr = AsyncMock(side_effect=RedisError("Redis KO"))

        response = await client.post(
            "/api/v1/auth/login",
            json={
                "phone_number": seeded_user["phone_number"],
                "password": seeded_user["plain_password"],
            },
        )
        assert response.status_code == 200

    @pytest.mark.asyncio
    async def test_login_invalid_phone_format(self, client):
        response = await client.post(
            "/api/v1/auth/login",
            json={"phone_number": "invalid", "password": "Str0ngPass!"},
        )
        assert response.status_code == 422

    @pytest.mark.asyncio
    async def test_login_too_long_password(self, client):
        """Mot de passe > 72 chars → 422 (protection DoS bcrypt)."""
        response = await client.post(
            "/api/v1/auth/login",
            json={"phone_number": "+22370000099", "password": "A" * 73},
        )
        assert response.status_code == 422


# ---------------------------------------------------------------------------
# Tests : Utilitaires de sécurité
# ---------------------------------------------------------------------------


class TestSecurity:
    """Tests unitaires pour les primitives cryptographiques."""

    def test_hash_and_verify_password(self):
        from app.core.security import hash_password, verify_password
        plain = "MySecurePass1!"
        hashed = hash_password(plain)
        assert hashed != plain
        assert verify_password(plain, hashed) is True
        assert verify_password("WrongPass", hashed) is False

    def test_generate_otp_length(self):
        from app.core.security import generate_otp
        otp = generate_otp(6)
        assert len(otp) == 6 and otp.isdigit()

    def test_generate_otp_is_numeric(self):
        from app.core.security import generate_otp
        for _ in range(20):
            assert generate_otp(6).isdigit()

    def test_create_and_decode_access_token(self):
        from app.core.security import create_access_token, decode_token
        token = create_access_token(user_id="user-123", phone_number="+22370000000")
        payload = decode_token(token)
        assert payload.sub == "user-123"
        assert payload.phone_number == "+22370000000"
        assert payload.token_type == "access"

    def test_create_and_decode_refresh_token(self):
        from app.core.security import create_refresh_token, decode_token
        token = create_refresh_token(user_id="user-456")
        payload = decode_token(token)
        assert payload.sub == "user-456"
        assert payload.token_type == "refresh"

    def test_create_and_decode_registration_token(self):
        from app.core.security import create_registration_token, decode_token
        token = create_registration_token(phone_number="+22370000000")
        payload = decode_token(token)
        assert payload.token_type == "registration"
        assert payload.phone_number == "+22370000000"

    def test_decode_invalid_token_raises(self):
        from app.core.security import decode_token
        from jose import JWTError
        with pytest.raises(JWTError):
            decode_token("this.is.not.a.valid.jwt")


# ---------------------------------------------------------------------------
# Tests : Validateur de configuration (REC-03)
# ---------------------------------------------------------------------------


class TestConfig:
    """Tests pour le validateur de sécurité de la configuration."""

    def test_jwt_secret_key_default_blocked_in_production(self):
        """Démarrage bloqué si JWT_SECRET_KEY est la valeur par défaut en production."""
        import os
        from unittest.mock import patch
        from pydantic import ValidationError
        from app.config import Settings

        with patch.dict(os.environ, {
            "ENVIRONMENT": "production",
            "JWT_SECRET_KEY": "change-me-in-production-use-a-long-random-string",
        }):
            with pytest.raises(ValidationError, match="JWT_SECRET_KEY"):
                Settings(_env_file=None)

    def test_jwt_secret_key_default_allowed_in_development(self):
        """Valeur par défaut autorisée en development."""
        import os
        from unittest.mock import patch
        from app.config import Settings

        with patch.dict(os.environ, {
            "ENVIRONMENT": "development",
            "JWT_SECRET_KEY": "change-me-in-production-use-a-long-random-string",
        }):
            s = Settings(_env_file=None)
            assert s.ENVIRONMENT == "development"

    def test_jwt_secret_key_custom_value_allowed_in_production(self):
        """Clé JWT personnalisée autorisée en production."""
        import os
        from unittest.mock import patch
        from app.config import Settings

        with patch.dict(os.environ, {
            "ENVIRONMENT": "production",
            "JWT_SECRET_KEY": "super-secret-production-key-64chars-minimum-for-hs256!!",
        }):
            s = Settings(_env_file=None)
            assert s.ENVIRONMENT == "production"
