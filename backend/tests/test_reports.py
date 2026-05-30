"""
Tests d'intégration — Module Rapports statistiques SIGMA (Étape 2.2).

Couvre :
- Calcul exact de la formule CA Net (TestNetIncomeFormula)
- Idempotence de l'Upsert DailyReport (TestUpsertIdempotency)
- Barrière d'abonnement /weekly et /monthly (TestSubscriptionGating)
- KPIs du dashboard temps réel (TestDashboard)
- Agrégation multi-jours (TestPeriodSummary)

Utilise SQLite in-memory + FakeRedis (via conftest autouse).
"""
import uuid

import pytest
import pytest_asyncio
from httpx import ASGITransport, AsyncClient

from app.main import app
from app.models.business import SubscriptionPlan


# ---------------------------------------------------------------------------
# Fixture : client HTTP ASGI
# ---------------------------------------------------------------------------


@pytest_asyncio.fixture
async def client():
    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as c:
        yield c


# ---------------------------------------------------------------------------
# Helpers internes (reproduits depuis test_orders.py pour l'isolation)
# ---------------------------------------------------------------------------


async def _create_user_and_business(
    db_session,
    phone: str,
    full_name: str,
    business_type: str,
    business_name: str,
    subscription_plan: str = SubscriptionPlan.FREE.value,
):
    """Crée User + Business(OWNER) + items initialisés. Retourne (user, headers, business)."""
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
        subscription_plan=subscription_plan,
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

    await _copy_items(db_session, business)
    await db_session.commit()

    token = create_access_token(user_id=str(user.id), phone_number=user.phone_number)
    headers = {"Authorization": f"Bearer {token}"}
    return user, headers, business


async def _get_first_item(client, headers: dict) -> dict:
    resp = await client.get("/api/v1/businesses/items", headers=headers)
    assert resp.status_code == 200
    items = resp.json()
    assert len(items) >= 1
    return items[0]


async def _create_and_pay_order(client, headers: dict, item_id: str) -> tuple[dict, dict]:
    """Crée une commande avec 1 item et la paie. Retourne (order, payment)."""
    order_resp = await client.post(
        "/api/v1/orders/",
        headers=headers,
        json={
            "vehicle_number": "TEST-001",
            "items": [{"business_item_id": item_id, "quantity": 1}],
        },
    )
    assert order_resp.status_code == 201, order_resp.text
    order = order_resp.json()

    pay_resp = await client.post(
        f"/api/v1/orders/{order['id']}/pay",
        headers=headers,
        json={"payment_method": "CASH", "amount": order["total"]},
    )
    assert pay_resp.status_code == 201, pay_resp.text
    return order, pay_resp.json()


# ===========================================================================
# CLASSE 1 : Calcul du CA Net
# ===========================================================================


class TestNetIncomeFormula:
    """Vérifie l'exactitude de la formule : net_income = gross_income - (expenses + credits)."""

    @pytest.mark.asyncio
    async def test_net_income_exact_formula(self, client, db_session):
        """
        Scénario type : 1 paiement CASH + 1 dépense + 1 créance.
        Vérifie que le rapport journalier a les valeurs exactes attendues.
        """
        _, headers, _ = await _create_user_and_business(
            db_session, "+22381000001", "Karim Test", "WASH", "Lavage Test Net"
        )
        item = await _get_first_item(client, headers)

        # 1. Payer une commande → déclenche le rapport
        order, payment = await _create_and_pay_order(client, headers, item["id"])
        gross_income_expected = payment["amount"]

        # 2. Enregistrer une dépense (déclenche upsert rapport)
        expense_amount = 3000
        exp_resp = await client.post(
            "/api/v1/financials/expenses/",
            headers=headers,
            json={"reason": "Produits nettoyants", "amount": expense_amount},
        )
        assert exp_resp.status_code == 201

        # 3. Enregistrer une créance (déclenche upsert rapport)
        credit_amount = 1500
        cred_resp = await client.post(
            "/api/v1/financials/credits/",
            headers=headers,
            json={"customer_name": "Client Test", "amount": credit_amount},
        )
        assert cred_resp.status_code == 201

        # 4. Récupérer le rapport journalier via l'API
        reports_resp = await client.get("/api/v1/reports/daily", headers=headers)
        assert reports_resp.status_code == 200
        reports = reports_resp.json()

        assert len(reports) == 1, f"Attendu 1 rapport journalier, obtenu {len(reports)}"
        report = reports[0]

        assert report["gross_income"] == gross_income_expected, (
            f"gross_income attendu : {gross_income_expected}, obtenu : {report['gross_income']}"
        )
        assert report["expenses"] == expense_amount, (
            f"expenses attendu : {expense_amount}, obtenu : {report['expenses']}"
        )
        assert report["credits"] == credit_amount, (
            f"credits attendu : {credit_amount}, obtenu : {report['credits']}"
        )
        expected_net = gross_income_expected - expense_amount - credit_amount
        assert report["net_income"] == expected_net, (
            f"net_income attendu : {expected_net}, obtenu : {report['net_income']}"
        )

    @pytest.mark.asyncio
    async def test_net_income_negative_when_losses_exceed_income(self, client, db_session):
        """
        Si les dépenses + créances dépassent le CA brut, net_income doit être négatif.
        """
        _, headers, _ = await _create_user_and_business(
            db_session, "+22381000002", "Test Négatif", "WASH", "Commerce Déficit"
        )
        item = await _get_first_item(client, headers)

        order, payment = await _create_and_pay_order(client, headers, item["id"])
        gross = payment["amount"]

        # Dépense intentionnellement supérieure au CA
        big_expense = gross + 10000
        await client.post(
            "/api/v1/financials/expenses/",
            headers=headers,
            json={"reason": "Grosse réparation", "amount": big_expense},
        )

        reports_resp = await client.get("/api/v1/reports/daily", headers=headers)
        report = reports_resp.json()[0]

        assert report["net_income"] < 0, (
            f"net_income devrait être négatif, obtenu : {report['net_income']}"
        )
        assert report["net_income"] == gross - big_expense

    @pytest.mark.asyncio
    async def test_total_orders_excludes_cancelled(self, client, db_session):
        """
        Les commandes CANCELLED ne comptent pas dans total_orders.
        """
        _, headers, _ = await _create_user_and_business(
            db_session, "+22381000003", "Test Annulé", "WASH", "Commerce Annul"
        )
        item = await _get_first_item(client, headers)

        # Créer et payer 1 commande → total_orders = 1
        await _create_and_pay_order(client, headers, item["id"])

        # Créer et annuler 1 commande → total_orders reste 1
        order_resp = await client.post(
            "/api/v1/orders/",
            headers=headers,
            json={
                "vehicle_number": "ANN-001",
                "items": [{"business_item_id": item["id"], "quantity": 1}],
            },
        )
        assert order_resp.status_code == 201
        order_id = order_resp.json()["id"]
        await client.patch(f"/api/v1/orders/{order_id}/cancel", headers=headers)

        # Créer une dépense pour déclencher le refresh du rapport
        await client.post(
            "/api/v1/financials/expenses/",
            headers=headers,
            json={"reason": "Trigger rapport", "amount": 100},
        )

        reports_resp = await client.get("/api/v1/reports/daily", headers=headers)
        report = reports_resp.json()[0]

        assert report["total_orders"] == 1, (
            f"total_orders devrait être 1 (hors CANCELLED), obtenu : {report['total_orders']}"
        )


# ===========================================================================
# CLASSE 2 : Idempotence de l'Upsert
# ===========================================================================


class TestUpsertIdempotency:
    """Vérifie qu'un même jour ne produit jamais qu'une seule ligne DailyReport."""

    @pytest.mark.asyncio
    async def test_multiple_events_produce_single_report(self, client, db_session):
        """
        3 événements financiers (paiement, dépense, créance) → 1 seul DailyReport
        avec des valeurs cumulées correctes.

        Assertion via GET /reports/daily (session HTTP fraîche) plutôt que via
        la session de test directe : la session de test peut avoir un snapshot
        de transaction antérieur aux commits des sessions HTTP, ce qui rendrait
        les données stale même après expire_all().
        """
        _, headers, _ = await _create_user_and_business(
            db_session, "+22382000001", "Test Upsert", "WASH", "Commerce Upsert"
        )
        item = await _get_first_item(client, headers)

        # Événement 1 : paiement → INSERT du rapport
        _, pay1 = await _create_and_pay_order(client, headers, item["id"])

        # Événement 2 : dépense → UPDATE du rapport
        await client.post(
            "/api/v1/financials/expenses/",
            headers=headers,
            json={"reason": "Essence", "amount": 2000},
        )

        # Événement 3 : créance → UPDATE du rapport
        await client.post(
            "/api/v1/financials/credits/",
            headers=headers,
            json={"customer_name": "Jean Dupont", "amount": 500},
        )

        # Vérification via l'API (session HTTP fraîche = snapshot cohérent post-commits)
        reports_resp = await client.get("/api/v1/reports/daily", headers=headers)
        assert reports_resp.status_code == 200
        reports = reports_resp.json()

        assert len(reports) == 1, (
            f"L'upsert doit produire exactement 1 DailyReport, obtenu {len(reports)}."
        )
        report = reports[0]
        assert report["gross_income"] == pay1["amount"], (
            f"gross_income attendu {pay1['amount']}, obtenu {report['gross_income']}"
        )
        assert report["expenses"] == 2000, (
            f"expenses attendu 2000, obtenu {report['expenses']}"
        )
        assert report["credits"] == 500, (
            f"credits attendu 500, obtenu {report['credits']}"
        )
        assert report["net_income"] == pay1["amount"] - 2000 - 500, (
            f"net_income attendu {pay1['amount'] - 2500}, obtenu {report['net_income']}"
        )

    @pytest.mark.asyncio
    async def test_second_payment_updates_gross_income(self, client, db_session):
        """
        Deux paiements le même jour → gross_income = somme des deux.
        """
        _, headers, _ = await _create_user_and_business(
            db_session, "+22382000002", "Test Double Paiement", "WASH", "Commerce Double"
        )
        item = await _get_first_item(client, headers)

        _, pay1 = await _create_and_pay_order(client, headers, item["id"])

        # Deuxième commande (vehicle_number différent pour éviter les doublons)
        order2_resp = await client.post(
            "/api/v1/orders/",
            headers=headers,
            json={
                "vehicle_number": "BB-0002",
                "items": [{"business_item_id": item["id"], "quantity": 1}],
            },
        )
        assert order2_resp.status_code == 201
        order2 = order2_resp.json()
        pay2_resp = await client.post(
            f"/api/v1/orders/{order2['id']}/pay",
            headers=headers,
            json={"payment_method": "CASH", "amount": order2["total"]},
        )
        assert pay2_resp.status_code == 201
        pay2 = pay2_resp.json()

        reports_resp = await client.get("/api/v1/reports/daily", headers=headers)
        report = reports_resp.json()[0]

        expected_gross = pay1["amount"] + pay2["amount"]
        assert report["gross_income"] == expected_gross, (
            f"gross_income cumulé attendu : {expected_gross}, obtenu : {report['gross_income']}"
        )


# ===========================================================================
# CLASSE 3 : Barrière d'abonnement
# ===========================================================================


class TestSubscriptionGating:
    """Vérifie que /weekly et /monthly requièrent un plan PREMIUM ou PREMIUM_PRO."""

    @pytest.mark.asyncio
    async def test_free_plan_blocked_on_weekly(self, client, db_session):
        """Plan FREE → GET /weekly → 403."""
        _, headers, _ = await _create_user_and_business(
            db_session, "+22383000001", "Test Free", "WASH", "Commerce Free W",
            subscription_plan=SubscriptionPlan.FREE.value,
        )
        resp = await client.get("/api/v1/reports/weekly", headers=headers)
        assert resp.status_code == 403, (
            f"Attendu 403 pour plan FREE sur /weekly, obtenu {resp.status_code}"
        )
        assert "PREMIUM" in resp.json()["detail"]

    @pytest.mark.asyncio
    async def test_free_plan_blocked_on_monthly(self, client, db_session):
        """Plan FREE → GET /monthly → 403."""
        _, headers, _ = await _create_user_and_business(
            db_session, "+22383000002", "Test Free M", "WASH", "Commerce Free M",
            subscription_plan=SubscriptionPlan.FREE.value,
        )
        resp = await client.get("/api/v1/reports/monthly", headers=headers)
        assert resp.status_code == 403, (
            f"Attendu 403 pour plan FREE sur /monthly, obtenu {resp.status_code}"
        )

    @pytest.mark.asyncio
    async def test_premium_plan_allowed_on_weekly(self, client, db_session):
        """Plan PREMIUM → GET /weekly → 200."""
        _, headers, business = await _create_user_and_business(
            db_session, "+22383000003", "Test Premium W", "WASH", "Commerce Premium W",
            subscription_plan=SubscriptionPlan.PREMIUM.value,
        )
        resp = await client.get("/api/v1/reports/weekly", headers=headers)
        assert resp.status_code == 200, (
            f"Attendu 200 pour plan PREMIUM sur /weekly, obtenu {resp.status_code}: {resp.text}"
        )
        data = resp.json()
        assert "period_start" in data
        assert "period_end" in data
        assert "net_income" in data
        assert isinstance(data["days"], list)

    @pytest.mark.asyncio
    async def test_premium_plan_allowed_on_monthly(self, client, db_session):
        """Plan PREMIUM → GET /monthly → 200."""
        _, headers, _ = await _create_user_and_business(
            db_session, "+22383000004", "Test Premium M", "WASH", "Commerce Premium M",
            subscription_plan=SubscriptionPlan.PREMIUM.value,
        )
        resp = await client.get("/api/v1/reports/monthly", headers=headers)
        assert resp.status_code == 200, (
            f"Attendu 200 pour plan PREMIUM sur /monthly, obtenu {resp.status_code}"
        )

    @pytest.mark.asyncio
    async def test_premium_pro_plan_allowed(self, client, db_session):
        """Plan PREMIUM_PRO → GET /weekly ET /monthly → 200."""
        _, headers, _ = await _create_user_and_business(
            db_session, "+22383000005", "Test Pro", "WASH", "Commerce Pro",
            subscription_plan=SubscriptionPlan.PREMIUM_PRO.value,
        )
        for endpoint in ("/api/v1/reports/weekly", "/api/v1/reports/monthly"):
            resp = await client.get(endpoint, headers=headers)
            assert resp.status_code == 200, (
                f"Attendu 200 pour PREMIUM_PRO sur {endpoint}, obtenu {resp.status_code}"
            )

    @pytest.mark.asyncio
    async def test_upgrade_free_to_premium_unlocks_reports(self, client, db_session):
        """
        Un commerce passe de FREE à PREMIUM :
        - Avant upgrade : /weekly → 403
        - Après upgrade  : /weekly → 200
        """
        _, headers, business = await _create_user_and_business(
            db_session, "+22383000006", "Test Upgrade", "WASH", "Commerce Upgrade",
            subscription_plan=SubscriptionPlan.FREE.value,
        )
        # Avant upgrade
        resp_before = await client.get("/api/v1/reports/weekly", headers=headers)
        assert resp_before.status_code == 403

        # Upgrade en base
        business.subscription_plan = SubscriptionPlan.PREMIUM.value
        await db_session.commit()

        # Après upgrade
        resp_after = await client.get("/api/v1/reports/weekly", headers=headers)
        assert resp_after.status_code == 200, (
            f"Après upgrade PREMIUM, /weekly devrait retourner 200, "
            f"obtenu {resp_after.status_code}: {resp_after.text}"
        )

    @pytest.mark.asyncio
    async def test_free_plan_allowed_on_daily(self, client, db_session):
        """Plan FREE → GET /daily → 200 (accès autorisé à tous)."""
        _, headers, _ = await _create_user_and_business(
            db_session, "+22383000007", "Test Free Daily", "WASH", "Commerce Free Daily",
            subscription_plan=SubscriptionPlan.FREE.value,
        )
        resp = await client.get("/api/v1/reports/daily", headers=headers)
        assert resp.status_code == 200, (
            f"Attendu 200 sur /daily pour plan FREE, obtenu {resp.status_code}"
        )

    @pytest.mark.asyncio
    async def test_upgrade_free_to_premium_pro_unlocks_reports(self, client, db_session):
        """
        FREE → PREMIUM_PRO : /weekly et /monthly sont débloqués après upgrade.
        Valide que la barrière _require_premium lit le plan en temps réel depuis la DB.
        """
        _, headers, business = await _create_user_and_business(
            db_session, "+22383000008", "Test Upgrade Pro", "WASH", "Commerce Upgrade Pro",
            subscription_plan=SubscriptionPlan.FREE.value,
        )
        # Avant upgrade : les deux endpoints premium sont bloqués
        assert (await client.get("/api/v1/reports/weekly", headers=headers)).status_code == 403
        assert (await client.get("/api/v1/reports/monthly", headers=headers)).status_code == 403

        # Upgrade vers PREMIUM_PRO en base
        business.subscription_plan = SubscriptionPlan.PREMIUM_PRO.value
        await db_session.commit()

        # Après upgrade : les deux endpoints sont débloqués
        resp_weekly = await client.get("/api/v1/reports/weekly", headers=headers)
        assert resp_weekly.status_code == 200, (
            f"Après upgrade PREMIUM_PRO, /weekly devrait retourner 200, "
            f"obtenu {resp_weekly.status_code}: {resp_weekly.text}"
        )
        resp_monthly = await client.get("/api/v1/reports/monthly", headers=headers)
        assert resp_monthly.status_code == 200, (
            f"Après upgrade PREMIUM_PRO, /monthly devrait retourner 200, "
            f"obtenu {resp_monthly.status_code}: {resp_monthly.text}"
        )


# ===========================================================================
# CLASSE 4 : Dashboard temps réel
# ===========================================================================


class TestDashboard:
    """Vérifie les KPIs du dashboard (OWNER uniquement)."""

    @pytest.mark.asyncio
    async def test_dashboard_reflects_todays_activity(self, client, db_session):
        """
        Après un paiement + une dépense : le dashboard affiche les valeurs correctes.
        """
        _, headers, _ = await _create_user_and_business(
            db_session, "+22384000001", "Dashboard Owner", "WASH", "Commerce Dashboard"
        )
        item = await _get_first_item(client, headers)

        # Créer et payer une commande
        order, payment = await _create_and_pay_order(client, headers, item["id"])
        gross = payment["amount"]

        # Enregistrer une dépense
        expense_amount = 1200
        await client.post(
            "/api/v1/financials/expenses/",
            headers=headers,
            json={"reason": "Eau", "amount": expense_amount},
        )

        resp = await client.get("/api/v1/reports/dashboard", headers=headers)
        assert resp.status_code == 200, resp.text

        data = resp.json()
        assert data["gross_income"] == gross
        assert data["total_expenses"] == expense_amount
        assert data["total_credits"] == 0
        assert data["net_income"] == gross - expense_amount
        assert data["paid_orders"] == 1
        assert data["pending_orders"] == 0

    @pytest.mark.asyncio
    async def test_dashboard_counts_pending_orders(self, client, db_session):
        """
        Une commande PENDING créée aujourd'hui apparaît dans pending_orders.
        """
        _, headers, _ = await _create_user_and_business(
            db_session, "+22384000002", "Dashboard Pending", "WASH", "Commerce Pending"
        )
        item = await _get_first_item(client, headers)

        # Créer une commande sans la payer (PENDING)
        resp = await client.post(
            "/api/v1/orders/",
            headers=headers,
            json={
                "vehicle_number": "PEN-001",
                "items": [{"business_item_id": item["id"], "quantity": 1}],
            },
        )
        assert resp.status_code == 201

        dashboard_resp = await client.get("/api/v1/reports/dashboard", headers=headers)
        assert dashboard_resp.status_code == 200
        data = dashboard_resp.json()

        assert data["pending_orders"] == 1
        assert data["paid_orders"] == 0
        assert data["gross_income"] == 0

    @pytest.mark.asyncio
    async def test_dashboard_reserved_for_owner(self, client, db_session):
        """
        Un MANAGER ne peut pas accéder au dashboard → 403.
        """
        from app.core.security import create_access_token, hash_password
        from app.models.business import BusinessUser, UserRole
        from app.models.user import User

        _, owner_headers, business = await _create_user_and_business(
            db_session, "+22384000003", "Owner Dashboard", "WASH", "Commerce Manager"
        )

        # Créer un MANAGER
        manager = User(
            id=uuid.uuid4(),
            phone_number="+22384000099",
            full_name="Manager Test",
            hashed_password=hash_password("Str0ngPass!"),
            is_active=True,
        )
        db_session.add(manager)
        await db_session.flush()
        db_session.add(BusinessUser(
            id=uuid.uuid4(),
            business_id=business.id,
            user_id=manager.id,
            role=UserRole.MANAGER,
        ))
        await db_session.commit()

        manager_token = create_access_token(str(manager.id), manager.phone_number)
        manager_headers = {"Authorization": f"Bearer {manager_token}"}

        resp = await client.get("/api/v1/reports/dashboard", headers=manager_headers)
        assert resp.status_code == 403, (
            f"Le dashboard doit être réservé à l'OWNER (403), obtenu {resp.status_code}"
        )


# ===========================================================================
# CLASSE 5 : Agrégation multi-jours (weekly/monthly)
# ===========================================================================


class TestPeriodSummary:
    """Vérifie que les rapports weekly/monthly agrègent correctement les DailyReports."""

    @pytest.mark.asyncio
    async def test_weekly_aggregates_todays_data(self, client, db_session):
        """
        Un rapport journalier créé aujourd'hui apparaît dans la synthèse hebdomadaire.
        """
        _, headers, _ = await _create_user_and_business(
            db_session, "+22385000001", "Test Weekly", "WASH", "Commerce Weekly",
            subscription_plan=SubscriptionPlan.PREMIUM.value,
        )
        item = await _get_first_item(client, headers)

        _, payment = await _create_and_pay_order(client, headers, item["id"])
        gross = payment["amount"]

        resp = await client.get("/api/v1/reports/weekly", headers=headers)
        assert resp.status_code == 200, resp.text
        data = resp.json()

        assert data["gross_income"] == gross, (
            f"gross_income hebdomadaire attendu : {gross}, obtenu : {data['gross_income']}"
        )
        assert data["net_income"] == gross
        assert len(data["days"]) >= 1, "La synthèse hebdomadaire doit inclure au moins 1 jour."

    @pytest.mark.asyncio
    async def test_monthly_includes_all_current_month_reports(self, client, db_session):
        """
        Les rapports générés ce mois apparaissent dans la synthèse mensuelle.
        """
        _, headers, _ = await _create_user_and_business(
            db_session, "+22385000002", "Test Monthly", "WASH", "Commerce Monthly",
            subscription_plan=SubscriptionPlan.PREMIUM.value,
        )
        item = await _get_first_item(client, headers)

        # Deux paiements + une dépense
        _, pay1 = await _create_and_pay_order(client, headers, item["id"])
        order2_resp = await client.post(
            "/api/v1/orders/",
            headers=headers,
            json={
                "vehicle_number": "MO-0002",
                "items": [{"business_item_id": item["id"], "quantity": 1}],
            },
        )
        order2 = order2_resp.json()
        pay2_resp = await client.post(
            f"/api/v1/orders/{order2['id']}/pay",
            headers=headers,
            json={"payment_method": "CASH", "amount": order2["total"]},
        )
        pay2 = pay2_resp.json()

        expense_amount = 800
        await client.post(
            "/api/v1/financials/expenses/",
            headers=headers,
            json={"reason": "Savon", "amount": expense_amount},
        )

        resp = await client.get("/api/v1/reports/monthly", headers=headers)
        assert resp.status_code == 200, resp.text
        data = resp.json()

        expected_gross = pay1["amount"] + pay2["amount"]
        assert data["gross_income"] == expected_gross
        assert data["expenses"] == expense_amount
        assert data["net_income"] == expected_gross - expense_amount

    @pytest.mark.asyncio
    async def test_period_structure_fields(self, client, db_session):
        """
        Vérifie la présence de tous les champs de PeriodSummaryResponse.
        """
        _, headers, _ = await _create_user_and_business(
            db_session, "+22385000003", "Test Fields", "WASH", "Commerce Fields",
            subscription_plan=SubscriptionPlan.PREMIUM.value,
        )

        resp = await client.get("/api/v1/reports/weekly", headers=headers)
        assert resp.status_code == 200
        data = resp.json()

        required_fields = {
            "period_start", "period_end", "total_orders",
            "gross_income", "expenses", "credits", "net_income", "days",
        }
        missing = required_fields - set(data.keys())
        assert not missing, f"Champs manquants dans PeriodSummaryResponse : {missing}"
