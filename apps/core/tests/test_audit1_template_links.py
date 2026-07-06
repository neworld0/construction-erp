from html.parser import HTMLParser
from urllib.parse import urlsplit

import pytest
from django.contrib.auth import get_user_model
from django.test import Client
from django.urls import Resolver404, resolve

from apps.core.rbac.models import ProjectAssignment, Role, UserProfile
from apps.projects.models import Project, WBSItem


@pytest.fixture(autouse=True)
def _disable_two_factor_enforce(settings):
    settings.MIDDLEWARE = [
        middleware
        for middleware in settings.MIDDLEWARE
        if middleware != "apps.core.middleware.two_factor_enforce.TwoFactorEnforceMiddleware"
    ]


class LinkParser(HTMLParser):
    def __init__(self):
        super().__init__()
        self.links = []

    def handle_starttag(self, tag, attrs):
        attrs = dict(attrs)
        if "href" in attrs:
            self.links.append(("href", attrs["href"]))
        if "action" in attrs:
            self.links.append(("action", attrs["action"]))


def _user(role, username):
    user = get_user_model().objects.create_user(username=username, password="pass")
    UserProfile.objects.create(user=user, role=role)
    return user


def _client(user):
    client = Client()
    client.force_login(user)
    return client


def _project():
    return Project.objects.create(
        code="AUDIT1-LINK-001",
        name="AUDIT1 Link Project",
        project_type="civil",
    )


def _field_url_for(user):
    project = _project()
    WBSItem.objects.create(
        project=project,
        name="AUDIT1 Link WBS",
        weight="100.00",
        sort_order=1,
        is_baseline=True,
    )
    ProjectAssignment.objects.create(user=user, project=project, is_active=True)
    return f"/app/field/?tab=progress&project_id={project.id}"


def _extract_internal_links(html):
    parser = LinkParser()
    parser.feed(html)
    for attr, raw_value in parser.links:
        value = (raw_value or "").strip()
        if not value:
            continue
        lower = value.lower()
        if (
            value.startswith("#")
            or value.startswith("?")
            or lower.startswith(("javascript:", "mailto:", "tel:", "http://", "https://"))
            or value.startswith(("/static/", "/media/"))
        ):
            continue
        if not value.startswith("/"):
            continue
        yield attr, value


def _assert_rendered_internal_links_resolve(client, page_url):
    response = client.get(page_url)
    assert response.status_code == 200
    html = response.content.decode("utf-8")
    broken = []
    for attr, link in _extract_internal_links(html):
        if "{{" in link or "{%" in link:
            broken.append((attr, link, "unresolved template placeholder"))
            continue
        path = urlsplit(link).path or "/"
        try:
            resolve(path)
        except Resolver404:
            broken.append((attr, link, "resolver 404"))
    assert not broken, f"{page_url} rendered broken internal links/actions: {broken}"


@pytest.mark.django_db
@pytest.mark.parametrize(
    "page_url",
    [
        "/app/hq/",
        "/app/hq/projects/",
        "/app/hq/labor/e-card-imports/",
        "/app/hq/labor/workers/",
        "/app/hq/labor/work-ledger/",
        "/app/hq/labor/reporting-map/",
        "/app/hq/labor/monthly-payroll/",
        "/app/hq/labor/payroll-allocation/",
    ],
)
def test_audit1_hq_rendered_internal_links_resolve(page_url):
    hq_user = _user(Role.HQ, f"audit1-link-hq-{abs(hash(page_url))}")

    _assert_rendered_internal_links_resolve(_client(hq_user), page_url)


@pytest.mark.django_db
def test_audit1_field_rendered_internal_links_resolve():
    field_user = _user(Role.FIELD, "audit1-link-field")

    _assert_rendered_internal_links_resolve(_client(field_user), _field_url_for(field_user))
