import pytest
from django.contrib.auth import get_user_model
from rest_framework.test import APIClient

from apps.cost.models import CostActual, CostItem
from apps.core.models import ApprovalRequest, ApprovalStatus
from apps.field.models import DailyReport, DailyReportLine
from apps.projects.models import Project


@pytest.fixture
def auth_client(db):
    client = APIClient()
    user = get_user_model().objects.create_user(username="tester", password="pass")
    client.force_authenticate(user=user)
    return client


@pytest.fixture
def project(db):
    return Project.objects.create(code="PRJ-AP-001", name="Approval Project")


@pytest.fixture
def cost_item(db):
    return CostItem.objects.create(
        code="COST-AP-001",
        name="Labor",
        category="labor",
        unit="hour",
        is_direct=True,
        sort_order=1,
        is_active=True,
    )


def _create_daily_report(project, reporter):
    report = DailyReport.objects.create(
        project=project,
        report_date="2024-01-01",
        reporter=reporter,
        status="submitted",
    )
    return report


def _add_line(report, cost_item):
    return DailyReportLine.objects.create(
        report=report,
        cost_item=cost_item,
        description="Work",
        quantity=1,
        unit_price=100,
    )


def _create_cost_actual_from_report(auth_client, report_id):
    return auth_client.post(
        "/api/cost-actuals/from-daily-report/",
        {"daily_report_id": report_id},
        format="json",
    )


def test_submit_requires_cost_actual(auth_client):
    response = auth_client.post(
        "/api/approvals/submit/",
        {"object_type": "COST_ACTUAL", "object_id": 9999},
        format="json",
    )

    assert response.status_code in (400, 404)


def test_submit_success_creates_submitted(auth_client, project, cost_item):
    user = get_user_model().objects.get(username="tester")
    report = _create_daily_report(project, user)
    _add_line(report, cost_item)
    cost_actual_response = _create_cost_actual_from_report(auth_client, report.id)
    cost_actual_id = cost_actual_response.json()["id"]

    response = auth_client.post(
        "/api/approvals/submit/",
        {"object_type": "COST_ACTUAL", "object_id": cost_actual_id},
        format="json",
    )

    assert response.status_code == 201
    assert response.json()["status"] == "submitted"


def test_approve_requires_submitted(auth_client, project, cost_item):
    user = get_user_model().objects.get(username="tester")
    report = _create_daily_report(project, user)
    _add_line(report, cost_item)
    cost_actual_response = _create_cost_actual_from_report(auth_client, report.id)
    cost_actual_id = cost_actual_response.json()["id"]

    approval = ApprovalRequest.objects.create(
        object_type="COST_ACTUAL",
        object_id=cost_actual_id,
        status=ApprovalStatus.DRAFT,
    )

    response = auth_client.post(f"/api/approvals/{approval.id}/approve/", format="json")

    assert response.status_code == 400


def test_approve_success_syncs_cost_actual(auth_client, project, cost_item):
    user = get_user_model().objects.get(username="tester")
    report = _create_daily_report(project, user)
    _add_line(report, cost_item)
    cost_actual_response = _create_cost_actual_from_report(auth_client, report.id)
    cost_actual_id = cost_actual_response.json()["id"]

    submit_response = auth_client.post(
        "/api/approvals/submit/",
        {"object_type": "COST_ACTUAL", "object_id": cost_actual_id},
        format="json",
    )
    approval_id = submit_response.json()["id"]

    response = auth_client.post(f"/api/approvals/{approval_id}/approve/", format="json")

    assert response.status_code == 200
    assert response.json()["status"] == "approved"
    assert CostActual.objects.get(id=cost_actual_id).status == "approved"


def test_reject_success_syncs_cost_actual(auth_client, project, cost_item):
    user = get_user_model().objects.get(username="tester")
    report = _create_daily_report(project, user)
    _add_line(report, cost_item)
    cost_actual_response = _create_cost_actual_from_report(auth_client, report.id)
    cost_actual_id = cost_actual_response.json()["id"]

    submit_response = auth_client.post(
        "/api/approvals/submit/",
        {"object_type": "COST_ACTUAL", "object_id": cost_actual_id},
        format="json",
    )
    approval_id = submit_response.json()["id"]

    response = auth_client.post(
        f"/api/approvals/{approval_id}/reject/",
        {"reject_reason": "Invalid"},
        format="json",
    )

    assert response.status_code == 200
    assert response.json()["status"] == "rejected"
    assert CostActual.objects.get(id=cost_actual_id).status == "rejected"


def test_submit_upsert_single_approval(auth_client, project, cost_item):
    user = get_user_model().objects.get(username="tester")
    report = _create_daily_report(project, user)
    _add_line(report, cost_item)
    cost_actual_response = _create_cost_actual_from_report(auth_client, report.id)
    cost_actual_id = cost_actual_response.json()["id"]

    auth_client.post(
        "/api/approvals/submit/",
        {"object_type": "COST_ACTUAL", "object_id": cost_actual_id},
        format="json",
    )
    auth_client.post(
        "/api/approvals/submit/",
        {"object_type": "COST_ACTUAL", "object_id": cost_actual_id},
        format="json",
    )

    assert ApprovalRequest.objects.filter(
        object_type="COST_ACTUAL", object_id=cost_actual_id
    ).count() == 1
