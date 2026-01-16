from decimal import Decimal

import pytest
from django.contrib.auth import get_user_model
from rest_framework.test import APIClient

from apps.cost.models import (
    CostActual,
    CostActualLine,
    CostActualStatus,
    CostItem,
    RevenueRecognition,
)
from apps.core.rbac.models import UserProfile
from apps.contracts.models import ContractSnapshot
from apps.projects.models import Project


@pytest.fixture
def auth_client(db):
    client = APIClient()
    user = get_user_model().objects.create_user(username="tester", password="pass")
    UserProfile.objects.create(user=user, role="hq")
    client.force_authenticate(user=user)
    return client


@pytest.fixture
def project(db):
    return Project.objects.create(code="PRJ-PL-001", name="ProfitLoss Project")


def _create_snapshot(project, version_no, amount, is_active=True):
    return ContractSnapshot.objects.create(
        project=project,
        version_no=version_no,
        base_contract_amount=amount,
        is_active=is_active,
    )


@pytest.fixture
def cost_item(db):
    return CostItem.objects.create(
        code="COST-PL-001",
        name="Labor",
        category="labor",
        unit="hour",
        is_direct=True,
        sort_order=1,
        is_active=True,
    )


def _create_revenue(project, snapshot, progress_percent, as_of_date):
    return RevenueRecognition.objects.create(
        project=project,
        contract_snapshot=snapshot,
        as_of_date=as_of_date,
        progress_percent=progress_percent,
    )


def _create_cost(project, cost_item, quantity, unit_price):
    cost_actual = CostActual.objects.create(
        project=project,
        report_date="2024-01-01",
        status=CostActualStatus.APPROVED,
    )
    CostActualLine.objects.create(
        cost_actual=cost_actual,
        cost_item=cost_item,
        quantity=quantity,
        unit_price=unit_price,
    )
    return cost_actual


def test_missing_params_returns_400(auth_client):
    response = auth_client.get("/api/profit-loss/")
    assert response.status_code == 400


def test_no_data_returns_zero(auth_client, project):
    response = auth_client.get(f"/api/profit-loss/?project_id={project.id}")
    data = response.json()

    assert response.status_code == 200
    assert data["as_of_date"] is None
    assert Decimal(data["recognized_revenue"]) == Decimal("0")
    assert Decimal(data["accrual_cost"]) == Decimal("0")
    assert Decimal(data["profit"]) == Decimal("0")


def test_profit_calculation(auth_client, project, cost_item):
    snapshot = _create_snapshot(project, 1, Decimal("1000"))
    _create_revenue(project, snapshot, Decimal("10.000"), "2024-01-01")
    _create_cost(project, cost_item, quantity=2, unit_price=100)

    response = auth_client.get(f"/api/profit-loss/?project_id={project.id}")
    data = response.json()

    assert Decimal(data["recognized_revenue"]) == Decimal("100.00")
    assert Decimal(data["accrual_cost"]) == Decimal("200")
    assert Decimal(data["profit"]) == Decimal("-100.00")


def test_margin_percent_when_revenue_positive(auth_client, project, cost_item):
    snapshot = _create_snapshot(project, 1, Decimal("1000"))
    _create_revenue(project, snapshot, Decimal("20.000"), "2024-01-01")
    _create_cost(project, cost_item, quantity=1, unit_price=100)

    response = auth_client.get(f"/api/profit-loss/?project_id={project.id}")
    data = response.json()

    assert Decimal(data["recognized_revenue"]) == Decimal("200.00")
    assert Decimal(data["accrual_cost"]) == Decimal("100")
    assert Decimal(data["profit"]) == Decimal("100.00")
    assert Decimal(data["margin_percent"]).quantize(Decimal("0.01")) == Decimal("50.00")


def test_snapshot_separation(auth_client, project):
    snapshot_one = _create_snapshot(project, 1, Decimal("1000"))
    _create_revenue(project, snapshot_one, Decimal("10.000"), "2024-01-01")

    snapshot_two = _create_snapshot(project, 2, Decimal("2000"), is_active=False)
    _create_revenue(project, snapshot_two, Decimal("10.000"), "2024-01-01")

    response_one = auth_client.get(f"/api/profit-loss/?snapshot_id={snapshot_one.id}")
    response_two = auth_client.get(f"/api/profit-loss/?snapshot_id={snapshot_two.id}")

    assert Decimal(response_one.json()["recognized_revenue"]) == Decimal("100.00")
    assert Decimal(response_two.json()["recognized_revenue"]) == Decimal("200.00")


def test_project_uses_active_snapshot(auth_client, project):
    snapshot_one = _create_snapshot(project, 1, Decimal("1000"), is_active=False)
    _create_revenue(project, snapshot_one, Decimal("10.000"), "2024-01-01")

    snapshot_two = _create_snapshot(project, 2, Decimal("2000"))
    _create_revenue(project, snapshot_two, Decimal("10.000"), "2024-01-02")

    response = auth_client.get(f"/api/profit-loss/?project_id={project.id}")
    data = response.json()

    assert Decimal(data["recognized_revenue"]) == Decimal("200.00")
