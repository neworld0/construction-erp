import pytest
from django.contrib.auth import get_user_model
from rest_framework.test import APIClient

from apps.projects.models import Project
from apps.core.rbac.models import UserProfile


@pytest.fixture
def auth_client(db):
    client = APIClient()
    user = get_user_model().objects.create_user(username="tester", password="pass")
    UserProfile.objects.create(user=user, role="hq")
    client.force_authenticate(user=user)
    return client


def test_project_list_requires_authentication():
    client = APIClient()

    response = client.get("/api/projects/")

    assert response.status_code in (401, 403)


def test_project_create_success(auth_client):
    payload = {
        "code": "PRJ-001",
        "name": "Sample Project",
        "client_name": "Client A",
        "contract_amount": "1000.00",
        "start_date": "2024-01-01",
        "end_date": "2024-12-31",
        "status": "planned",
    }

    response = auth_client.post("/api/projects/", payload, format="json")

    assert response.status_code == 201
    assert response.json()["code"] == payload["code"]


def test_project_rejects_negative_contract_amount(auth_client):
    Project.objects.create(
        code="PRJ-NEG-UPDATE",
        name="Update Target",
        client_name="Client U",
        contract_amount="100.00",
        start_date="2024-01-01",
        end_date="2024-12-31",
        status="planned",
    )
    payload = {
        "code": "PRJ-004",
        "name": "Bad Project",
        "client_name": "Client D",
        "contract_amount": "-1.00",
        "start_date": "2024-01-01",
        "end_date": "2024-12-31",
        "status": "planned",
    }

    response = auth_client.post("/api/projects/", payload, format="json")

    assert response.status_code == 400
    assert "contract_amount" in response.json()["details"]

    project = Project.objects.get(code="PRJ-NEG-UPDATE")
    response = auth_client.patch(
        f"/api/projects/{project.id}/",
        {"contract_amount": "-5.00"},
        format="json",
    )

    assert response.status_code == 400
    assert "contract_amount" in response.json()["details"]


def test_project_soft_delete(auth_client):
    project = Project.objects.create(
        code="PRJ-005",
        name="Soft Delete Project",
        client_name="Client E",
        contract_amount="1200.00",
        start_date="2024-04-01",
        end_date="2024-11-30",
        status="active",
        is_active=True,
    )

    response = auth_client.delete(f"/api/projects/{project.id}/")

    assert response.status_code == 204
    project.refresh_from_db()
    assert project.is_active is False

    response = auth_client.get("/api/projects/")
    assert response.status_code == 200
    codes = [item["code"] for item in response.json()]
    assert project.code not in codes
