import csv
from io import StringIO

import pytest
from django.contrib.auth import get_user_model
from rest_framework.test import APIClient

from apps.core.rbac.models import Role, UserProfile
from apps.projects.models import Project


CSV_URL = "/api/ceo/reports/project-summary.csv"
CSV_HEADERS = [
    "project_id",
    "project_name",
    "snapshot_version_no",
    "overall_progress_percent",
    "recognized_revenue",
    "accrual_cost",
    "profit",
    "margin_percent",
    "risk_open_count",
    "risk_critical_count",
]


def _user(role, username):
    user = get_user_model().objects.create_user(username=username, password="pass")
    UserProfile.objects.create(user=user, role=role)
    return user


def _client(user):
    client = APIClient()
    client.force_authenticate(user=user)
    return client


def _project():
    return Project.objects.create(
        code="CSV-UTF8-BOM", name="2026년 8월 로컬 검증 포장보수공사", project_type="civil"
    )


@pytest.mark.django_db
def test_ceo_project_summary_csv_starts_with_utf8_bom():
    ceo = _user(Role.CEO, "csv-bom-ceo")
    project = _project()

    response = _client(ceo).get(CSV_URL)
    content = bytes(response.content)

    assert response.status_code == 200
    assert response["Content-Type"].startswith("text/csv; charset=utf-8")
    assert content.startswith(b"\xef\xbb\xbf")
    decoded = content.decode("utf-8-sig")
    assert project.name in decoded
    assert "�" not in decoded


@pytest.mark.django_db
def test_ceo_project_summary_csv_headers_remain_stable():
    ceo = _user(Role.CEO, "csv-bom-header")

    response = _client(ceo).get(CSV_URL)
    header = next(csv.reader(StringIO(response.content.decode("utf-8-sig"))))

    assert header == CSV_HEADERS
    assert "sep=," not in response.content.decode("utf-8-sig")


@pytest.mark.django_db
def test_field_cannot_download_ceo_project_summary_csv():
    field = _user(Role.FIELD, "csv-bom-field")

    response = _client(field).get(CSV_URL)

    assert response.status_code == 403
    assert not response["Content-Type"].startswith("text/csv")


@pytest.mark.django_db
def test_anonymous_cannot_download_ceo_project_summary_csv():
    response = APIClient().get(CSV_URL)

    assert response.status_code in {401, 403}
    assert not response.get("Content-Type", "").startswith("text/csv")


@pytest.mark.django_db
def test_ceo_project_summary_csv_empty_projects_still_has_bom_and_header():
    ceo = _user(Role.CEO, "csv-bom-empty")

    response = _client(ceo).get(CSV_URL)
    decoded = response.content.decode("utf-8-sig")

    assert response.status_code == 200
    assert response.content.startswith(b"\xef\xbb\xbf")
    assert next(csv.reader(StringIO(decoded))) == CSV_HEADERS
    assert "�" not in decoded
