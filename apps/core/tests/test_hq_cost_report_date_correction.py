from datetime import timedelta
from decimal import Decimal

import pytest
from django.contrib.auth import get_user_model
from django.test import Client
from django.utils import timezone

from apps.audit.models import AuditLog
from apps.core.models import ApprovalRequest, ApprovalStatus
from apps.core.rbac.models import Role, UserProfile
from apps.cost.models import CostActual, CostActualLine, CostActualStatus, CostItem
from apps.field.models import DailyReport, DailyReportStatus
from apps.projects.models import Project


@pytest.fixture(autouse=True)
def _disable_two_factor_enforce(settings):
    settings.MIDDLEWARE = [
        middleware
        for middleware in settings.MIDDLEWARE
        if middleware != "apps.core.middleware.two_factor_enforce.TwoFactorEnforceMiddleware"
    ]


@pytest.mark.django_db
def test_hq_corrects_submitted_cost_date_and_returns_it_to_field_rework():
    hq = get_user_model().objects.create_user(username="hq-cost-date", password="pass")
    field = get_user_model().objects.create_user(username="field-cost-date-correct", password="pass")
    UserProfile.objects.create(user=hq, role=Role.HQ)
    UserProfile.objects.create(user=field, role=Role.FIELD)
    project = Project.objects.create(code="HQ-COST-DATE", name="HQ 날짜 정정 현장", project_type="civil")
    old_date = timezone.localdate() - timedelta(days=2)
    new_date = timezone.localdate() - timedelta(days=1)
    report = DailyReport.objects.create(
        project=project, report_date=old_date, reporter=field, status=DailyReportStatus.SUBMITTED
    )
    cbs = CostItem.objects.create(code="HQ-COST-DATE-CBS", name="날짜 정정 CBS", category="other")
    cost = CostActual.objects.create(
        project=project, report_date=old_date, source_daily_report=report, status=CostActualStatus.SUBMITTED
    )
    CostActualLine.objects.create(
        cost_actual=cost,
        cost_item=cbs,
        quantity=Decimal("1"),
        unit_price=Decimal("1000"),
    )
    approval = ApprovalRequest.objects.create(
        object_type="COST_ACTUAL", object_id=cost.id, status=ApprovalStatus.SUBMITTED, submitted_by=field
    )
    client = Client()
    client.force_login(hq)

    detail = client.get(f"/app/hq/costs/{cost.id}/")
    assert detail.status_code == 200
    assert "원가 발생일 정정" in detail.content.decode("utf-8")

    response = client.post(
        f"/app/hq/costs/{cost.id}/correct-date/",
        {"report_date": new_date.isoformat(), "reason": "현장 전표 발생일 오기"},
    )

    assert response.status_code == 302
    cost.refresh_from_db()
    report.refresh_from_db()
    approval.refresh_from_db()
    assert cost.report_date == new_date
    assert report.report_date == new_date
    assert cost.status == CostActualStatus.REJECTED
    assert report.status == DailyReportStatus.REJECTED
    assert approval.status == ApprovalStatus.REJECTED
    assert "HQ 날짜 정정" in approval.reject_reason
    audit = AuditLog.objects.get(action="COST_ACTUAL_REPORT_DATE_CORRECT", object_id=cost.id)
    assert audit.before_json["report_date"] == old_date.isoformat()
    assert audit.after_json["report_date"] == new_date.isoformat()


@pytest.mark.django_db
def test_hq_cannot_directly_correct_approved_cost_date():
    hq = get_user_model().objects.create_user(username="hq-approved-cost-date", password="pass")
    field = get_user_model().objects.create_user(username="field-approved-cost-date", password="pass")
    UserProfile.objects.create(user=hq, role=Role.HQ)
    UserProfile.objects.create(user=field, role=Role.FIELD)
    project = Project.objects.create(code="HQ-APPROVED-COST-DATE", name="승인 원가 정정 차단", project_type="civil")
    old_date = timezone.localdate() - timedelta(days=2)
    report = DailyReport.objects.create(project=project, report_date=old_date, reporter=field)
    cost = CostActual.objects.create(
        project=project, report_date=old_date, source_daily_report=report, status=CostActualStatus.APPROVED
    )
    client = Client()
    client.force_login(hq)

    response = client.post(
        f"/app/hq/costs/{cost.id}/correct-date/",
        {"report_date": (old_date + timedelta(days=1)).isoformat(), "reason": "오입력"},
        follow=True,
    )

    cost.refresh_from_db()
    assert response.status_code == 200
    assert cost.report_date == old_date
    assert not AuditLog.objects.filter(
        action="COST_ACTUAL_REPORT_DATE_CORRECT", object_id=cost.id
    ).exists()
