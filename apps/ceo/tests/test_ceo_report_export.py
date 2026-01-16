import pytest
from django.contrib.auth import get_user_model
from rest_framework.test import APIClient

from apps.audit.constants import REPORT_EXPORT
from apps.audit.models import AuditLog
from apps.contracts.models import ContractSnapshot
from apps.core.rbac.models import UserProfile
from apps.projects.models import Project


@pytest.fixture
def project(db):
    return Project.objects.create(code="PRJ-CSV-001", name="CSV Project")


@pytest.fixture
def field_client(db):
    client = APIClient()
    user = get_user_model().objects.create_user(username="field-csv", password="pass")
    UserProfile.objects.create(user=user, role="field")
    client.force_authenticate(user=user)
    return client


@pytest.fixture
def hq_client(db):
    client = APIClient()
    user = get_user_model().objects.create_user(username="hq-csv", password="pass")
    UserProfile.objects.create(user=user, role="hq")
    client.force_authenticate(user=user)
    return client


def test_field_forbidden(field_client):
    response = field_client.get("/api/ceo/reports/project-summary.csv")
    assert response.status_code == 403


def test_hq_csv_headers_and_audit(hq_client, project):
    ContractSnapshot.objects.create(
        project=project,
        version_no=1,
        base_contract_amount="1000.00",
        is_active=True,
    )
    response = hq_client.get("/api/ceo/reports/project-summary.csv")
    assert response.status_code == 200
    assert response["Content-Type"].startswith("text/csv")
    assert "attachment" in response["Content-Disposition"]
    assert "project-summary.csv" in response["Content-Disposition"]
    assert AuditLog.objects.filter(action=REPORT_EXPORT).exists()
