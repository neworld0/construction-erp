import pytest
from django.contrib.auth import get_user_model
from rest_framework.test import APIClient

from apps.contracts.models import ContractChange
from apps.projects.models import Project
from apps.schedule.models import DailyProgress, PlanChangeRequest, SchedulePlan, ScheduleTask
from apps.schedule.services.progress_agg import get_project_progress


@pytest.fixture
def auth_client(db):
    client = APIClient()
    user = get_user_model().objects.create_user(username="tester", password="pass")
    client.force_authenticate(user=user)
    return client


@pytest.fixture
def project(db):
    return Project.objects.create(code="PRJ-PC-001", name="Plan Change Project")


@pytest.fixture
def base_plan(project, db):
    return SchedulePlan.objects.create(project=project, version_no=1, is_active=True)


@pytest.fixture
def base_task(base_plan, db):
    return ScheduleTask.objects.create(
        plan=base_plan, name="Base Task", weight_percent=50, sort_order=1
    )


def _create_change_request(auth_client, project, base_plan):
    payload = {
        "project": project.id,
        "base_plan": base_plan.id,
        "change_type": "field_request",
        "reason": "Adjust tasks",
        "proposed_payload": [
            {"name": "New Task", "weight_percent": 100, "sort_order": 1}
        ],
    }
    return auth_client.post("/api/plan-change-requests/", payload, format="json")


def test_approve_versions_up(auth_client, project, base_plan):
    create_resp = _create_change_request(auth_client, project, base_plan)
    change_id = create_resp.json()["id"]
    auth_client.post(f"/api/plan-change-requests/{change_id}/submit/")

    approve_resp = auth_client.post(f"/api/plan-change-requests/{change_id}/approve/")
    assert approve_resp.status_code == 200

    assert SchedulePlan.objects.filter(project=project).count() == 2
    latest = SchedulePlan.objects.filter(project=project).order_by("-version_no").first()
    assert latest.version_no == 2


def test_active_plan_single(auth_client, project, base_plan):
    create_resp = _create_change_request(auth_client, project, base_plan)
    change_id = create_resp.json()["id"]
    auth_client.post(f"/api/plan-change-requests/{change_id}/submit/")
    auth_client.post(f"/api/plan-change-requests/{change_id}/approve/")

    assert SchedulePlan.objects.filter(project=project, is_active=True).count() == 1


def test_only_draft_can_submit(auth_client, project, base_plan):
    create_resp = _create_change_request(auth_client, project, base_plan)
    change_id = create_resp.json()["id"]

    first = auth_client.post(f"/api/plan-change-requests/{change_id}/submit/")
    assert first.status_code == 200

    second = auth_client.post(f"/api/plan-change-requests/{change_id}/submit/")
    assert second.status_code == 400


def test_only_submitted_can_approve(auth_client, project, base_plan):
    create_resp = _create_change_request(auth_client, project, base_plan)
    change_id = create_resp.json()["id"]

    response = auth_client.post(f"/api/plan-change-requests/{change_id}/approve/")
    assert response.status_code == 400


def test_progress_uses_new_plan(auth_client, project, base_plan, base_task):
    create_resp = _create_change_request(auth_client, project, base_plan)
    change_id = create_resp.json()["id"]
    auth_client.post(f"/api/plan-change-requests/{change_id}/submit/")
    auth_client.post(f"/api/plan-change-requests/{change_id}/approve/")

    new_plan = SchedulePlan.objects.filter(project=project, is_active=True).first()
    new_task = ScheduleTask.objects.filter(plan=new_plan).first()
    user = get_user_model().objects.get(username="tester")

    DailyProgress.objects.create(
        project=project,
        plan=new_plan,
        task=new_task,
        report_date="2024-01-01",
        progress_percent=50,
        reporter=user,
    )

    progress = get_project_progress(project.id, None)
    assert progress["plan_id"] == new_plan.id


def _create_contract_change(auth_client, project, status=None):
    payload = {
        "project": project.id,
        "change_type": "change_order",
        "reason": "Extra work",
        "contract_amount_delta": "500.00",
        "time_extension_days": 2,
    }
    response = auth_client.post("/api/contract-changes/", payload, format="json")
    if status:
        ContractChange.objects.filter(id=response.json()["id"]).update(status=status)
    return response


def test_change_order_requires_contract_change_on_submit(auth_client, project, base_plan):
    payload = {
        "project": project.id,
        "base_plan": base_plan.id,
        "change_type": "change_order",
        "reason": "Extra work",
        "proposed_payload": [{"name": "New Task", "weight_percent": 100}],
    }
    create_resp = auth_client.post("/api/plan-change-requests/", payload, format="json")
    change_id = create_resp.json()["id"]

    submit_resp = auth_client.post(f"/api/plan-change-requests/{change_id}/submit/")

    assert submit_resp.status_code == 400


def test_change_order_approve_requires_approved_contract_change(
    auth_client, project, base_plan
):
    contract_change = _create_contract_change(auth_client, project, status="submitted").json()
    payload = {
        "project": project.id,
        "base_plan": base_plan.id,
        "change_type": "change_order",
        "reason": "Extra work",
        "contract_change": contract_change["id"],
        "proposed_payload": [{"name": "New Task", "weight_percent": 100}],
    }
    create_resp = auth_client.post("/api/plan-change-requests/", payload, format="json")
    change_id = create_resp.json()["id"]
    auth_client.post(f"/api/plan-change-requests/{change_id}/submit/")

    approve_resp = auth_client.post(f"/api/plan-change-requests/{change_id}/approve/")

    assert approve_resp.status_code == 400


def test_change_order_approve_with_approved_contract_change(auth_client, project, base_plan):
    contract_change = _create_contract_change(auth_client, project, status="approved").json()
    payload = {
        "project": project.id,
        "base_plan": base_plan.id,
        "change_type": "change_order",
        "reason": "Extra work",
        "contract_change": contract_change["id"],
        "proposed_payload": [{"name": "New Task", "weight_percent": 100}],
    }
    create_resp = auth_client.post("/api/plan-change-requests/", payload, format="json")
    change_id = create_resp.json()["id"]
    auth_client.post(f"/api/plan-change-requests/{change_id}/submit/")

    approve_resp = auth_client.post(f"/api/plan-change-requests/{change_id}/approve/")

    assert approve_resp.status_code == 200


def test_field_request_can_approve_without_contract_change(auth_client, project, base_plan):
    payload = {
        "project": project.id,
        "base_plan": base_plan.id,
        "change_type": "field_request",
        "reason": "Site request",
        "proposed_payload": [{"name": "New Task", "weight_percent": 100}],
    }
    create_resp = auth_client.post("/api/plan-change-requests/", payload, format="json")
    change_id = create_resp.json()["id"]
    auth_client.post(f"/api/plan-change-requests/{change_id}/submit/")

    approve_resp = auth_client.post(f"/api/plan-change-requests/{change_id}/approve/")

    assert approve_resp.status_code == 200
