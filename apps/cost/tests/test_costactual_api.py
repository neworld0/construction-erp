import pytest
from django.contrib.auth import get_user_model
from rest_framework.test import APIClient

from apps.cost.models import CostActual, CostItem
from apps.field.models import DailyReport, DailyReportLine, DailyReportStatus
from apps.projects.models import Project


@pytest.fixture
def auth_client(db):
    client = APIClient()
    user = get_user_model().objects.create_user(username="tester", password="pass")
    client.force_authenticate(user=user)
    return client


@pytest.fixture
def project(db):
    return Project.objects.create(code="PRJ-CA-001", name="CostActual Project")


@pytest.fixture
def cost_item(db):
    return CostItem.objects.create(
        code="COST-CA-001",
        name="Labor",
        category="labor",
        unit="hour",
        is_direct=True,
        sort_order=1,
        is_active=True,
    )


def _create_daily_report(project, reporter, status=DailyReportStatus.DRAFT):
    report = DailyReport.objects.create(
        project=project,
        report_date="2024-01-01",
        reporter=reporter,
        status=status,
    )
    return report


def _add_line(report, cost_item, quantity=1, unit_price=100):
    return DailyReportLine.objects.create(
        report=report,
        cost_item=cost_item,
        description="Work",
        quantity=quantity,
        unit_price=unit_price,
    )


def _submit_report(auth_client, report_id):
    return auth_client.post(f"/api/daily-reports/{report_id}/submit/")


def test_create_from_daily_report_requires_submitted(
    auth_client, project, cost_item
):
    user = get_user_model().objects.get(username="tester")
    report = _create_daily_report(project, user, status=DailyReportStatus.DRAFT)
    _add_line(report, cost_item)

    response = auth_client.post(
        "/api/cost-actuals/from-daily-report/",
        {"daily_report_id": report.id},
        format="json",
    )

    assert response.status_code == 400


def test_create_from_daily_report_success_and_line_count(
    auth_client, project, cost_item
):
    user = get_user_model().objects.get(username="tester")
    report = _create_daily_report(project, user)
    _add_line(report, cost_item)
    _add_line(report, cost_item, quantity=2, unit_price=50)
    submit_response = _submit_report(auth_client, report.id)
    assert submit_response.status_code == 200

    response = auth_client.post(
        "/api/cost-actuals/from-daily-report/",
        {"daily_report_id": report.id},
        format="json",
    )

    assert response.status_code == 201
    data = response.json()
    assert data["source_daily_report"] == report.id
    assert len(data["lines"]) == 2


def test_create_from_daily_report_duplicate_rejected(
    auth_client, project, cost_item
):
    user = get_user_model().objects.get(username="tester")
    report = _create_daily_report(project, user)
    _add_line(report, cost_item)
    _submit_report(auth_client, report.id)

    first_response = auth_client.post(
        "/api/cost-actuals/from-daily-report/",
        {"daily_report_id": report.id},
        format="json",
    )
    assert first_response.status_code == 201

    second_response = auth_client.post(
        "/api/cost-actuals/from-daily-report/",
        {"daily_report_id": report.id},
        format="json",
    )

    assert second_response.status_code == 400


def test_approve_from_draft(auth_client, project, cost_item):
    user = get_user_model().objects.get(username="tester")
    report = _create_daily_report(project, user)
    _add_line(report, cost_item)
    _submit_report(auth_client, report.id)

    create_response = auth_client.post(
        "/api/cost-actuals/from-daily-report/",
        {"daily_report_id": report.id},
        format="json",
    )
    cost_actual_id = create_response.json()["id"]

    approve_response = auth_client.post(f"/api/cost-actuals/{cost_actual_id}/approve/")

    assert approve_response.status_code == 200
    assert approve_response.json()["status"] == "approved"


def test_approve_from_submitted(auth_client, project, cost_item):
    user = get_user_model().objects.get(username="tester")
    report = _create_daily_report(project, user)
    _add_line(report, cost_item)
    _submit_report(auth_client, report.id)

    create_response = auth_client.post(
        "/api/cost-actuals/from-daily-report/",
        {"daily_report_id": report.id},
        format="json",
    )
    cost_actual_id = create_response.json()["id"]

    CostActual.objects.filter(id=cost_actual_id).update(status="submitted")

    approve_response = auth_client.post(f"/api/cost-actuals/{cost_actual_id}/approve/")

    assert approve_response.status_code == 200
    assert approve_response.json()["status"] == "approved"


def test_close_from_approved_and_block_updates(auth_client, project, cost_item):
    user = get_user_model().objects.get(username="tester")
    report = _create_daily_report(project, user)
    _add_line(report, cost_item)
    _submit_report(auth_client, report.id)

    create_response = auth_client.post(
        "/api/cost-actuals/from-daily-report/",
        {"daily_report_id": report.id},
        format="json",
    )
    cost_actual_id = create_response.json()["id"]
    auth_client.post(f"/api/cost-actuals/{cost_actual_id}/approve/")

    close_response = auth_client.post(f"/api/cost-actuals/{cost_actual_id}/close/")

    assert close_response.status_code == 200
    assert close_response.json()["status"] == "closed"

    patch_response = auth_client.patch(
        f"/api/cost-actuals/{cost_actual_id}/",
        {"report_date": "2024-01-02"},
        format="json",
    )
    assert patch_response.status_code in (400, 403)
