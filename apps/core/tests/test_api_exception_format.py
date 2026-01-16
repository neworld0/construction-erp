import pytest
from django.contrib.auth import get_user_model
from rest_framework.test import APIClient

from apps.projects.models import Project


@pytest.fixture
def client(db):
    return APIClient()


@pytest.fixture
def hq_user(db):
    user = get_user_model().objects.create_user(username="hq", password="pass")
    from apps.core.rbac.models import UserProfile

    UserProfile.objects.create(user=user, role="hq")
    return user


@pytest.fixture
def field_user(db):
    user = get_user_model().objects.create_user(username="field", password="pass")
    from apps.core.rbac.models import UserProfile

    UserProfile.objects.create(user=user, role="field")
    return user


def test_validation_error_format(client, hq_user):
    client.force_authenticate(user=hq_user)
    response = client.post("/api/projects/", {}, format="json")
    assert response.status_code == 400
    data = response.json()
    assert data["code"] == "VALIDATION_ERROR"
    assert "details" in data


def test_forbidden_error_format(client, field_user):
    client.force_authenticate(user=field_user)
    response = client.get("/api/ceo/dashboard/")
    assert response.status_code == 403
    data = response.json()
    assert data["code"] == "FORBIDDEN"


def test_not_found_error_format(client, hq_user):
    client.force_authenticate(user=hq_user)
    response = client.get("/api/evidence/999999/")
    assert response.status_code == 404
    data = response.json()
    assert data["code"] == "NOT_FOUND"
