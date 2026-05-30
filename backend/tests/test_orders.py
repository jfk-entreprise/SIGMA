"""
Tests d'intégration — Module Orders & Financials SIGMA (Étape 2.1).

Couvre :
- Création de commandes WASH et LAUNDRY (TestCreateOrder)
- Annulation de commandes avec contrôle des droits (TestCancelOrder)
- Enregistrement de paiements (TestRecordPayment)
- Dépenses opérationnelles et créances clients (TestFinancials)
- Isolation multi-tenant (TestMultiTenantOrders)

Utilise SQLite in-memory + FakeRedis (via conftest autouse).
"""
import uuid

import pytest
import pytest_asyncio
from httpx import ASGITransport, AsyncClient

from app.main import app


# ---------------------------------------------------------------------------
# Fixture : client HTTP ASGI
# ---------------------------------------------------------------------------


@pytest_asyncio.fixture
async def client():
    """Client HTTP ASGI sans serveur réel."""
    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as c:
        yield c


# ---------------------------------------------------------------------------
# Helpers internes
# ---------------------------------------------------------------------------


async def _create_user_and_business(db_session, phone: str, full_name: str, business_type: str, business_name: str):
    """
    Crée un User + Business + BusinessUser(OWNER) en base,
    initialise les items du catalogue, et retourne (user, headers, business).

    Le commit() est explicite pour garantir la visibilité des données
    dans les sessions HTTP concurrentes (SQLite in-memory partagé).
    """
    from app.core.security import create_access_token, hash_password
    from app.models.business import Business, BusinessUser, UserRole
    from app.models.user import User
    from app.services.business import _initialize_business_items as _copy_items

    user = User(
        id=uuid.uuid4(),
        phone_number=phone,
        full_name=full_name,
        hashed_password=hash_password("Str0ngPass!"),
        is_active=True,
    )
    db_session.add(user)
    await db_session.flush()

    business = Business(
        id=uuid.uuid4(),
        name=business_name,
        business_type=business_type,
        phone=phone,
        location="Bamako",
        is_active=True,
        owner_id=user.id,
    )
    db_session.add(business)
    await db_session.flush()

    membership = BusinessUser(
        id=uuid.uuid4(),
        business_id=business.id,
        user_id=user.id,
        role=UserRole.OWNER,
    )
    db_session.add(membership)
    await db_session.flush()

    # Copie des items du catalogue pour ce commerce
    await _copy_items(db_session, business)

    # Commit explicite pour rendre les données visibles aux sessions HTTP
    await db_session.commit()

    token = create_access_token(user_id=str(user.id), phone_number=user.phone_number)
    headers = {"Authorization": f"Bearer {token}"}
    return user, headers, business


async def _get_first_two_items(client, headers: dict) -> list[dict]:
    """Retourne les 2 premiers items actifs du commerce de l'utilisateur."""
    resp = await client.get("/api/v1/businesses/items", headers=headers)
    assert resp.status_code == 200, f"Impossible de lire les items : {resp.text}"
    items = resp.json()
    assert len(items) >= 2, "Le commerce doit avoir au moins 2 items."
    return items[:2]


async def _get_item_by_name(client, headers: dict, name: str) -> dict | None:
    """Retourne un item par son nom personnalisé."""
    resp = await client.get("/api/v1/businesses/items", headers=headers)
    items = resp.json()
    return next((i for i in items if i["custom_name"] == name), None)


async def _create_order_via_api(client, headers: dict, payload: dict) -> dict:
    """Crée une commande via l'API et retourne le JSON de la réponse."""
    resp = await client.post("/api/v1/orders/", headers=headers, json=payload)
    assert resp.status_code == 201, f"Échec création commande : {resp.text}"
    return resp.json()


# ---------------------------------------------------------------------------
# Fixtures : owner WASH
# ---------------------------------------------------------------------------


@pytest_asyncio.fixture
async def wash_owner(db_session):
    user, _, _ = await _create_user_and_business(
        db_session,
        phone="+22371000001",
        full_name="Karim Coulibaly",
        business_type="WASH",
        business_name="Lavage Rapide Bamako",
    )
    return user


@pytest_asyncio.fixture
async def wash_headers(db_session, wash_owner):
    from app.core.security import create_access_token
    token = create_access_token(user_id=str(wash_owner.id), phone_number=wash_owner.phone_number)
    return {"Authorization": f"Bearer {token}"}


@pytest_asyncio.fixture
async def wash_business(db_session, wash_owner):
    from sqlalchemy import select
    from app.models.business import Business
    result = await db_session.execute(
        select(Business).where(Business.owner_id == wash_owner.id)
    )
    return result.scalar_one()


# ---------------------------------------------------------------------------
# Fixtures : owner LAUNDRY
# ---------------------------------------------------------------------------


@pytest_asyncio.fixture
async def laundry_owner(db_session):
    user, _, _ = await _create_user_and_business(
        db_session,
        phone="+22371000002",
        full_name="Fatoumata Diallo",
        business_type="LAUNDRY",
        business_name="Blanchisserie Propre Net",
    )
    return user


@pytest_asyncio.fixture
async def laundry_headers(db_session, laundry_owner):
    from app.core.security import create_access_token
    token = create_access_token(user_id=str(laundry_owner.id), phone_number=laundry_owner.phone_number)
    return {"Authorization": f"Bearer {token}"}


@pytest_asyncio.fixture
async def laundry_business(db_session, laundry_owner):
    from sqlalchemy import select
    from app.models.business import Business
    result = await db_session.execute(
        select(Business).where(Business.owner_id == laundry_owner.id)
    )
    return result.scalar_one()


# ---------------------------------------------------------------------------
# Fixtures : commandes pré-créées
# ---------------------------------------------------------------------------


@pytest_asyncio.fixture
async def wash_order(client, wash_headers):
    """Commande WASH créée pour les tests qui en ont besoin comme point de départ."""
    items = await _get_first_two_items(client, wash_headers)
    payload = {
        "vehicle_number": "AA-0001",
        "vehicle_color": "Rouge",
        "items": [
            {"business_item_id": items[0]["id"], "quantity": 1},
        ],
    }
    return await _create_order_via_api(client, wash_headers, payload)


@pytest_asyncio.fixture
async def laundry_order(client, laundry_headers):
    """Commande LAUNDRY créée pour les tests qui en ont besoin comme point de départ."""
    items = await _get_first_two_items(client, laundry_headers)
    payload = {
        "items": [
            {"business_item_id": items[0]["id"], "quantity": 1},
        ],
    }
    return await _create_order_via_api(client, laundry_headers, payload)


# ===========================================================================
# CLASSE 1 : Création de commandes
# ===========================================================================


class TestCreateOrder:
    """Tests de création de commandes pour les types WASH et LAUNDRY."""

    @pytest.mark.asyncio
    async def test_create_wash_order_success(self, client, db_session):
        """
        Crée une commande WASH avec vehicle_number="AB-1234", vehicle_color="Blanc"
        et au moins 2 items (4x4 + Aspirateur).
        Vérifie : status=PENDING, total>0.
        """
        _, headers, _ = await _create_user_and_business(
            db_session, "+22372000001", "Seydou Keïta", "WASH", "Lavage Express"
        )
        items = await _get_first_two_items(client, headers)

        payload = {
            "vehicle_number": "AB-1234",
            "vehicle_color": "Blanc",
            "wash_type": "Intérieur + Extérieur",
            "items": [
                {"business_item_id": items[0]["id"], "quantity": 1},
                {"business_item_id": items[1]["id"], "quantity": 1},
            ],
        }
        resp = await client.post("/api/v1/orders/", headers=headers, json=payload)
        assert resp.status_code == 201, resp.text

        data = resp.json()
        assert data["status"] == "PENDING"
        assert data["vehicle_number"] == "AB-1234"
        assert data["vehicle_color"] == "Blanc"
        assert data["total"] > 0
        assert len(data["items"]) == 2

    @pytest.mark.asyncio
    async def test_create_laundry_order_success(self, client, db_session):
        """
        Crée une commande LAUNDRY sans vehicle_number mais avec des items.
        Vérifie : status=PENDING, vehicle_number=None, total>0.
        """
        _, headers, _ = await _create_user_and_business(
            db_session, "+22372000002", "Aminata Traoré", "LAUNDRY", "Blanchisserie Centrale"
        )
        items = await _get_first_two_items(client, headers)

        payload = {
            "customer_name": "Oumar Diarra",
            "items": [
                {"business_item_id": items[0]["id"], "quantity": 2},
                {"business_item_id": items[1]["id"], "quantity": 1},
            ],
        }
        resp = await client.post("/api/v1/orders/", headers=headers, json=payload)
        assert resp.status_code == 201, resp.text

        data = resp.json()
        assert data["status"] == "PENDING"
        assert data["vehicle_number"] is None
        assert data["total"] > 0
        assert len(data["items"]) == 2

    @pytest.mark.asyncio
    async def test_create_order_invalid_item(self, client, db_session):
        """
        Tente de créer une commande avec un business_item_id inexistant.
        Attendu : 404 (item introuvable) ou 422 (validation).
        """
        _, headers, _ = await _create_user_and_business(
            db_session, "+22372000003", "Ibrahim Coulibaly", "WASH", "Lavage Test"
        )
        fake_item_id = str(uuid.uuid4())

        payload = {
            "items": [{"business_item_id": fake_item_id, "quantity": 1}],
        }
        resp = await client.post("/api/v1/orders/", headers=headers, json=payload)
        assert resp.status_code in (400, 404, 422), (
            f"Attendu 400/404/422 pour item inexistant, obtenu {resp.status_code}"
        )

    @pytest.mark.asyncio
    async def test_create_order_cross_tenant_item(self, client, db_session):
        """
        L'owner LAUNDRY tente d'utiliser un item du commerce WASH.
        Attendu : 400/404 (isolation tenant).
        """
        _, wash_headers, _ = await _create_user_and_business(
            db_session, "+22372000004", "Karim Sanogo", "WASH", "Wash A"
        )
        _, laundry_headers, _ = await _create_user_and_business(
            db_session, "+22372000005", "Moussa Diakité", "LAUNDRY", "Laundry B"
        )

        # Récupérer un item du commerce WASH
        wash_items = await _get_first_two_items(client, wash_headers)
        wash_item_id = wash_items[0]["id"]

        # L'owner LAUNDRY tente de créer une commande avec cet item
        payload = {
            "items": [{"business_item_id": wash_item_id, "quantity": 1}],
        }
        resp = await client.post("/api/v1/orders/", headers=laundry_headers, json=payload)
        assert resp.status_code in (400, 404, 422), (
            f"Attendu 400/404/422 pour cross-tenant item, obtenu {resp.status_code}. "
            "L'isolation multi-tenant doit bloquer l'utilisation d'items d'un autre commerce."
        )

    @pytest.mark.asyncio
    async def test_create_order_empty_items(self, client, db_session):
        """
        Zéro items dans la commande → 422 (validation Pydantic min_length=1).
        """
        _, headers, _ = await _create_user_and_business(
            db_session, "+22372000006", "Nana Coulibaly", "WASH", "Lavage Zéro"
        )
        payload = {"items": []}
        resp = await client.post("/api/v1/orders/", headers=headers, json=payload)
        assert resp.status_code == 422, (
            f"Attendu 422 pour items vide, obtenu {resp.status_code}"
        )

    @pytest.mark.asyncio
    async def test_create_order_with_discount(self, client, db_session):
        """
        Discount = 500 FCFA.
        Vérifie que total = subtotal - 500.
        """
        _, headers, _ = await _create_user_and_business(
            db_session, "+22372000007", "Sali Diallo", "WASH", "Lavage Discount"
        )
        items = await _get_first_two_items(client, headers)

        payload = {
            "vehicle_number": "DC-9999",
            "items": [
                {"business_item_id": items[0]["id"], "quantity": 1},
                {"business_item_id": items[1]["id"], "quantity": 1},
            ],
            "discount": 500,
        }
        resp = await client.post("/api/v1/orders/", headers=headers, json=payload)
        assert resp.status_code == 201, resp.text

        data = resp.json()
        assert data["discount"] == 500
        assert data["total"] == data["subtotal"] - 500, (
            f"total={data['total']} devrait être subtotal({data['subtotal']}) - 500"
        )


# ===========================================================================
# CLASSE 2 : Annulation de commandes
# ===========================================================================


class TestCancelOrder:
    """Tests d'annulation de commandes avec contrôle des droits."""

    @pytest.mark.asyncio
    async def test_cancel_pending_order(self, client, wash_headers, wash_order):
        """Annule une commande PENDING → status=CANCELLED, 200."""
        order_id = wash_order["id"]
        resp = await client.patch(
            f"/api/v1/orders/{order_id}/cancel",
            headers=wash_headers,
        )
        assert resp.status_code == 200, resp.text
        data = resp.json()
        assert data["status"] == "CANCELLED"

    @pytest.mark.asyncio
    async def test_cancel_paid_order_forbidden(self, client, wash_headers, wash_order):
        """Tente d'annuler une commande PAID → 400."""
        order_id = wash_order["id"]

        # Payer d'abord la commande
        pay_resp = await client.post(
            f"/api/v1/orders/{order_id}/pay",
            headers=wash_headers,
            json={"payment_method": "CASH", "amount": wash_order["total"] or 1000},
        )
        assert pay_resp.status_code == 201, f"Échec du paiement : {pay_resp.text}"

        # Tenter d'annuler la commande maintenant PAID
        resp = await client.patch(
            f"/api/v1/orders/{order_id}/cancel",
            headers=wash_headers,
        )
        assert resp.status_code == 400, (
            f"Attendu 400 pour annulation d'une commande PAID, obtenu {resp.status_code}"
        )

    @pytest.mark.asyncio
    async def test_cancel_order_by_non_creator_manager(self, client, db_session, wash_business, wash_headers):
        """
        Un MANAGER qui n'a pas créé la commande tente de l'annuler → 400.
        """
        from app.core.security import create_access_token, hash_password
        from app.models.business import BusinessUser, UserRole
        from app.models.user import User

        # Créer un manager dans le même commerce WASH
        manager = User(
            id=uuid.uuid4(),
            phone_number="+22373000001",
            full_name="Manager Non Créateur",
            hashed_password=hash_password("Str0ngPass!"),
            is_active=True,
        )
        db_session.add(manager)
        await db_session.flush()

        db_session.add(BusinessUser(
            id=uuid.uuid4(),
            business_id=wash_business.id,
            user_id=manager.id,
            role=UserRole.MANAGER,
        ))
        await db_session.flush()

        manager_token = create_access_token(str(manager.id), manager.phone_number)
        manager_headers = {"Authorization": f"Bearer {manager_token}"}

        # L'owner crée la commande
        items = await _get_first_two_items(client, wash_headers)
        order = await _create_order_via_api(client, wash_headers, {
            "vehicle_number": "ZZ-1111",
            "items": [{"business_item_id": items[0]["id"], "quantity": 1}],
        })

        # Le manager (non créateur) tente d'annuler
        resp = await client.patch(
            f"/api/v1/orders/{order['id']}/cancel",
            headers=manager_headers,
        )
        assert resp.status_code == 400, (
            f"Attendu 400 pour annulation par manager non créateur, obtenu {resp.status_code}"
        )

    @pytest.mark.asyncio
    async def test_owner_can_cancel_any_order(self, client, db_session, wash_business, wash_headers):
        """
        L'OWNER peut annuler une commande même si un MANAGER l'a créée → 200.
        """
        from app.core.security import create_access_token, hash_password
        from app.models.business import BusinessUser, UserRole
        from app.models.user import User

        # Créer un manager dans le commerce WASH
        manager = User(
            id=uuid.uuid4(),
            phone_number="+22373000002",
            full_name="Manager Créateur",
            hashed_password=hash_password("Str0ngPass!"),
            is_active=True,
        )
        db_session.add(manager)
        await db_session.flush()

        db_session.add(BusinessUser(
            id=uuid.uuid4(),
            business_id=wash_business.id,
            user_id=manager.id,
            role=UserRole.MANAGER,
        ))
        await db_session.flush()

        manager_token = create_access_token(str(manager.id), manager.phone_number)
        manager_headers = {"Authorization": f"Bearer {manager_token}"}

        # Le manager crée une commande
        items = await _get_first_two_items(client, wash_headers)
        order = await _create_order_via_api(client, manager_headers, {
            "vehicle_number": "ZZ-2222",
            "items": [{"business_item_id": items[0]["id"], "quantity": 1}],
        })

        # L'owner (pas le créateur) annule la commande
        resp = await client.patch(
            f"/api/v1/orders/{order['id']}/cancel",
            headers=wash_headers,
        )
        assert resp.status_code == 200, (
            f"L'owner doit pouvoir annuler n'importe quelle commande, obtenu {resp.status_code}: {resp.text}"
        )
        assert resp.json()["status"] == "CANCELLED"


# ===========================================================================
# CLASSE 3 : Enregistrement de paiements
# ===========================================================================


class TestRecordPayment:
    """Tests d'enregistrement de paiements sur une commande."""

    @pytest.mark.asyncio
    async def test_record_cash_payment(self, client, wash_headers, wash_order):
        """
        Paie une commande CASH → statut devient PAID, completed_at non null, 201.
        """
        order_id = wash_order["id"]
        amount = wash_order["total"] if wash_order["total"] > 0 else 1000

        resp = await client.post(
            f"/api/v1/orders/{order_id}/pay",
            headers=wash_headers,
            json={"payment_method": "CASH", "amount": amount},
        )
        assert resp.status_code == 201, resp.text

        payment = resp.json()
        assert payment["payment_method"] == "CASH"
        assert payment["amount"] == amount
        assert payment["order_id"] == order_id

        # Vérifier que la commande est passée en PAID avec completed_at renseigné
        order_resp = await client.get(f"/api/v1/orders/{order_id}", headers=wash_headers)
        assert order_resp.status_code == 200
        order_data = order_resp.json()
        assert order_data["status"] == "PAID"
        assert order_data["completed_at"] is not None

    @pytest.mark.asyncio
    async def test_record_mobile_money_payment(self, client, wash_headers, wash_order):
        """
        Paie avec MOBILE_MONEY + reference → 201.
        """
        order_id = wash_order["id"]
        amount = wash_order["total"] if wash_order["total"] > 0 else 1000

        resp = await client.post(
            f"/api/v1/orders/{order_id}/pay",
            headers=wash_headers,
            json={
                "payment_method": "MOBILE_MONEY",
                "amount": amount,
                "reference": "TXN-2024-001",
            },
        )
        assert resp.status_code == 201, resp.text

        payment = resp.json()
        assert payment["payment_method"] == "MOBILE_MONEY"
        assert payment["reference"] == "TXN-2024-001"

    @pytest.mark.asyncio
    async def test_pay_already_paid_order(self, client, wash_headers, wash_order):
        """
        Tente de payer une commande déjà PAID → 400.
        """
        order_id = wash_order["id"]
        amount = wash_order["total"] if wash_order["total"] > 0 else 1000

        # Premier paiement réussi
        first = await client.post(
            f"/api/v1/orders/{order_id}/pay",
            headers=wash_headers,
            json={"payment_method": "CASH", "amount": amount},
        )
        assert first.status_code == 201

        # Deuxième tentative de paiement
        second = await client.post(
            f"/api/v1/orders/{order_id}/pay",
            headers=wash_headers,
            json={"payment_method": "CASH", "amount": amount},
        )
        assert second.status_code == 400, (
            f"Attendu 400 pour doublon de paiement, obtenu {second.status_code}"
        )

    @pytest.mark.asyncio
    async def test_pay_cancelled_order(self, client, wash_headers, wash_order):
        """
        Tente de payer une commande CANCELLED → 400.
        """
        order_id = wash_order["id"]
        amount = wash_order["total"] if wash_order["total"] > 0 else 1000

        # Annuler la commande
        cancel = await client.patch(
            f"/api/v1/orders/{order_id}/cancel",
            headers=wash_headers,
        )
        assert cancel.status_code == 200

        # Tenter de payer la commande annulée
        resp = await client.post(
            f"/api/v1/orders/{order_id}/pay",
            headers=wash_headers,
            json={"payment_method": "CASH", "amount": amount},
        )
        assert resp.status_code == 400, (
            f"Attendu 400 pour paiement d'une commande CANCELLED, obtenu {resp.status_code}"
        )


# ===========================================================================
# CLASSE 4 : Finances (dépenses et créances)
# ===========================================================================


class TestFinancials:
    """Tests des endpoints financiers : dépenses opérationnelles et créances clients."""

    @pytest.mark.asyncio
    async def test_record_expense_success(self, client, db_session):
        """
        Crée une dépense "Carburant" 5000 FCFA → 201, vérifie les champs.
        """
        _, headers, business = await _create_user_and_business(
            db_session, "+22374000001", "Alpha Touré", "WASH", "Lavage Alpha"
        )

        resp = await client.post(
            "/api/v1/financials/expenses/",
            headers=headers,
            json={"reason": "Carburant", "amount": 5000},
        )
        assert resp.status_code == 201, resp.text

        data = resp.json()
        assert data["reason"] == "Carburant"
        assert data["amount"] == 5000
        assert str(data["business_id"]) == str(business.id)
        assert "id" in data
        assert "created_at" in data

    @pytest.mark.asyncio
    async def test_list_expenses(self, client, db_session):
        """
        Crée 2 dépenses, GET /expenses/ → 2 résultats.
        """
        _, headers, _ = await _create_user_and_business(
            db_session, "+22374000002", "Binta Koné", "WASH", "Lavage Binta"
        )

        for reason, amount in [("Eau minérale", 2000), ("Savon liquide", 3500)]:
            r = await client.post(
                "/api/v1/financials/expenses/",
                headers=headers,
                json={"reason": reason, "amount": amount},
            )
            assert r.status_code == 201

        resp = await client.get("/api/v1/financials/expenses/", headers=headers)
        assert resp.status_code == 200
        expenses = resp.json()
        assert len(expenses) == 2, f"Attendu 2 dépenses, obtenu {len(expenses)}"

    @pytest.mark.asyncio
    async def test_record_credit_success(self, client, db_session):
        """
        Crée un crédit client → status=OUTSTANDING, 201.
        """
        _, headers, business = await _create_user_and_business(
            db_session, "+22374000003", "Cheick Diabaté", "WASH", "Lavage Cheick"
        )

        resp = await client.post(
            "/api/v1/financials/credits/",
            headers=headers,
            json={
                "customer_name": "Oumar Coulibaly",
                "customer_phone": "+22370000100",
                "amount": 7500,
                "reason": "Lavage 4x4 non payé",
            },
        )
        assert resp.status_code == 201, resp.text

        data = resp.json()
        assert data["status"] == "OUTSTANDING"
        assert data["customer_name"] == "Oumar Coulibaly"
        assert data["amount"] == 7500
        assert str(data["business_id"]) == str(business.id)
        assert data["repaid_at"] is None

    @pytest.mark.asyncio
    async def test_repay_credit(self, client, db_session):
        """
        Crée un crédit puis le rembourse → status=REPAID, repaid_at≠None, 200.
        """
        _, headers, _ = await _create_user_and_business(
            db_session, "+22374000004", "Daouda Sanogo", "LAUNDRY", "Blanchisserie Daouda"
        )

        # Créer le crédit
        create_resp = await client.post(
            "/api/v1/financials/credits/",
            headers=headers,
            json={"customer_name": "Fanta Diallo", "amount": 4500},
        )
        assert create_resp.status_code == 201
        credit_id = create_resp.json()["id"]

        # Rembourser le crédit
        repay_resp = await client.patch(
            f"/api/v1/financials/credits/{credit_id}/repay",
            headers=headers,
        )
        assert repay_resp.status_code == 200, repay_resp.text

        data = repay_resp.json()
        assert data["status"] == "REPAID"
        assert data["repaid_at"] is not None
        assert data["repaid_by"] is not None

    @pytest.mark.asyncio
    async def test_repay_already_repaid_credit(self, client, db_session):
        """
        Tente de rembourser un crédit déjà REPAID → 400.
        """
        _, headers, _ = await _create_user_and_business(
            db_session, "+22374000005", "Issa Konaté", "WASH", "Lavage Issa"
        )

        # Créer et rembourser le crédit
        create_resp = await client.post(
            "/api/v1/financials/credits/",
            headers=headers,
            json={"customer_name": "Mamou Traoré", "amount": 3000},
        )
        assert create_resp.status_code == 201
        credit_id = create_resp.json()["id"]

        first_repay = await client.patch(
            f"/api/v1/financials/credits/{credit_id}/repay",
            headers=headers,
        )
        assert first_repay.status_code == 200

        # Deuxième tentative de remboursement
        second_repay = await client.patch(
            f"/api/v1/financials/credits/{credit_id}/repay",
            headers=headers,
        )
        assert second_repay.status_code == 400, (
            f"Attendu 400 pour double remboursement, obtenu {second_repay.status_code}"
        )

    @pytest.mark.asyncio
    async def test_list_credits_filter_by_status(self, client, db_session):
        """
        Crée 2 crédits (1 OUTSTANDING + 1 REPAID).
        Filtre ?status=OUTSTANDING → 1 résultat.
        """
        _, headers, _ = await _create_user_and_business(
            db_session, "+22374000006", "Néné Coulibaly", "WASH", "Lavage Néné"
        )

        # Crédit 1 : restera OUTSTANDING
        c1 = await client.post(
            "/api/v1/financials/credits/",
            headers=headers,
            json={"customer_name": "Client Impayé", "amount": 2500},
        )
        assert c1.status_code == 201

        # Crédit 2 : sera remboursé
        c2 = await client.post(
            "/api/v1/financials/credits/",
            headers=headers,
            json={"customer_name": "Client Remboursé", "amount": 1500},
        )
        assert c2.status_code == 201
        credit2_id = c2.json()["id"]

        repay = await client.patch(
            f"/api/v1/financials/credits/{credit2_id}/repay",
            headers=headers,
        )
        assert repay.status_code == 200

        # Filtre par OUTSTANDING
        resp = await client.get(
            "/api/v1/financials/credits/?status=OUTSTANDING",
            headers=headers,
        )
        assert resp.status_code == 200
        outstanding = resp.json()
        assert len(outstanding) == 1, (
            f"Attendu 1 crédit OUTSTANDING, obtenu {len(outstanding)}"
        )
        assert outstanding[0]["status"] == "OUTSTANDING"


# ===========================================================================
# CLASSE 5 : Isolation multi-tenant pour les commandes
# ===========================================================================


class TestMultiTenantOrders:
    """Vérifie que les commandes d'un commerce sont inaccessibles depuis un autre."""

    @pytest.mark.asyncio
    async def test_owner_b_cannot_see_order_of_owner_a(self, client, db_session):
        """
        2 commerces WASH distincts.
        Owner B effectue GET /orders/{order_a_id} → 404 (isolation tenant).
        """
        _, headers_a, _ = await _create_user_and_business(
            db_session, "+22375000001", "Owner A Wash", "WASH", "Commerce A"
        )
        _, headers_b, _ = await _create_user_and_business(
            db_session, "+22375000002", "Owner B Wash", "WASH", "Commerce B"
        )

        # Owner A crée une commande
        items_a = await _get_first_two_items(client, headers_a)
        order_a = await _create_order_via_api(client, headers_a, {
            "vehicle_number": "AA-XXXX",
            "items": [{"business_item_id": items_a[0]["id"], "quantity": 1}],
        })
        order_a_id = order_a["id"]

        # Owner B tente de lire la commande d'Owner A
        resp = await client.get(f"/api/v1/orders/{order_a_id}", headers=headers_b)
        assert resp.status_code == 404, (
            f"Attendu 404 (isolation tenant), Owner B ne doit pas voir la commande d'Owner A. "
            f"Obtenu {resp.status_code}."
        )

    @pytest.mark.asyncio
    async def test_owner_b_cannot_cancel_order_of_owner_a(self, client, db_session):
        """
        2 commerces WASH distincts.
        Owner B PATCH /orders/{order_a_id}/cancel → 404 (pas 200 ni 403).
        """
        _, headers_a, _ = await _create_user_and_business(
            db_session, "+22375000003", "Owner A Cancel", "WASH", "Commerce A Cancel"
        )
        _, headers_b, _ = await _create_user_and_business(
            db_session, "+22375000004", "Owner B Cancel", "WASH", "Commerce B Cancel"
        )

        # Owner A crée une commande
        items_a = await _get_first_two_items(client, headers_a)
        order_a = await _create_order_via_api(client, headers_a, {
            "vehicle_number": "BB-YYYY",
            "items": [{"business_item_id": items_a[0]["id"], "quantity": 1}],
        })
        order_a_id = order_a["id"]

        # Owner B tente d'annuler la commande d'Owner A
        resp = await client.patch(
            f"/api/v1/orders/{order_a_id}/cancel",
            headers=headers_b,
        )
        assert resp.status_code == 404, (
            f"Attendu 404 (isolation tenant), Owner B ne doit pas pouvoir annuler "
            f"la commande d'Owner A. Obtenu {resp.status_code}."
        )

    @pytest.mark.asyncio
    async def test_owner_b_cannot_pay_order_of_owner_a(self, client, db_session):
        """
        Owner B POST /orders/{order_a_id}/pay → 404 (isolation tenant).
        """
        _, headers_a, _ = await _create_user_and_business(
            db_session, "+22375000005", "Owner A Pay", "WASH", "Commerce A Pay"
        )
        _, headers_b, _ = await _create_user_and_business(
            db_session, "+22375000006", "Owner B Pay", "WASH", "Commerce B Pay"
        )

        items_a = await _get_first_two_items(client, headers_a)
        order_a = await _create_order_via_api(client, headers_a, {
            "vehicle_number": "CC-ZZZZ",
            "items": [{"business_item_id": items_a[0]["id"], "quantity": 1}],
        })

        resp = await client.post(
            f"/api/v1/orders/{order_a['id']}/pay",
            headers=headers_b,
            json={"payment_method": "CASH", "amount": order_a["total"] or 1000},
        )
        assert resp.status_code == 404, (
            f"Attendu 404 (isolation tenant), Owner B ne doit pas pouvoir payer "
            f"la commande d'Owner A. Obtenu {resp.status_code}."
        )

    @pytest.mark.asyncio
    async def test_owner_b_cannot_repay_credit_of_owner_a(self, client, db_session):
        """
        Owner B PATCH /credits/{credit_a_id}/repay → 404 (isolation tenant).
        """
        _, headers_a, _ = await _create_user_and_business(
            db_session, "+22375000007", "Owner A Credit", "WASH", "Commerce A Credit"
        )
        _, headers_b, _ = await _create_user_and_business(
            db_session, "+22375000008", "Owner B Credit", "WASH", "Commerce B Credit"
        )

        create_resp = await client.post(
            "/api/v1/financials/credits/",
            headers=headers_a,
            json={"customer_name": "Client A", "amount": 5000},
        )
        assert create_resp.status_code == 201
        credit_id = create_resp.json()["id"]

        resp = await client.patch(
            f"/api/v1/financials/credits/{credit_id}/repay",
            headers=headers_b,
        )
        assert resp.status_code == 404, (
            f"Attendu 404 (isolation tenant), Owner B ne doit pas pouvoir rembourser "
            f"un crédit d'Owner A. Obtenu {resp.status_code}."
        )

    @pytest.mark.asyncio
    async def test_owner_b_cannot_see_expenses_of_owner_a(self, client, db_session):
        """
        Owner B GET /expenses/ → liste vide (pas de fuite de données d'Owner A).
        """
        _, headers_a, _ = await _create_user_and_business(
            db_session, "+22375000009", "Owner A Expense", "WASH", "Commerce A Expense"
        )
        _, headers_b, _ = await _create_user_and_business(
            db_session, "+22375000010", "Owner B Expense", "WASH", "Commerce B Expense"
        )

        # Owner A crée une dépense
        r = await client.post(
            "/api/v1/financials/expenses/",
            headers=headers_a,
            json={"reason": "Achat secret", "amount": 9999},
        )
        assert r.status_code == 201
        secret_expense_id = r.json()["id"]

        # Owner B liste ses propres dépenses → ne doit pas voir celle d'Owner A
        resp = await client.get("/api/v1/financials/expenses/", headers=headers_b)
        assert resp.status_code == 200
        expense_ids = [e["id"] for e in resp.json()]
        assert secret_expense_id not in expense_ids, (
            "Owner B ne doit pas voir les dépenses d'Owner A (fuite multi-tenant)."
        )


# ===========================================================================
# CLASSE 6 : Validation des règles métier (Étape 2.1 — correctifs QA)
# ===========================================================================


class TestBusinessRuleValidation:
    """
    Vérifie les nouvelles règles métier introduites suite à l'audit @SigmaQA :
    - Discount plafonné au sous-total
    - Montant de paiement >= total pour les méthodes hors-crédit
    - Filtres de statut validés (422 si valeur inconnue)
    - Paiement CREDIT exempté de la validation de montant
    """

    @pytest.mark.asyncio
    async def test_discount_exceeds_subtotal_rejected(self, client, db_session):
        """
        discount > subtotal → 422 (ValueError dans le service, mappé en 422 par le router).
        """
        _, headers, _ = await _create_user_and_business(
            db_session, "+22376000001", "Test Discount", "WASH", "Commerce Discount"
        )
        items = await _get_first_two_items(client, headers)

        payload = {
            "vehicle_number": "DD-0001",
            "items": [{"business_item_id": items[0]["id"], "quantity": 1}],
            "discount": 999999,  # Bien au-delà du sous-total de tout item WASH
        }
        resp = await client.post("/api/v1/orders/", headers=headers, json=payload)
        assert resp.status_code == 422, (
            f"Attendu 422 pour discount > subtotal, obtenu {resp.status_code}: {resp.text}"
        )

    @pytest.mark.asyncio
    async def test_payment_below_order_total_rejected(self, client, db_session):
        """
        CASH amount=1 FCFA sur une commande de plusieurs milliers → 400.
        """
        _, headers, _ = await _create_user_and_business(
            db_session, "+22376000002", "Test Paiement", "WASH", "Commerce Paiement"
        )
        items = await _get_first_two_items(client, headers)
        order = await _create_order_via_api(client, headers, {
            "vehicle_number": "EE-0001",
            "items": [{"business_item_id": items[0]["id"], "quantity": 1}],
        })

        assert order["total"] > 1, (
            f"Le total de la commande doit être > 1 FCFA pour ce test, obtenu {order['total']}"
        )

        resp = await client.post(
            f"/api/v1/orders/{order['id']}/pay",
            headers=headers,
            json={"payment_method": "CASH", "amount": 1},
        )
        assert resp.status_code == 400, (
            f"Attendu 400 pour montant CASH insuffisant, obtenu {resp.status_code}: {resp.text}"
        )

    @pytest.mark.asyncio
    async def test_credit_payment_bypasses_amount_check(self, client, db_session):
        """
        Paiement CREDIT avec amount=1 FCFA < total → 201 (CREDIT est exempté).
        Le paiement partiel différé est un cas métier valide pour les créances.
        """
        _, headers, _ = await _create_user_and_business(
            db_session, "+22376000003", "Test Credit Pay", "WASH", "Commerce Credit"
        )
        items = await _get_first_two_items(client, headers)
        order = await _create_order_via_api(client, headers, {
            "vehicle_number": "FF-0001",
            "items": [{"business_item_id": items[0]["id"], "quantity": 1}],
        })

        resp = await client.post(
            f"/api/v1/orders/{order['id']}/pay",
            headers=headers,
            json={"payment_method": "CREDIT", "amount": 1},
        )
        assert resp.status_code == 201, (
            f"Un paiement CREDIT doit passer même avec amount < total. "
            f"Obtenu {resp.status_code}: {resp.text}"
        )

    @pytest.mark.asyncio
    async def test_list_orders_invalid_status_returns_422(self, client, db_session):
        """
        GET /orders/?status=INVALID → 422 (plus de liste vide silencieuse).
        """
        _, headers, _ = await _create_user_and_business(
            db_session, "+22376000004", "Test Statut Ordres", "WASH", "Commerce Statut"
        )
        resp = await client.get("/api/v1/orders/?status=INVALID_STATUS", headers=headers)
        assert resp.status_code == 422, (
            f"Attendu 422 pour statut invalide dans les commandes, obtenu {resp.status_code}"
        )

    @pytest.mark.asyncio
    async def test_list_credits_invalid_status_returns_422(self, client, db_session):
        """
        GET /credits/?status=INVALID → 422 (plus de liste vide silencieuse).
        """
        _, headers, _ = await _create_user_and_business(
            db_session, "+22376000005", "Test Statut Credits", "WASH", "Commerce Statut2"
        )
        resp = await client.get(
            "/api/v1/financials/credits/?status=INVALID_STATUS", headers=headers
        )
        assert resp.status_code == 422, (
            f"Attendu 422 pour statut invalide dans les crédits, obtenu {resp.status_code}"
        )
