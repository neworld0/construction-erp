import pytest
from django.contrib.auth import get_user_model
from django.test import Client

from apps.core.rbac.models import ProjectAssignment, Role, UserProfile
from apps.projects.models import Project, WBSItem


@pytest.fixture(autouse=True)
def _disable_two_factor_enforce(settings):
    settings.MIDDLEWARE = [
        middleware
        for middleware in settings.MIDDLEWARE
        if middleware != "apps.core.middleware.two_factor_enforce.TwoFactorEnforceMiddleware"
    ]


def _user(role, username):
    user = get_user_model().objects.create_user(username=username, password="pass")
    UserProfile.objects.create(user=user, role=role)
    return user


def _client(user):
    client = Client()
    client.force_login(user)
    return client


def _project(code, name):
    return Project.objects.create(code=code, name=name, project_type="civil")


def _add_wbs(project, name="Scope WBS"):
    return WBSItem.objects.create(
        project=project,
        name=name,
        weight="100.00",
        sort_order=1,
        is_baseline=True,
    )


@pytest.mark.django_db
def test_assigned_field_user_can_access_field_project_view():
    field_user = _user(Role.FIELD, "field-scope-assigned")
    project = _project("PRJ-SCOPE-001", "Assigned Scope Project")
    _add_wbs(project, "Assigned Scope Task")
    ProjectAssignment.objects.create(user=field_user, project=project, is_active=True)

    response = _client(field_user).get(f"/app/field/?tab=progress&project_id={project.id}")

    assert response.status_code == 200
    content = response.content.decode("utf-8")
    assert "Assigned Scope Project" in content
    assert "Assigned Scope Task" in content


@pytest.mark.django_db
def test_unassigned_field_user_cannot_switch_query_string_to_other_project():
    field_user = _user(Role.FIELD, "field-scope-unassigned")
    assigned = _project("PRJ-SCOPE-002", "Allowed Scope Project")
    forbidden = _project("PRJ-SCOPE-003", "Forbidden Scope Project")
    _add_wbs(assigned, "Allowed Scope Task")
    _add_wbs(forbidden, "Forbidden Scope Task")
    ProjectAssignment.objects.create(user=field_user, project=assigned, is_active=True)

    response = _client(field_user).get(
        f"/app/field/?tab=progress&project_id={forbidden.id}"
    )

    assert response.status_code == 200
    content = response.content.decode("utf-8")
    assert "Forbidden Scope Project" not in content
    assert "Forbidden Scope Task" not in content
    assert "Allowed Scope Project" in content


@pytest.mark.django_db
def test_inactive_project_assignment_does_not_grant_field_access():
    field_user = _user(Role.FIELD, "field-scope-inactive")
    project = _project("PRJ-SCOPE-004", "Inactive Scope Project")
    _add_wbs(project, "Inactive Scope Task")
    ProjectAssignment.objects.create(user=field_user, project=project, is_active=False)

    response = _client(field_user).get(f"/app/field/?tab=progress&project_id={project.id}")

    assert response.status_code == 200
    content = response.content.decode("utf-8")
    assert "Inactive Scope Project" not in content
    assert "Inactive Scope Task" not in content


@pytest.mark.django_db
def test_hq_can_access_field_dashboard_for_any_project_scope():
    hq_user = _user(Role.HQ, "hq-scope")
    project = _project("PRJ-SCOPE-005", "HQ Scope Project")
    _add_wbs(project, "HQ Scope Task")

    response = _client(hq_user).get(f"/app/field/?tab=progress&project_id={project.id}")

    assert response.status_code == 200
    content = response.content.decode("utf-8")
    assert "HQ Scope Project" in content
