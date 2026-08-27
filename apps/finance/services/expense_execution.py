from __future__ import annotations

from datetime import date

from django.core.exceptions import PermissionDenied, ValidationError
from django.db import transaction
from django.utils import timezone

from apps.audit.services.logger import log_action
from apps.closing.guards import guard_write
from apps.core.rbac.models import Role
from apps.core.rbac.permissions import get_user_role
from apps.finance.models import CashEvent, CashEventStatus, CashEventType, ExpenseExecution, ExpenseExecutionStatus


def _require_hq(actor):
    if get_user_role(actor) != Role.HQ:
        raise PermissionDenied("HQ 사용자만 비용 집행을 처리할 수 있습니다.")


def _lock_execution_with_relations(execution_id):
    """Lock only the execution row; cash_event is nullable and must not be joined in FOR UPDATE."""
    locked = ExpenseExecution.objects.select_for_update().get(pk=execution_id)
    return ExpenseExecution.objects.select_related("cash_event", "cost_actual__project").get(pk=locked.pk)


def queue_ceo_approved_cost_execution(*, cost_actual, actor, approved_at=None, request=None):
    """Create exactly one payable target and planned cash outflow for a CEO approval."""
    if get_user_role(actor) != Role.CEO:
        return None
    with transaction.atomic():
        existing = ExpenseExecution.objects.select_for_update().filter(cost_actual=cost_actual).first()
        if existing:
            return existing
        approved_at = approved_at or timezone.now()
        event = CashEvent.objects.create(
            project=cost_actual.project,
            event_type=CashEventType.OUT,
            status=CashEventStatus.PLANNED,
            amount=cost_actual.total_amount,
            event_date=approved_at.date(),
            description=f"CEO 승인 비용 집행 예정 / 원가 #{cost_actual.id}",
            created_by=actor,
        )
        execution = ExpenseExecution.objects.create(
            cost_actual=cost_actual,
            amount_snapshot=cost_actual.total_amount,
            cash_event=event,
            ceo_approved_by=actor,
            ceo_approved_at=approved_at,
        )
        log_action(
            actor=actor, action="EXPENSE_EXECUTION_READY", object_type="ExpenseExecution",
            object_id=execution.id, project=cost_actual.project, request=request,
            after={"status": execution.status, "cost_actual_id": cost_actual.id, "amount": str(execution.amount_snapshot)},
        )
        return execution


def schedule_expense_execution(*, execution, scheduled_date: date, actor, memo="", request=None):
    _require_hq(actor)
    if execution.status not in (ExpenseExecutionStatus.READY, ExpenseExecutionStatus.SCHEDULED):
        raise ValidationError("지급 완료 또는 취소된 건은 예정일을 변경할 수 없습니다.")
    guard_write(project=execution.cost_actual.project, target_date=scheduled_date, message_context="비용 집행 예정일 등록입니다.", exc=PermissionDenied)
    with transaction.atomic():
        execution = _lock_execution_with_relations(execution.pk)
        before = execution.status
        execution.status = ExpenseExecutionStatus.SCHEDULED
        execution.scheduled_date = scheduled_date
        execution.scheduled_by = actor
        execution.memo = (memo or "").strip()
        execution.save(update_fields=["status", "scheduled_date", "scheduled_by", "memo", "updated_at"])
        if execution.cash_event_id:
            execution.cash_event.event_date = scheduled_date
            execution.cash_event.status = CashEventStatus.PLANNED
            execution.cash_event.save(update_fields=["event_date", "status"])
        log_action(actor=actor, action="EXPENSE_EXECUTION_SCHEDULED", object_type="ExpenseExecution", object_id=execution.id, project=execution.cost_actual.project, request=request, before={"status": before}, after={"status": execution.status, "scheduled_date": scheduled_date.isoformat()})
        return execution


def pay_expense_execution(*, execution, paid_date: date, payment_reference="", memo="", actor=None, request=None):
    _require_hq(actor)
    if execution.status not in (ExpenseExecutionStatus.READY, ExpenseExecutionStatus.SCHEDULED):
        raise ValidationError("지급 대기 또는 지급 예정 상태의 건만 지급 완료할 수 있습니다.")
    guard_write(project=execution.cost_actual.project, target_date=paid_date, message_context="비용 지급 처리입니다.", exc=PermissionDenied)
    with transaction.atomic():
        execution = _lock_execution_with_relations(execution.pk)
        before = execution.status
        execution.status = ExpenseExecutionStatus.PAID
        execution.paid_date = paid_date
        execution.paid_by = actor
        execution.payment_reference = (payment_reference or "").strip()
        execution.memo = (memo or "").strip()
        execution.save(update_fields=["status", "paid_date", "paid_by", "payment_reference", "memo", "updated_at"])
        if execution.cash_event_id:
            execution.cash_event.event_date = paid_date
            execution.cash_event.status = CashEventStatus.CONFIRMED
            execution.cash_event.save(update_fields=["event_date", "status"])
        log_action(actor=actor, action="EXPENSE_EXECUTION_PAID", object_type="ExpenseExecution", object_id=execution.id, project=execution.cost_actual.project, request=request, before={"status": before}, after={"status": execution.status, "paid_date": paid_date.isoformat(), "payment_reference": execution.payment_reference})
        return execution


def cancel_expense_execution(*, execution, memo, actor, request=None):
    _require_hq(actor)
    if execution.status not in (ExpenseExecutionStatus.READY, ExpenseExecutionStatus.SCHEDULED):
        raise ValidationError("지급 완료 또는 이미 취소된 건은 취소할 수 없습니다.")
    guard_write(
        project=execution.cost_actual.project,
        target_date=(execution.cash_event.event_date if execution.cash_event_id else timezone.localdate()),
        message_context="비용 집행 취소입니다.",
        exc=PermissionDenied,
    )
    memo = (memo or "").strip()
    if not memo:
        raise ValidationError("집행 취소 사유를 입력해 주세요.")
    with transaction.atomic():
        execution = _lock_execution_with_relations(execution.pk)
        before = execution.status
        execution.status = ExpenseExecutionStatus.CANCELLED
        execution.memo = memo
        execution.save(update_fields=["status", "memo", "updated_at"])
        if execution.cash_event_id:
            execution.cash_event.status = CashEventStatus.CANCELLED
            execution.cash_event.save(update_fields=["status"])
        log_action(actor=actor, action="EXPENSE_EXECUTION_CANCELLED", object_type="ExpenseExecution", object_id=execution.id, project=execution.cost_actual.project, request=request, before={"status": before}, after={"status": execution.status, "memo": memo})
        return execution
