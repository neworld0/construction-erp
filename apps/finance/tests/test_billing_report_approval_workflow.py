from datetime import date
from decimal import Decimal

import pytest
from django.contrib.auth import get_user_model
from django.core.exceptions import PermissionDenied

from apps.core.rbac.models import LegalEntity, LegalEntityAccessScope, Role, UserLegalEntityMembership, UserProfile
from apps.cost.models import RevenueRecognition
from apps.finance.models import BillingReport, BillingReportStatus, BillingReportType, TaxInvoice
from apps.finance.services.billing_reports import (
    ATTACHMENT_FIELDS,
    approve_billing_report,
    reject_billing_report,
    review_billing_report,
    record_owner_confirmation,
    issue_tax_invoice_and_recognize_revenue,
)
from apps.projects.models import Project
from apps.schedule.models import DailyProgress, SchedulePlan, ScheduleTask


def _user(username, role):
    user = get_user_model().objects.create_user(username=username, password="test")
    UserProfile.objects.create(user=user, role=role)
    UserLegalEntityMembership.objects.create(
        user=user,
        legal_entity=LegalEntity.objects.get(code="ASAN"),
        access_scope=LegalEntityAccessScope.ENTITY_HQ if role == Role.HQ else LegalEntityAccessScope.CEO_VIEW,
    )
    return user


def _report(project, user):
    return BillingReport.objects.create(
        project=project,
        report_type=BillingReportType.COMPLETION,
        billing_round=1,
        billing_date=date(2026, 9, 13),
        approved_progress_percent=Decimal("100"),
        contract_amount_snapshot=Decimal("100000000"),
        current_gross_billing_amount=Decimal("100000000"),
        cumulative_billing_amount=Decimal("100000000"),
        remaining_billing_amount=Decimal("0"),
        net_claim_amount=Decimal("90000000"),
        status=BillingReportStatus.ENGINEER_INPUT_REQUIRED,
        attachment_checklist={field: True for field in ATTACHMENT_FIELDS},
        generated_by=user,
    )


@pytest.mark.django_db
def test_completion_report_requires_ceo_review_then_locks_after_ceo_approval():
    hq = _user("billing-hq", Role.HQ)
    ceo = _user("billing-ceo", Role.CEO)
    project = Project.objects.create(code="BILL-CEO-01", name="준공 결재 테스트", status="active")
    report = _report(project, hq)

    review_billing_report(report=report, actor=hq)
    report.refresh_from_db()
    assert report.status == BillingReportStatus.CEO_REVIEW

    with pytest.raises(PermissionDenied):
        approve_billing_report(report=report, actor=hq)

    approve_billing_report(report=report, actor=ceo)
    report.refresh_from_db()
    assert report.status == BillingReportStatus.LOCKED
    assert report.ceo_approved_by == ceo
    assert report.locked_at is not None


@pytest.mark.django_db
def test_ceo_rejection_returns_report_to_hq_rework_with_reason():
    hq = _user("billing-hq-reject", Role.HQ)
    ceo = _user("billing-ceo-reject", Role.CEO)
    project = Project.objects.create(code="BILL-CEO-02", name="준공 반려 테스트", status="active")
    report = _report(project, hq)
    review_billing_report(report=report, actor=hq)

    reject_billing_report(report=report, actor=ceo, reason="검측 증빙을 보완해 주세요.")
    report.refresh_from_db()
    assert report.status == BillingReportStatus.REJECTED
    assert report.reject_reason == "검측 증빙을 보완해 주세요."


@pytest.mark.django_db
def test_owner_confirmation_then_tax_invoice_recognizes_revenue_on_supply_date():
    hq = _user("billing-tax-hq", Role.HQ)
    project = Project.objects.create(
        code="BILL-TAX-01",
        name="관공서 준공 세금계산서",
        status="active",
        contract_amount=Decimal("100000000"),
    )
    plan = SchedulePlan.objects.create(project=project, name="기준선", is_active=True)
    task = ScheduleTask.objects.create(plan=plan, name="준공", weight_percent=Decimal("100"))
    DailyProgress.objects.create(
        project=project,
        plan=plan,
        task=task,
        report_date=date(2026, 9, 13),
        progress_percent=Decimal("100"),
        status="approved",
        reporter=hq,
    )
    report = _report(project, hq)
    report.status = BillingReportStatus.LOCKED
    report.save(update_fields=["status"])

    record_owner_confirmation(
        report=report,
        confirmation_date=date(2026, 9, 13),
        reference="발주처-2026-준공-01",
        actor=hq,
    )
    invoice = issue_tax_invoice_and_recognize_revenue(
        report=report,
        invoice_number="2026-09-13-001",
        supply_date=date(2026, 9, 13),
        actor=hq,
    )

    report.refresh_from_db()
    assert report.owner_confirmation_status == "CONFIRMED"
    assert TaxInvoice.objects.get(id=invoice.id).supply_amount == Decimal("90909090.91")
    assert TaxInvoice.objects.get(id=invoice.id).tax_amount == Decimal("9090909.09")
    revenue = RevenueRecognition.objects.get(project=project, as_of_date=date(2026, 9, 13))
    assert revenue.recognized_revenue == Decimal("90909090.91")
