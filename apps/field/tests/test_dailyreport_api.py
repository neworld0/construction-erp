import pytest
from django.contrib.auth import get_user_model
from rest_framework.test import APIClient

from apps.cost.models import CostItem
from apps.projects.models import Project


@pytest.fixture
def auth_client(db):
    client = APIClient()
    user = get_user_model().objects.create_user(username="tester", password="pass")
    client.force_authenticate(user=user)
    return client


@pytest.fixture
def seed_project(db):
    return Project.objects.create(
        code="PRJ-DR-001",
        name="Daily Report Project",
        client_name="Client DR",
        contract_amount="10000.00",
        status="planned",
    )


@pytest.fixture
def seed_cost_item(db):
    return CostItem.objects.create(
        code="COST-DR-001",
        name="Labor",
        category="labor",
        unit="hour",
        is_direct=True,
        sort_order=1,
        is_active=True,
    )


def _report_payload(project_id, reporter_id, cost_item_id, overrides=None):
    payload = {
        "project": project_id,
        "report_date": "2024-01-01",
        "reporter": reporter_id,
        "note": "",
        "lines": [
            {
                "cost_item": cost_item_id,
                "description": "Work",
                "quantity": "2.000",
                "unit_price": "100.00",
            }
        ],
    }
    if overrides:
        payload.update(overrides)
    return payload


def test_dailyreport_list_requires_authentication():
    client = APIClient()

    response = client.get("/api/daily-reports/")

    assert response.status_code in (401, 403)


def test_dailyreport_create_with_lines_success(auth_client, seed_project, seed_cost_item):
    user = get_user_model().objects.get(username="tester")
    payload = _report_payload(seed_project.id, user.id, seed_cost_item.id)

    response = auth_client.post("/api/daily-reports/", payload, format="json")

    assert response.status_code == 201
    data = response.json()
    assert data["project"] == seed_project.id
    assert len(data["lines"]) == 1


def test_dailyreport_rejects_inactive_cost_item(auth_client, seed_project):
    inactive_item = CostItem.objects.create(
        code="COST-DR-002",
        name="Inactive",
        category="material",
        unit="kg",
        is_direct=True,
        sort_order=2,
        is_active=False,
    )
    user = get_user_model().objects.get(username="tester")
    payload = _report_payload(seed_project.id, user.id, inactive_item.id)

    response = auth_client.post("/api/daily-reports/", payload, format="json")

    assert response.status_code == 400
    assert "lines" in response.json()["details"]


@pytest.mark.parametrize(
    "line_overrides",
    [
        {"quantity": "-1.000"},
        {"unit_price": "-10.00"},
    ],
)
def test_dailyreport_rejects_negative_amounts(
    auth_client, seed_project, seed_cost_item, line_overrides
):
    user = get_user_model().objects.get(username="tester")
    payload = _report_payload(seed_project.id, user.id, seed_cost_item.id)
    payload["lines"][0].update(line_overrides)

    response = auth_client.post("/api/daily-reports/", payload, format="json")

    assert response.status_code == 400
    assert "lines" in response.json()["details"]


def test_dailyreport_submit_transition(auth_client, seed_project, seed_cost_item):
    user = get_user_model().objects.get(username="tester")
    payload = _report_payload(seed_project.id, user.id, seed_cost_item.id)
    create_response = auth_client.post("/api/daily-reports/", payload, format="json")
    report_id = create_response.json()["id"]

    submit_response = auth_client.post(f"/api/daily-reports/{report_id}/submit/")

    assert submit_response.status_code == 200
    assert submit_response.json()["status"] == "submitted"

    resubmit_response = auth_client.post(f"/api/daily-reports/{report_id}/submit/")

    assert resubmit_response.status_code == 400
