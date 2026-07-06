import pytest
from django.contrib.auth import get_user_model
from django.test import Client
from django.urls import resolve

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


def _project(code="AUDIT1-URL-001", name="AUDIT1 URL Project"):
    return Project.objects.create(code=code, name=name, project_type="civil")


def _assign_field_project(user):
    project = _project("AUDIT1-FIELD-001", "AUDIT1 Field Project")
    WBSItem.objects.create(
        project=project,
        name="AUDIT1 Field Task",
        weight="100.00",
        sort_order=1,
        is_baseline=True,
    )
    ProjectAssignment.objects.create(user=user, project=project, is_active=True)
    return project


HQ_URLS = [
    "/app/hq/",
    "/app/hq/projects/",
    "/app/hq/projects/new/",
    "/app/hq/closing/",
    "/app/hq/master/cbs/",
    "/app/hq/master/labor/roles/",
    "/app/hq/master/labor/rates/",
    "/app/hq/master/warehouses/",
    "/app/hq/master/items/",
    "/app/hq/labor/workers/",
    "/app/hq/labor/workers/new/",
    "/app/hq/labor/work-ledger/",
    "/app/hq/labor/work-ledger/new/",
    "/app/hq/labor/reporting-map/",
    "/app/hq/labor/e-card-imports/",
    "/app/hq/labor/confirmed-work-days/",
    "/app/hq/labor/monthly-payroll/",
    "/app/hq/labor/payroll-allocation/",
    "/app/hq/labor/payroll-allocation/new/",
]


CEO_URLS = [
    "/app/ceo/",
    "/app/ceo/cbs/",
]


@pytest.mark.django_db
@pytest.mark.parametrize("url", HQ_URLS)
def test_audit1_hq_high_priority_urls_resolve_and_open(url):
    hq_user = _user(Role.HQ, f"audit1-hq-{abs(hash(url))}")

    match = resolve(url)
    response = _client(hq_user).get(url)

    assert match.func is not None
    assert response.status_code == 200


@pytest.mark.django_db
@pytest.mark.parametrize("url", CEO_URLS)
def test_audit1_ceo_high_priority_urls_resolve_and_open(url):
    ceo_user = _user(Role.CEO, f"audit1-ceo-{abs(hash(url))}")

    match = resolve(url)
    response = _client(ceo_user).get(url)

    assert match.func is not None
    assert response.status_code == 200


@pytest.mark.django_db
def test_audit1_field_dashboard_resolves_and_opens_for_assigned_project():
    field_user = _user(Role.FIELD, "audit1-field-user")
    project = _assign_field_project(field_user)
    url = f"/app/field/?tab=progress&project_id={project.id}"

    match = resolve("/app/field/")
    response = _client(field_user).get(url)

    assert match.func is not None
    assert response.status_code == 200
