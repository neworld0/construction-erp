import pytest
from django.contrib.auth import get_user_model
from django.test import Client

from apps.core.rbac.models import Role, UserProfile
from apps.labor.models import LaborRole, WorkerMaster
from apps.labor.role_master import LOCAL_OPS_LABOR_ROLE_SPECS, seed_local_ops_labor_roles


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


@pytest.mark.django_db
def test_hq_worker_registration_dropdown_includes_local_ops_roles():
    seed_local_ops_labor_roles()
    hq_user = _user(Role.HQ, "labor-role-hq")

    response = _client(hq_user).get("/app/hq/labor/workers/new/")

    assert response.status_code == 200
    content = response.content.decode()
    for _code, name, _group, _sort_order in LOCAL_OPS_LABOR_ROLE_SPECS:
        assert name in content
    assert "???" not in content


@pytest.mark.django_db
def test_labor_role_seed_is_idempotent():
    first = seed_local_ops_labor_roles()
    count_after_first = LaborRole.objects.filter(
        code__in=[spec[0] for spec in LOCAL_OPS_LABOR_ROLE_SPECS]
    ).count()
    second = seed_local_ops_labor_roles()

    assert count_after_first == len(LOCAL_OPS_LABOR_ROLE_SPECS)
    assert not second["created"]
    assert LaborRole.objects.filter(code="LAB-EQP", name="장비공", is_active=True).exists()
    assert len(first["created"]) + len(first["updated"]) + len(first["unchanged"]) == 5


@pytest.mark.django_db
def test_hq_worker_registration_saves_selected_default_labor_role():
    seed_local_ops_labor_roles()
    hq_user = _user(Role.HQ, "labor-role-save-hq")
    role = LaborRole.objects.get(code="LAB-EQP")

    response = _client(hq_user).post(
        "/app/hq/labor/workers/new/",
        {
            "name": "테스트장비공",
            "rrn": "900101-1234567",
            "default_labor_role": role.id,
            "retirement_deduction_eligible": "on",
            "active": "on",
        },
    )

    assert response.status_code == 302
    assert WorkerMaster.objects.get(name="테스트장비공").default_labor_role == role


@pytest.mark.django_db
def test_inactive_labor_roles_are_not_shown_in_worker_registration_dropdown():
    LaborRole.objects.create(code="LAB-OLD", name="사용중지직종", is_active=False)
    hq_user = _user(Role.HQ, "labor-role-inactive-hq")

    response = _client(hq_user).get("/app/hq/labor/workers/new/")

    assert response.status_code == 200
    assert "사용중지직종" not in response.content.decode()


@pytest.mark.django_db
def test_field_cannot_access_hq_worker_registration_after_role_expansion():
    seed_local_ops_labor_roles()
    field_user = _user(Role.FIELD, "labor-role-field")

    response = _client(field_user).get("/app/hq/labor/workers/new/")

    assert response.status_code == 403
