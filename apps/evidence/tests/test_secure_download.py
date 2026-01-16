import pytest
from django.contrib.auth import get_user_model
from django.core.files.uploadedfile import SimpleUploadedFile
from rest_framework.test import APIClient

from apps.audit.constants import FILE_DOWNLOAD
from apps.audit.models import AuditLog
from apps.contracts.models import ContractChange
from apps.core.rbac.models import ProjectAssignment, UserProfile
from apps.evidence.models import Evidence, EvidenceFile
from apps.projects.models import Project


@pytest.fixture
def project_a(db):
    return Project.objects.create(code="PRJ-DL-001", name="Download Project A")


@pytest.fixture
def project_b(db):
    return Project.objects.create(code="PRJ-DL-002", name="Download Project B")


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


def _create_evidence_file(project, created_by):
    change = ContractChange.objects.create(
        project=project,
        change_no=1,
        change_type="design_change",
        reason="Reason",
    )
    evidence = Evidence.objects.create(
        title="Evidence",
        description="",
        object_type="CONTRACT_CHANGE",
        object_id=change.id,
        created_by=created_by,
    )
    upload = SimpleUploadedFile("secure.txt", b"secure", content_type="text/plain")
    evidence_file = EvidenceFile.objects.create(
        evidence=evidence,
        file=upload,
        original_name=upload.name,
        content_type=upload.content_type or "",
        created_by=created_by,
    )
    return evidence_file


def test_download_requires_auth(project_a):
    evidence_file = _create_evidence_file(project_a, get_user_model().objects.create_user("u1"))
    client = APIClient()
    response = client.get(f"/api/evidence-files/{evidence_file.id}/download/")
    assert response.status_code in (401, 403)


def test_field_unassigned_download_forbidden(field_client, project_a):
    evidence_file = _create_evidence_file(project_a, field_client.handler._force_user)
    response = field_client.get(f"/api/evidence-files/{evidence_file.id}/download/")
    assert response.status_code == 403


def test_field_assigned_download_allowed(field_client, field_user, project_a):
    ProjectAssignment.objects.create(user=field_user, project=project_a, is_active=True)
    evidence_file = _create_evidence_file(project_a, field_user)
    response = field_client.get(f"/api/evidence-files/{evidence_file.id}/download/")
    assert response.status_code == 200


def test_hq_download_allowed(hq_client, project_b, hq_user):
    evidence_file = _create_evidence_file(project_b, hq_user)
    response = hq_client.get(f"/api/evidence-files/{evidence_file.id}/download/")
    assert response.status_code == 200


def test_download_creates_audit_log(hq_client, project_a, hq_user):
    evidence_file = _create_evidence_file(project_a, hq_user)
    response = hq_client.get(f"/api/evidence-files/{evidence_file.id}/download/")
    assert response.status_code == 200
    assert AuditLog.objects.filter(action=FILE_DOWNLOAD, object_id=evidence_file.id).exists()


def test_content_disposition_includes_original_name(hq_client, project_a, hq_user):
    evidence_file = _create_evidence_file(project_a, hq_user)
    response = hq_client.get(f"/api/evidence-files/{evidence_file.id}/download/")
    assert response.status_code == 200
    assert evidence_file.original_name in response["Content-Disposition"]
