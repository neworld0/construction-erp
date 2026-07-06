import pytest
from django.contrib.auth import get_user_model
from django.test import Client
from django.urls import resolve

from apps.core.rbac.models import Role, UserProfile


@pytest.fixture(autouse=True)
def _disable_two_factor_enforce(settings):
    settings.MIDDLEWARE = [
        middleware
        for middleware in settings.MIDDLEWARE
        if middleware != "apps.core.middleware.two_factor_enforce.TwoFactorEnforceMiddleware"
    ]


def _client_for(role, username):
    user = get_user_model().objects.create_user(username=username, password="pass")
    UserProfile.objects.create(user=user, role=role)
    client = Client()
    client.force_login(user)
    return client


@pytest.mark.django_db
@pytest.mark.parametrize(
    ("source", "target"),
    [
        ("/app/hq/labor/payroll/", "/app/hq/labor/payroll-allocation/"),
        ("/app/hq/labor/payroll/new/", "/app/hq/labor/payroll-allocation/new/"),
        ("/app/hq/labor/payroll/123/", "/app/hq/labor/payroll-allocation/123/"),
    ],
)
def test_audit1_labor_payroll_legacy_redirects_resolve_to_valid_targets(source, target):
    response = _client_for(Role.HQ, f"audit1-redirect-{abs(hash(source))}").get(source)

    assert response.status_code in (301, 302)
    assert response.headers["Location"] == target
    assert resolve(target).func is not None
    assert response.url != source


@pytest.mark.django_db
def test_audit1_ceo_cbs_duplicate_route_redirects_to_canonical_cbs():
    response = _client_for(Role.CEO, "audit1-ceo-cbs-redirect").get("/app/ceo/cbs/cbs/")

    assert response.status_code in (301, 302)
    assert response.headers["Location"] == "/app/ceo/cbs/"
    assert resolve("/app/ceo/cbs/").func is not None
