import pytest
from django.contrib.auth import get_user_model
from django.test import Client

from apps.core.rbac.models import Role, UserProfile


@pytest.fixture(autouse=True)
def _disable_two_factor_enforce(settings):
    settings.MIDDLEWARE = [
        middleware
        for middleware in settings.MIDDLEWARE
        if middleware != "apps.core.middleware.two_factor_enforce.TwoFactorEnforceMiddleware"
    ]


def _client_for_role(role, username):
    user = get_user_model().objects.create_user(username=username, password="pass")
    UserProfile.objects.create(user=user, role=role)
    client = Client()
    client.force_login(user)
    return client


HQ_URLS = [
    "/app/hq/",
    "/app/hq/projects/",
    "/app/hq/closing/",
    "/app/hq/labor/workers/",
    "/app/hq/labor/work-ledger/",
    "/app/hq/labor/reporting-map/",
    "/app/hq/labor/e-card-imports/",
    "/app/hq/labor/confirmed-work-days/",
    "/app/hq/labor/monthly-payroll/",
    "/app/hq/labor/payroll-allocation/",
]


@pytest.mark.django_db
@pytest.mark.parametrize("url", HQ_URLS)
def test_field_user_is_blocked_from_hq_operational_urls(url):
    client = _client_for_role(Role.FIELD, f"field-{abs(hash(url))}")

    response = client.get(url)

    assert response.status_code == 403


@pytest.mark.django_db
@pytest.mark.parametrize("url", HQ_URLS)
def test_hq_user_can_open_hq_operational_urls(url):
    client = _client_for_role(Role.HQ, f"hq-{abs(hash(url))}")

    response = client.get(url)

    assert response.status_code in (200, 302)


@pytest.mark.django_db
@pytest.mark.parametrize("url", HQ_URLS)
def test_ceo_user_can_open_hq_operational_urls(url):
    client = _client_for_role(Role.CEO, f"ceo-{abs(hash(url))}")

    response = client.get(url)

    assert response.status_code in (200, 302)
