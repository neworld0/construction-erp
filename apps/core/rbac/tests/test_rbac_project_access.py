import pytest
from django.contrib.auth import get_user_model
from rest_framework.test import APIClient

from apps.core.rbac.models import ProjectAssignment, UserProfile
from apps.projects.models import Project


@pytest.fixture
def project_a(db):
    return Project.objects.create(code="PRJ-RBAC-001", name="RBAC Project A")


@pytest.fixture
def project_b(db):
    return Project.objects.create(code="PRJ-RBAC-002", name="RBAC Project B")


@pytest.fixture
def field_user(db):
    user = get_user_model().objects.create_user(username="field", password="pass")
    UserProfile.objects.create(user=user, role="field")
    return user


@pytest.fixture
def hq_user(db):
    user = get_user_model().objects.create_user(username="hq", password="pass")
    UserProfile.objects.create(user=user, role="hq")
    return user


@pytest.fixture
def field_client(field_user):
    client = APIClient()
    client.force_authenticate(user=field_user)
    return client


@pytest.fixture
def hq_client(hq_user):
    client = APIClient()
    client.force_authenticate(user=hq_user)
    return client


def test_field_unassigned_progress_forbidden(field_client, project_a):
    response = field_client.get(f"/api/progress/?project_id={project_a.id}")
    assert response.status_code == 403


def test_field_assigned_progress_allowed(field_client, field_user, project_a):
    ProjectAssignment.objects.create(user=field_user, project=project_a, is_active=True)
    response = field_client.get(f"/api/progress/?project_id={project_a.id}")
    assert response.status_code == 200


def test_field_unassigned_profit_loss_forbidden(field_client, project_a):
    response = field_client.get(f"/api/profit-loss/?project_id={project_a.id}")
    assert response.status_code == 403


def test_field_assigned_profit_loss_allowed(field_client, field_user, project_a):
    ProjectAssignment.objects.create(user=field_user, project=project_a, is_active=True)
    response = field_client.get(f"/api/profit-loss/?project_id={project_a.id}")
    assert response.status_code == 200


def test_hq_access_any_project(hq_client, project_a, project_b):
    response_a = hq_client.get(f"/api/progress/?project_id={project_a.id}")
    response_b = hq_client.get(f"/api/profit-loss/?project_id={project_b.id}")
    assert response_a.status_code == 200
    assert response_b.status_code == 200


def test_field_ceo_api_forbidden(field_client):
    response = field_client.get("/api/ceo/dashboard/")
    assert response.status_code == 403
