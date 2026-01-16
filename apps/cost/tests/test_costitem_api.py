import pytest
from django.contrib.auth import get_user_model
from rest_framework.test import APIClient

from apps.cost.models import CostItem


@pytest.fixture
def auth_client(db):
    client = APIClient()
    user = get_user_model().objects.create_user(username="tester", password="pass")
    client.force_authenticate(user=user)
    return client


def test_costitem_list_requires_authentication():
    client = APIClient()

    response = client.get("/api/cost-items/")

    assert response.status_code in (401, 403)


def test_costitem_create_success(auth_client):
    payload = {
        "code": "COST-001",
        "name": "Labor Cost",
        "category": "labor",
        "unit": "hour",
        "is_direct": True,
        "sort_order": 1,
    }

    response = auth_client.post("/api/cost-items/", payload, format="json")

    assert response.status_code == 201
    assert response.json()["code"] == payload["code"]


def test_costitem_duplicate_code_rejected(auth_client):
    CostItem.objects.create(
        code="COST-002",
        name="Material Cost",
        category="material",
        unit="kg",
        is_direct=True,
        sort_order=2,
    )
    payload = {
        "code": "COST-002",
        "name": "Duplicate",
        "category": "material",
        "unit": "kg",
        "is_direct": True,
        "sort_order": 3,
    }

    response = auth_client.post("/api/cost-items/", payload, format="json")

    assert response.status_code == 400
    assert "code" in response.json()


def test_costitem_soft_delete(auth_client):
    item = CostItem.objects.create(
        code="COST-003",
        name="Equipment Cost",
        category="equip",
        unit="day",
        is_direct=False,
        sort_order=5,
        is_active=True,
    )

    response = auth_client.delete(f"/api/cost-items/{item.id}/")

    assert response.status_code == 204
    item.refresh_from_db()
    assert item.is_active is False

    response = auth_client.get("/api/cost-items/")
    assert response.status_code == 200
    codes = [row["code"] for row in response.json()]
    assert item.code not in codes


def test_costitem_rejects_negative_sort_order(auth_client):
    payload = {
        "code": "COST-004",
        "name": "Other Cost",
        "category": "other",
        "unit": "",
        "is_direct": True,
        "sort_order": -1,
    }

    response = auth_client.post("/api/cost-items/", payload, format="json")

    assert response.status_code == 400
    assert "sort_order" in response.json()["details"]
