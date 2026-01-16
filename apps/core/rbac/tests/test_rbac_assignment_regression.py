import pytest
from django.contrib.auth import get_user_model
from django.core.files.uploadedfile import SimpleUploadedFile
from rest_framework.test import APIClient

from apps.contracts.models import ContractChange
from apps.core.rbac.models import ProjectAssignment, UserProfile
from apps.evidence.models import Evidence, EvidenceFile
from apps.projects.models import Project


@pytest.fixture
def project_a(db):
    return Project.objects.create(code="PRJ-RBAC-A", name="RBAC Project A")


@pytest.fixture
def project_b(db):
    return Project.objects.create(code="PRJ-RBAC-B", name="RBAC Project B")


@pytest.fixture
def field_user(db):
    user = get_user_model().objects.create_user(username="field-user", password="pass")
    UserProfile.objects.create(user=user, role="field")
    return user


@pytest.fixture
def hq_user(db):
    user = get_user_model().objects.create_user(username="hq-user", password="pass")
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


def _create_evidence_file(project, user):
    change = ContractChange.objects.create(
        project=project,
        change_no=1,
        change_type="design_change",
        reason="RBAC evidence",
        contract_amount_delta="100.00",
        time_extension_days=1,
        status="draft",
    )
    evidence = Evidence.objects.create(
        title="RBAC Evidence",
        description="",
        object_type="CONTRACT_CHANGE",
        object_id=change.id,
        created_by=user,
    )
    upload = SimpleUploadedFile(
        "rbac.txt", b"rbac", content_type="text/plain"
    )
    return EvidenceFile.objects.create(
        evidence=evidence,
        file=upload,
        original_name="rbac.txt",
        content_type="text/plain",
        size_bytes=4,
        created_by=user,
    )


def test_field_unassigned_progress_forbidden(field_client, project_a):
    response = field_client.get(f"/api/progress/?project_id={project_a.id}")
    assert response.status_code == 403


def test_field_assigned_progress_allowed(field_client, field_user, project_a):
    ProjectAssignment.objects.create(user=field_user, project=project_a, is_active=True)
    response = field_client.get(f"/api/progress/?project_id={project_a.id}")
    assert response.status_code == 200


def test_field_unassigned_profit_loss_forbidden(field_client, project_a):
    response = field_client.get(f"/api/profit-loss/?project_id={project_a.id}")
    assert response.status_code == 403


def test_field_assigned_profit_loss_allowed(field_client, field_user, project_a):
    ProjectAssignment.objects.create(user=field_user, project=project_a, is_active=True)
    response = field_client.get(f"/api/profit-loss/?project_id={project_a.id}")
    assert response.status_code == 200


def test_field_unassigned_evidence_download_forbidden(
    field_client, field_user, project_a
):
    evidence_file = _create_evidence_file(project_a, field_user)
    response = field_client.get(f"/api/evidence-files/{evidence_file.id}/download/")
    assert response.status_code == 403


def test_hq_access_all(hq_client, hq_user, project_a, project_b):
    evidence_file = _create_evidence_file(project_b, hq_user)
    progress = hq_client.get(f"/api/progress/?project_id={project_a.id}")
    profit_loss = hq_client.get(f"/api/profit-loss/?project_id={project_b.id}")
    download = hq_client.get(f"/api/evidence-files/{evidence_file.id}/download/")
    assert progress.status_code == 200
    assert profit_loss.status_code == 200
    assert download.status_code == 200
