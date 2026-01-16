from django.contrib.auth import get_user_model
from django.core.exceptions import ValidationError
from django.core.files.uploadedfile import SimpleUploadedFile
from rest_framework.test import APIClient
import pytest

from apps.contracts.models import ContractChange
from apps.evidence.models import Evidence, EvidenceFile, EvidencePolicy
from apps.projects.models import Project
from apps.schedule.models import SchedulePlan
from apps.core.rbac.models import UserProfile


@pytest.fixture
def auth_client(db):
    client = APIClient()
    user = get_user_model().objects.create_user(username="tester", password="pass")
    UserProfile.objects.create(user=user, role="hq")
    client.force_authenticate(user=user)
    return client


@pytest.fixture
def project(db):
    return Project.objects.create(code="PRJ-EV-001", name="Evidence Project")


def _create_contract_change(auth_client, project):
    payload = {
        "project": project.id,
        "change_type": "design_change",
        "reason": "Design update",
        "contract_amount_delta": "100.00",
        "time_extension_days": 1,
    }
    response = auth_client.post("/api/contract-changes/", payload, format="json")
    return response.json()["id"]


def _create_plan_change_request(auth_client, project):
    base_plan = SchedulePlan.objects.create(project=project, version_no=1, is_active=True)
    payload = {
        "project": project.id,
        "base_plan": base_plan.id,
        "change_type": "field_request",
        "reason": "Site change",
        "proposed_payload": [{"name": "New Task", "weight_percent": 100}],
    }
    response = auth_client.post("/api/plan-change-requests/", payload, format="json")
    return response.json()["id"]


def _create_evidence(user, object_type, object_id):
    return Evidence.objects.create(
        title="Evidence",
        description="",
        object_type=object_type,
        object_id=object_id,
        created_by=user,
    )


def _upload_file(auth_client, evidence_id, name="evidence.txt", content=b"hello", content_type="text/plain"):
    file_obj = SimpleUploadedFile(name=name, content=content, content_type=content_type)
    return auth_client.post(
        f"/api/evidence/{evidence_id}/files/",
        {"file": file_obj},
        format="multipart",
    )


def test_evidence_file_sha256_saved(auth_client, project):
    user = get_user_model().objects.get(username="tester")
    evidence = _create_evidence(user, "CONTRACT_CHANGE", 1)

    response = _upload_file(auth_client, evidence.id, content=b"sha-test")

    assert response.status_code == 201
    file_id = response.json()["id"]
    saved = EvidenceFile.objects.get(id=file_id)
    assert saved.sha256
    assert len(saved.sha256) == 64


def test_policy_required_blocks_without_evidence(auth_client, project):
    change_id = _create_contract_change(auth_client, project)
    EvidencePolicy.objects.create(
        object_type="CONTRACT_CHANGE",
        when_status="SUBMIT",
        is_required=True,
        min_files=1,
    )

    response = auth_client.post(f"/api/contract-changes/{change_id}/submit/")

    assert response.status_code == 400


def test_policy_required_blocks_with_zero_files(auth_client, project):
    change_id = _create_contract_change(auth_client, project)
    EvidencePolicy.objects.create(
        object_type="CONTRACT_CHANGE",
        when_status="SUBMIT",
        is_required=True,
        min_files=1,
    )
    user = get_user_model().objects.get(username="tester")
    _create_evidence(user, "CONTRACT_CHANGE", change_id)

    response = auth_client.post(f"/api/contract-changes/{change_id}/submit/")

    assert response.status_code == 400


def test_policy_allows_after_file_upload(auth_client, project):
    change_id = _create_contract_change(auth_client, project)
    EvidencePolicy.objects.create(
        object_type="CONTRACT_CHANGE",
        when_status="SUBMIT",
        is_required=True,
        min_files=1,
    )
    user = get_user_model().objects.get(username="tester")
    evidence = _create_evidence(user, "CONTRACT_CHANGE", change_id)
    _upload_file(auth_client, evidence.id)

    response = auth_client.post(f"/api/contract-changes/{change_id}/submit/")

    assert response.status_code == 200


def test_policy_allowed_types_blocks_mismatch(auth_client, project):
    change_id = _create_contract_change(auth_client, project)
    EvidencePolicy.objects.create(
        object_type="CONTRACT_CHANGE",
        when_status="SUBMIT",
        is_required=True,
        min_files=1,
        allowed_types=["application/pdf"],
    )
    user = get_user_model().objects.get(username="tester")
    evidence = _create_evidence(user, "CONTRACT_CHANGE", change_id)
    _upload_file(auth_client, evidence.id, name="photo.jpg", content_type="image/jpeg")

    response = auth_client.post(f"/api/contract-changes/{change_id}/submit/")

    assert response.status_code == 400


def test_evidence_file_immutable_on_update(auth_client, project):
    user = get_user_model().objects.get(username="tester")
    evidence = _create_evidence(user, "PLAN_CHANGE_REQUEST", 1)
    upload = _upload_file(auth_client, evidence.id)
    file_id = upload.json()["id"]
    evidence_file = EvidenceFile.objects.get(id=file_id)

    new_file = SimpleUploadedFile(name="new.txt", content=b"new", content_type="text/plain")
    evidence_file.file = new_file
    with pytest.raises(ValidationError):
        evidence_file.save()
