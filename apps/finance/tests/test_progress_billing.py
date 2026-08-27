from datetime import date
from decimal import Decimal

import pytest
from django.contrib.auth import get_user_model

from apps.core.rbac.models import LegalEntity, LegalEntityAccessScope, Role, UserLegalEntityMembership, UserProfile
from apps.closing.models import ClosingPeriod, ClosingStatus, ProjectClose, ProjectCloseStatus
from apps.finance.models import CashEventStatus, ProgressBillingStatus
from apps.finance.services.progress_billing import (
    build_progress_billing_preview,
    collect_progress_billing,
    issue_progress_billing,
    register_advance_payment,
)
from apps.projects.models import Project
from apps.schedule.models import DailyProgress, SchedulePlan, ScheduleTask


def _user():
    user = get_user_model().objects.create_user(username="progress-billing-hq", password="pass")
    UserProfile.objects.create(user=user, role=Role.HQ)
    UserLegalEntityMembership.objects.create(
        user=user,
        legal_entity=LegalEntity.objects.get(code="ASAN"),
        access_scope=LegalEntityAccessScope.ENTITY_HQ,
    )
    return user


@pytest.mark.django_db
def test_progress_billing_recovers_advance_by_cumulative_progress_and_confirms_cash():
    hq = _user()
    project = Project.objects.create(code="BILL-001", name="기성청구 현장", project_type="civil", contract_amount=Decimal("132000000"))
    plan = SchedulePlan.objects.create(project=project, version_no=1, name="기준선")
    task = ScheduleTask.objects.create(plan=plan, name="포장", weight_percent=Decimal("100"))
    DailyProgress.objects.create(project=project, plan=plan, task=task, report_date=date(2026, 8, 18), progress_percent=Decimal("18.36"), status="approved", reporter=hq)

    advance = register_advance_payment(project=project, advance_rate_percent="40", received_date=date(2026, 8, 1), actor=hq)
    preview = build_progress_billing_preview(project, billing_date=date(2026, 8, 18))

    assert advance.advance_amount == Decimal("52800000.00")
    assert preview["gross_claim_amount"] == Decimal("24235200.00")
    assert preview["advance_deduction_amount"] == Decimal("9694080.00")
    assert preview["net_claim_amount"] == Decimal("14541120.00")
    assert preview["advance_balance_after"] == Decimal("43105920.00")

    billing = issue_progress_billing(project=project, billing_date=date(2026, 8, 18), actor=hq)
    assert billing.status == ProgressBillingStatus.ISSUED
    assert billing.cash_event.status == CashEventStatus.PLANNED

    collect_progress_billing(billing=billing, collected_date=date(2026, 8, 25), actor=hq)
    billing.refresh_from_db()
    billing.cash_event.refresh_from_db()
    assert billing.status == ProgressBillingStatus.COLLECTED
    assert billing.cash_event.status == CashEventStatus.CONFIRMED


@pytest.mark.django_db
def test_collection_after_billing_month_and_project_close_uses_open_actual_receipt_month():
    hq = _user()
    project = Project.objects.create(
        code="BILL-COLLECT-001",
        name="사후 수금 현장",
        project_type="civil",
        contract_amount=Decimal("100000000"),
    )
    plan = SchedulePlan.objects.create(project=project, version_no=1, name="기준선")
    task = ScheduleTask.objects.create(plan=plan, name="포장", weight_percent=Decimal("100"))
    DailyProgress.objects.create(
        project=project,
        plan=plan,
        task=task,
        report_date=date(2026, 8, 18),
        progress_percent=Decimal("20"),
        status="approved",
        reporter=hq,
    )
    register_advance_payment(project=project, advance_rate_percent="40", received_date=date(2026, 8, 1), actor=hq)
    billing = issue_progress_billing(project=project, billing_date=date(2026, 8, 18), actor=hq)
    ClosingPeriod.objects.create(
        legal_entity=LegalEntity.objects.get(code="ASAN"),
        year=2026,
        month=8,
        status=ClosingStatus.CLOSED,
    )
    ProjectClose.objects.create(project=project, status=ProjectCloseStatus.CLOSED)

    collect_progress_billing(billing=billing, collected_date=date(2026, 9, 1), actor=hq)

    billing.refresh_from_db()
    billing.cash_event.refresh_from_db()
    assert billing.status == ProgressBillingStatus.COLLECTED
    assert billing.cash_event.status == CashEventStatus.CONFIRMED
    assert billing.cash_event.event_date == date(2026, 9, 1)
