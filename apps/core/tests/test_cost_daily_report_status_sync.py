import pytest
from django.contrib.auth import get_user_model

from apps.core.models import ApprovalRequest, ApprovalStatus
from apps.core.services.approvals import approve_request, reject_request
from apps.cost.models import CostActual, CostActualStatus
from apps.field.models import DailyReport, DailyReportStatus
from apps.projects.models import Project


@pytest.mark.django_db
def test_cost_approval_synchronizes_its_daily_report_source():
    User = get_user_model()
    field_user = User.objects.create_user(username="cost-source-field", password="pass")
    approver = User.objects.create_user(username="cost-source-approver", password="pass")
    project = Project.objects.create(code="COST-SOURCE-SYNC-01", name="원가 원본 상태 동기화")
    report = DailyReport.objects.create(
        project=project,
        report_date="2026-08-20",
        reporter=field_user,
        status=DailyReportStatus.SUBMITTED,
    )
    cost = CostActual.objects.create(
        project=project,
        report_date=report.report_date,
        source_daily_report=report,
        status=CostActualStatus.SUBMITTED,
    )
    approval = ApprovalRequest.objects.create(
        object_type="COST_ACTUAL", object_id=cost.id, status=ApprovalStatus.SUBMITTED
    )

    approve_request(approval.id, approver)

    report.refresh_from_db()
    assert report.status == DailyReportStatus.APPROVED


@pytest.mark.django_db
def test_cost_rejection_synchronizes_its_daily_report_source():
    User = get_user_model()
    field_user = User.objects.create_user(username="cost-source-reject-field", password="pass")
    approver = User.objects.create_user(username="cost-source-reject-approver", password="pass")
    project = Project.objects.create(code="COST-SOURCE-SYNC-02", name="원가 원본 반려 동기화")
    report = DailyReport.objects.create(
        project=project,
        report_date="2026-08-20",
        reporter=field_user,
        status=DailyReportStatus.SUBMITTED,
    )
    cost = CostActual.objects.create(
        project=project,
        report_date=report.report_date,
        source_daily_report=report,
        status=CostActualStatus.SUBMITTED,
    )
    approval = ApprovalRequest.objects.create(
        object_type="COST_ACTUAL", object_id=cost.id, status=ApprovalStatus.SUBMITTED
    )

    reject_request(approval.id, approver, reject_reason="증빙 보완")

    report.refresh_from_db()
    assert report.status == DailyReportStatus.REJECTED
