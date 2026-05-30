"""
Tests d'intégration — Module Business SIGMA (Étape 1.3).

Couvre :
- Création de commerce + copie automatique des items (seed WASH)
- GET /my, GET /items
- PATCH /items/{item_id} (Owner only)
- POST /managers (Owner only)
- Isolation multi-tenant
- Cas d'erreur (droits, doublons, types invalides)

Utilise SQLite in-memory + FakeRedis (via conftest autouse).
"""
import uuid

import pytest
import pytest_asyncio
from httpx import ASGITransport, AsyncClient

from app.main import app


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------


@pytest_asyncio.fixture
async def client():
    """Client HTTP ASGI sans serveur réel."""
    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as c:
        yield c


@pytest_asyncio.fixture
async def owner_user(db_session):
    """Crée un propriétaire en base et retourne ses données + token JWT."""
    from app.core.security import create_access_token, hash_password
    from app.models.user import User

    user = User(
        id=uuid.uuid4(),
        phone_number="+22370000010",
        full_name="Seydou Keïta",
        hashed_password=hash_password("Str0ngPass!"),
        is_active=True,
    )
    db_session.add(user)
    await db_session.flush()

    token = create_access_token(user_id=str(user.id), phone_number=user.phone_number)
    return {
        "id": user.id,
        "phone_number": user.phone_number,
        "token": token,
        "headers": {"Authorization": f"Bearer {token}"},
    }


@pytest_asyncio.fixture
async def manager_user(db_session):
    """Crée un utilisateur distinct qui sera ajouté comme gérant."""
    from app.core.security import hash_password
    from app.models.user import User

    user = User(
        id=uuid.uuid4(),
        phone_number="+22370000011",
        full_name="Ibrahim Touré",
        hashed_password=hash_password("Str0ngPass!"),
        is_active=True,
    )
    db_session.add(user)
    await db_session.flush()
    return user


@pytest_asyncio.fixture
async def created_business(client, owner_user):
    """Crée un commerce WASH via l'API et retourne la réponse JSON."""
    response = await client.post(
        "/api/v1/businesses/",
        headers=owner_user["headers"],
        json={
            "name": "Lavage Express Bamako",
            "business_type": "WASH",
            "phone": "+22370000010",
            "location": "Quartier du Fleuve",
        },
    )
    assert response.status_code == 201, response.text
    return response.json()


# ---------------------------------------------------------------------------
# Tests : POST /api/v1/businesses/ — Création de commerce
# ---------------------------------------------------------------------------


class TestCreateBusiness:
    """Tests de création de commerce et d'initialisation automatique des items."""

    @pytest.mark.asyncio
    async def test_create_wash_business_success(self, client, owner_user):
        """Création d'un commerce WASH → 201 avec toutes les métadonnées."""
        response = await client.post(
            "/api/v1/businesses/",
            headers=owner_user["headers"],
            json={
                "name": "Lavage Express Bamako",
                "business_type": "WASH",
                "phone": "+22370000010",
                "location": "Quartier du Fleuve, Bamako",
            },
        )
        assert response.status_code == 201
        data = response.json()
        assert data["name"] == "Lavage Express Bamako"
        assert data["business_type"] == "WASH"
        assert data["is_active"] is True
        assert str(data["owner_id"]) == str(owner_user["id"])

    @pytest.mark.asyncio
    async def test_create_business_items_auto_initialized(self, client, owner_user):
        """
        Après création d'un commerce WASH, les items du catalogue doivent être
        automatiquement copiés en business_items.
        Le catalogue WASH contient 13 items (5 véhicules + 4 types de lavage + 4 add-ons).
        """
        await client.post(
            "/api/v1/businesses/",
            headers=owner_user["headers"],
            json={"name": "Test Wash", "business_type": "WASH"},
        )
        response = await client.get(
            "/api/v1/businesses/items",
            headers=owner_user["headers"],
        )
        assert response.status_code == 200
        items = response.json()
        assert len(items) == 13, f"Attendu 13 items, obtenu {len(items)}"

    @pytest.mark.asyncio
    async def test_create_business_items_inherit_default_prices(self, client, owner_user):
        """Les business_items créés doivent hériter des prix par défaut du catalogue."""
        await client.post(
            "/api/v1/businesses/",
            headers=owner_user["headers"],
            json={"name": "Test Wash", "business_type": "WASH"},
        )
        items_resp = await client.get(
            "/api/v1/businesses/items",
            headers=owner_user["headers"],
        )
        items = items_resp.json()
        # Le 4x4 doit avoir custom_price = 4000 (valeur du catalogue)
        suv = next((i for i in items if i["custom_name"] == "4x4"), None)
        assert suv is not None
        assert suv["custom_price"] == 4000

    @pytest.mark.asyncio
    async def test_create_business_items_all_active(self, client, owner_user):
        """Tous les items initialisés doivent être actifs par défaut."""
        await client.post(
            "/api/v1/businesses/",
            headers=owner_user["headers"],
            json={"name": "Test Wash", "business_type": "WASH"},
        )
        items_resp = await client.get(
            "/api/v1/businesses/items",
            headers=owner_user["headers"],
        )
        items = items_resp.json()
        assert all(item["is_active"] for item in items)

    @pytest.mark.asyncio
    async def test_create_business_duplicate_owner(self, client, owner_user, created_business):
        """Un owner ne peut pas créer un second commerce actif → 409."""
        response = await client.post(
            "/api/v1/businesses/",
            headers=owner_user["headers"],
            json={"name": "Deuxième Commerce", "business_type": "WASH"},
        )
        assert response.status_code == 409

    @pytest.mark.asyncio
    async def test_create_business_invalid_type(self, client, owner_user):
        """Type de commerce invalide → 422."""
        response = await client.post(
            "/api/v1/businesses/",
            headers=owner_user["headers"],
            json={"name": "Test", "business_type": "INVALID_TYPE"},
        )
        assert response.status_code == 422

    @pytest.mark.asyncio
    async def test_create_business_unauthenticated(self, client):
        """Sans token → 422 (header Authorization manquant)."""
        response = await client.post(
            "/api/v1/businesses/",
            json={"name": "Test", "business_type": "WASH"},
        )
        assert response.status_code == 422

    @pytest.mark.asyncio
    async def test_create_business_expired_token(self, client):
        """Token JWT expiré → 401."""
        response = await client.post(
            "/api/v1/businesses/",
            headers={"Authorization": "Bearer invalid.jwt.token"},
            json={"name": "Test", "business_type": "WASH"},
        )
        assert response.status_code == 401


# ---------------------------------------------------------------------------
# Tests : GET /api/v1/businesses/my
# ---------------------------------------------------------------------------


class TestGetMyBusiness:
    """Tests pour la récupération du commerce de l'utilisateur connecté."""

    @pytest.mark.asyncio
    async def test_get_my_business_success(self, client, owner_user, created_business):
        """L'owner doit pouvoir récupérer son commerce."""
        response = await client.get(
            "/api/v1/businesses/my",
            headers=owner_user["headers"],
        )
        assert response.status_code == 200
        data = response.json()
        assert data["id"] == created_business["id"]
        assert data["name"] == created_business["name"]

    @pytest.mark.asyncio
    async def test_get_my_business_no_business(self, client, owner_user):
        """Utilisateur sans commerce → 404."""
        response = await client.get(
            "/api/v1/businesses/my",
            headers=owner_user["headers"],
        )
        assert response.status_code == 404


# ---------------------------------------------------------------------------
# Tests : PATCH /api/v1/businesses/items/{item_id}
# ---------------------------------------------------------------------------


class TestUpdateBusinessItem:
    """Tests pour la modification des prestations (Owner uniquement)."""

    @pytest.mark.asyncio
    async def test_update_item_price(self, client, owner_user, created_business):
        """L'owner doit pouvoir modifier le prix d'un item."""
        # Récupérer un item
        items_resp = await client.get(
            "/api/v1/businesses/items",
            headers=owner_user["headers"],
        )
        item = items_resp.json()[0]
        item_id = item["id"]

        response = await client.patch(
            f"/api/v1/businesses/items/{item_id}",
            headers=owner_user["headers"],
            json={"custom_price": 9999},
        )
        assert response.status_code == 200
        assert response.json()["custom_price"] == 9999

    @pytest.mark.asyncio
    async def test_update_item_deactivate(self, client, owner_user, created_business):
        """L'owner doit pouvoir désactiver un item."""
        items_resp = await client.get(
            "/api/v1/businesses/items",
            headers=owner_user["headers"],
        )
        item_id = items_resp.json()[0]["id"]

        response = await client.patch(
            f"/api/v1/businesses/items/{item_id}",
            headers=owner_user["headers"],
            json={"is_active": False},
        )
        assert response.status_code == 200
        assert response.json()["is_active"] is False

    @pytest.mark.asyncio
    async def test_update_item_custom_name(self, client, owner_user, created_business):
        """L'owner peut renommer une prestation."""
        items_resp = await client.get(
            "/api/v1/businesses/items",
            headers=owner_user["headers"],
        )
        item_id = items_resp.json()[0]["id"]

        response = await client.patch(
            f"/api/v1/businesses/items/{item_id}",
            headers=owner_user["headers"],
            json={"custom_name": "Gros 4x4"},
        )
        assert response.status_code == 200
        assert response.json()["custom_name"] == "Gros 4x4"

    @pytest.mark.asyncio
    async def test_update_item_wrong_business(self, client, owner_user, created_business):
        """Tenter de modifier un item avec un UUID inexistant → 404."""
        fake_id = str(uuid.uuid4())
        response = await client.patch(
            f"/api/v1/businesses/items/{fake_id}",
            headers=owner_user["headers"],
            json={"custom_price": 1000},
        )
        assert response.status_code == 404

    @pytest.mark.asyncio
    async def test_update_item_empty_body(self, client, owner_user, created_business):
        """Body vide (aucun champ) → 422."""
        items_resp = await client.get(
            "/api/v1/businesses/items",
            headers=owner_user["headers"],
        )
        item_id = items_resp.json()[0]["id"]

        response = await client.patch(
            f"/api/v1/businesses/items/{item_id}",
            headers=owner_user["headers"],
            json={},
        )
        assert response.status_code == 422

    @pytest.mark.asyncio
    async def test_update_item_manager_forbidden(self, client, owner_user, created_business, db_session):
        """Un Manager ne doit pas pouvoir modifier les prix → 403."""
        from app.core.security import create_access_token, hash_password
        from app.models.business import BusinessUser, UserRole
        from app.models.user import User

        # Créer le manager et l'associer au commerce
        manager = User(
            id=uuid.uuid4(),
            phone_number="+22370000020",
            full_name="Manager Test",
            hashed_password=hash_password("Str0ngPass!"),
            is_active=True,
        )
        db_session.add(manager)
        await db_session.flush()

        biz_id = uuid.UUID(created_business["id"])
        membership = BusinessUser(
            id=uuid.uuid4(),
            business_id=biz_id,
            user_id=manager.id,
            role=UserRole.MANAGER,
        )
        db_session.add(membership)
        await db_session.flush()

        manager_token = create_access_token(
            user_id=str(manager.id), phone_number=manager.phone_number
        )
        manager_headers = {"Authorization": f"Bearer {manager_token}"}

        items_resp = await client.get(
            "/api/v1/businesses/items",
            headers=manager_headers,
        )
        item_id = items_resp.json()[0]["id"]

        response = await client.patch(
            f"/api/v1/businesses/items/{item_id}",
            headers=manager_headers,
            json={"custom_price": 1},
        )
        assert response.status_code == 403


# ---------------------------------------------------------------------------
# Tests : POST /api/v1/businesses/managers
# ---------------------------------------------------------------------------


class TestAddManager:
    """Tests pour l'ajout d'un gérant par l'owner."""

    @pytest.mark.asyncio
    async def test_add_manager_success(self, client, owner_user, created_business):
        """L'owner peut ajouter un nouveau gérant → 201."""
        response = await client.post(
            "/api/v1/businesses/managers",
            headers=owner_user["headers"],
            json={
                "full_name": "Ibrahim Touré",
                "phone_number": "+22370000030",
                "password": "ManagerPass1!",
            },
        )
        assert response.status_code == 201
        data = response.json()
        assert data["role"] == "MANAGER"
        assert data["phone_number"] == "+22370000030"
        assert data["full_name"] == "Ibrahim Touré"

    @pytest.mark.asyncio
    async def test_add_manager_existing_user_reused(self, client, owner_user, created_business, manager_user):
        """Si le numéro correspond à un compte existant, le compte est réutilisé."""
        response = await client.post(
            "/api/v1/businesses/managers",
            headers=owner_user["headers"],
            json={
                "full_name": manager_user.full_name,
                "phone_number": manager_user.phone_number,
                "password": "ManagerPass1!",
            },
        )
        assert response.status_code == 201
        assert response.json()["user_id"] == str(manager_user.id)

    @pytest.mark.asyncio
    async def test_add_manager_duplicate(self, client, owner_user, created_business):
        """Ajouter deux fois le même gérant → 409."""
        payload = {
            "full_name": "Duplicate Manager",
            "phone_number": "+22370000031",
            "password": "ManagerPass1!",
        }
        await client.post(
            "/api/v1/businesses/managers",
            headers=owner_user["headers"],
            json=payload,
        )
        response = await client.post(
            "/api/v1/businesses/managers",
            headers=owner_user["headers"],
            json=payload,
        )
        assert response.status_code == 409

    @pytest.mark.asyncio
    async def test_add_manager_non_owner_forbidden(self, client, owner_user, created_business, db_session):
        """Un Manager ne peut pas ajouter d'autres managers → 403."""
        from app.core.security import create_access_token, hash_password
        from app.models.business import BusinessUser, UserRole
        from app.models.user import User

        mgr = User(
            id=uuid.uuid4(),
            phone_number="+22370000040",
            full_name="Mgr",
            hashed_password=hash_password("Str0ngPass!"),
            is_active=True,
        )
        db_session.add(mgr)
        await db_session.flush()

        db_session.add(BusinessUser(
            id=uuid.uuid4(),
            business_id=uuid.UUID(created_business["id"]),
            user_id=mgr.id,
            role=UserRole.MANAGER,
        ))
        await db_session.flush()

        mgr_headers = {"Authorization": f"Bearer {create_access_token(str(mgr.id), mgr.phone_number)}"}

        response = await client.post(
            "/api/v1/businesses/managers",
            headers=mgr_headers,
            json={
                "full_name": "Autre",
                "phone_number": "+22370000041",
                "password": "ManagerPass1!",
            },
        )
        assert response.status_code == 403

    @pytest.mark.asyncio
    async def test_add_manager_weak_password(self, client, owner_user, created_business):
        """Mot de passe faible pour le manager → 422."""
        response = await client.post(
            "/api/v1/businesses/managers",
            headers=owner_user["headers"],
            json={
                "full_name": "Manager",
                "phone_number": "+22370000050",
                "password": "weak",
            },
        )
        assert response.status_code == 422


# ---------------------------------------------------------------------------
# Tests : Isolation multi-tenant
# ---------------------------------------------------------------------------


class TestMultiTenantIsolation:
    """Vérifie que les données d'un commerce ne sont pas accessibles par un autre."""

    @pytest.mark.asyncio
    async def test_two_owners_see_only_own_business(self, client, db_session):
        """Deux owners créent chacun leur commerce — ils voient uniquement le leur."""
        from app.core.security import create_access_token, hash_password
        from app.models.user import User

        # Owner A
        user_a = User(
            id=uuid.uuid4(),
            phone_number="+22370000060",
            full_name="Owner A",
            hashed_password=hash_password("Str0ngPass!"),
            is_active=True,
        )
        # Owner B
        user_b = User(
            id=uuid.uuid4(),
            phone_number="+22370000061",
            full_name="Owner B",
            hashed_password=hash_password("Str0ngPass!"),
            is_active=True,
        )
        db_session.add_all([user_a, user_b])
        await db_session.flush()

        headers_a = {"Authorization": f"Bearer {create_access_token(str(user_a.id), user_a.phone_number)}"}
        headers_b = {"Authorization": f"Bearer {create_access_token(str(user_b.id), user_b.phone_number)}"}

        # Créer les deux commerces
        resp_a = await client.post(
            "/api/v1/businesses/",
            headers=headers_a,
            json={"name": "Commerce A", "business_type": "WASH"},
        )
        resp_b = await client.post(
            "/api/v1/businesses/",
            headers=headers_b,
            json={"name": "Commerce B", "business_type": "WASH"},
        )
        assert resp_a.status_code == 201
        assert resp_b.status_code == 201

        # Chaque owner voit uniquement son propre commerce
        biz_a = (await client.get("/api/v1/businesses/my", headers=headers_a)).json()
        biz_b = (await client.get("/api/v1/businesses/my", headers=headers_b)).json()

        assert biz_a["name"] == "Commerce A"
        assert biz_b["name"] == "Commerce B"
        assert biz_a["id"] != biz_b["id"]
