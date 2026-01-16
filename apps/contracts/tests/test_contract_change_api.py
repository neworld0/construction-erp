import pytest
from django.contrib.auth import get_user_model
from rest_framework.test import APIClient

from apps.contracts.models import ContractChange
from apps.projects.models import Project


@pytest.fixture
def auth_client(db):
    client = APIClient()
    user = get_user_model().objects.create_user(username="tester", password="pass")
    client.force_authenticate(user=user)
    return client


@pytest.fixture
def project(db):
    return Project.objects.create(code="PRJ-CC-001", name="Contract Change Project")


def _create_change(auth_client, project, payload=None):
    base = {
        "project": project.id,
        "change_type": "design_change",
        "reason": "Design update",
        "contract_amount_delta": "1000.00",
        "time_extension_days": 5,
    }
    if payload:
        base.update(payload)
    return auth_client.post("/api/contract-changes/", base, format="json")


def test_submit_and_approve_flow(auth_client, project):
    create_resp = _create_change(auth_client, project)
    change_id = create_resp.json()["id"]

    submit_resp = auth_client.post(f"/api/contract-changes/{change_id}/submit/")
    assert submit_resp.status_code == 200
    assert submit_resp.json()["status"] == "submitted"

    approve_resp = auth_client.post(f"/api/contract-changes/{change_id}/approve/")
    assert approve_resp.status_code == 200
    assert approve_resp.json()["status"] == "approved"


def test_approved_change_cannot_update(auth_client, project):
    change_id = _create_change(auth_client, project).json()["id"]
    auth_client.post(f"/api/contract-changes/{change_id}/submit/")
    auth_client.post(f"/api/contract-changes/{change_id}/approve/")

    patch_resp = auth_client.patch(
        f"/api/contract-changes/{change_id}/",
        {"reason": "Edit"},
        format="json",
    )
    assert patch_resp.status_code in (400, 403)


def test_change_no_increments_per_project(auth_client, project):
    first = _create_change(auth_client, project).json()
    second = _create_change(auth_client, project).json()

    assert second["change_no"] == first["change_no"] + 1


def test_reject_only_submitted(auth_client, project):
    change_id = _create_change(auth_client, project).json()["id"]

    reject_resp = auth_client.post(f"/api/contract-changes/{change_id}/reject/")
    assert reject_resp.status_code == 400


def test_submit_only_draft(auth_client, project):
    change_id = _create_change(auth_client, project).json()["id"]
    auth_client.post(f"/api/contract-changes/{change_id}/submit/")
    second_submit = auth_client.post(f"/api/contract-changes/{change_id}/submit/")

    assert second_submit.status_code == 400
