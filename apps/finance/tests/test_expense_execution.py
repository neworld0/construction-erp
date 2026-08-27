from datetime import date
from decimal import Decimal

import pytest
from django.contrib.auth import get_user_model
from django.test import Client
from django.utils import timezone

from apps.core.models import ApprovalRequest, ApprovalStatus
from apps.core.rbac.models import Role, UserProfile
from apps.core.services.approvals import approve_request
from apps.cost.models import CostActual, CostActualStatus
from apps.finance.models import CashEventStatus, ExpenseExecution, ExpenseExecutionStatus
from apps.finance.services.expense_execution import pay_expense_execution, schedule_expense_execution
from apps.projects.models import Project


def _user(role, username):
    user = get_user_model().objects.create_user(username=username, password="pass")
    UserProfile.objects.create(user=user, role=role)
    return user


@pytest.mark.django_db
def test_ceo_approved_cost_becomes_hq_expense_execution_and_confirms_cash(settings):
    settings.MIDDLEWARE = [m for m in settings.MIDDLEWARE if "two_factor_enforce" not in m]
    ceo = _user(Role.CEO, "expense-ceo")
    hq = _user(Role.HQ, "expense-hq")
    project = Project.objects.create(code="EXPENSE-001", name="비용 집행 현장", project_type="civil", is_active=True)
    cost = CostActual.objects.create(
        project=project, report_date=timezone.localdate(), status=CostActualStatus.SUBMITTED,
        total_amount=Decimal("1250000.00"),
    )
    approval = ApprovalRequest.objects.create(
        object_type="COST_ACTUAL", object_id=cost.id, status=ApprovalStatus.SUBMITTED,
        submitted_by=hq, submitted_at=timezone.now(),
    )

    approve_request(approval.id, ceo)

    cost.refresh_from_db()
    execution = ExpenseExecution.objects.get(cost_actual=cost)
    assert cost.status == CostActualStatus.APPROVED
    assert execution.status == ExpenseExecutionStatus.READY
    assert execution.amount_snapshot == Decimal("1250000.00")
    assert execution.cash_event.status == CashEventStatus.PLANNED

    schedule_expense_execution(execution=execution, scheduled_date=date(2026, 8, 19), actor=hq, memo="지급 예정")
    execution.refresh_from_db()
    assert execution.status == ExpenseExecutionStatus.SCHEDULED
    assert execution.cash_event.event_date == date(2026, 8, 19)

    pay_expense_execution(execution=execution, paid_date=date(2026, 8, 20), payment_reference="BANK-001", actor=hq)
    execution.refresh_from_db()
    execution.cash_event.refresh_from_db()
    assert execution.status == ExpenseExecutionStatus.PAID
    assert execution.payment_reference == "BANK-001"
    assert execution.cash_event.status == CashEventStatus.CONFIRMED
    assert execution.cash_event.event_date == date(2026, 8, 20)

    client = Client()
    client.force_login(hq)
    response = client.get("/app/hq/finance/expense-executions/?status=PAID")
    assert response.status_code == 200
    assert "비용 집행 관리" in response.content.decode("utf-8")
    dashboard = client.get("/app/hq/")
    assert dashboard.status_code == 200
    assert "비용 집행 대상" in dashboard.content.decode("utf-8")


@pytest.mark.django_db
def test_hq_approved_cost_does_not_create_ceo_payment_target():
    hq = _user(Role.HQ, "expense-only-hq")
    project = Project.objects.create(code="EXPENSE-002", name="HQ 승인 현장", project_type="civil", is_active=True)
    cost = CostActual.objects.create(project=project, report_date=timezone.localdate(), status=CostActualStatus.SUBMITTED, total_amount=Decimal("100"))
    approval = ApprovalRequest.objects.create(object_type="COST_ACTUAL", object_id=cost.id, status=ApprovalStatus.SUBMITTED, submitted_by=hq, submitted_at=timezone.now())

    approve_request(approval.id, hq)

    assert not ExpenseExecution.objects.filter(cost_actual=cost).exists()
