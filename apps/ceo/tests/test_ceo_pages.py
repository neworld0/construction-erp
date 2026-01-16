import pytest
from django.contrib.auth import get_user_model
from django.test import Client

from apps.core.rbac.models import UserProfile
from apps.projects.models import Project


@pytest.fixture
def client():
    return Client()


@pytest.fixture
def user(db):
    user = get_user_model().objects.create_user(username="tester", password="pass")
    UserProfile.objects.create(user=user, role="ceo")
    return user


def test_dashboard_requires_login(client):
    response = client.get("/ceo/dashboard/")
    assert response.status_code in (302, 403)


def test_dashboard_login_success(client, user):
    client.force_login(user)
    response = client.get("/ceo/dashboard/")
    assert response.status_code == 200


def test_project_detail_smoke(client, user):
    project = Project.objects.create(code="PRJ-CEO-UI-001", name="CEO UI Project")
    client.force_login(user)
    response = client.get(f"/ceo/projects/{project.id}/")
    assert response.status_code == 200
