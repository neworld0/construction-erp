from __future__ import annotations

from datetime import date
from decimal import Decimal

from django.core.exceptions import PermissionDenied, ValidationError
from django.db import transaction
from django.db.models import Sum
from django.utils import timezone

from apps.audit.services.logger import log_action
from apps.closing.guards import assert_month_open, guard_write
from apps.closing.revenue_recognition import _contract_amount, get_approved_progress_percent
from apps.core.rbac.models import Role
from apps.core.rbac.permissions import get_user_role, require_legal_entity_access
from apps.finance.models import AdvancePayment, CashEvent, CashEventStatus, CashEventType, ProgressBilling, ProgressBillingStatus


def _require_hq(actor):
    if get_user_role(actor) != Role.HQ:
        raise PermissionDenied("HQ 사용자만 선급금 및 기성청구를 처리할 수 있습니다.")


def _require_hq_for_project(actor, project):
    """HQ role and the contracting entity membership are both required."""
    _require_hq(actor)
    require_legal_entity_access(actor, project.legal_entity)


def register_advance_payment(*, project, advance_rate_percent, received_date: date, actor, received_amount=None, memo="", request=None):
    _require_hq_for_project(actor, project)
    guard_write(project=project, target_date=received_date, message_context="선급금 수령일입니다.", exc=PermissionDenied)
    rate = Decimal(str(advance_rate_percent or 0))
    if rate <= 0 or rate > 100:
        raise ValidationError("선급금 비율은 0 초과 100 이하로 입력해 주세요.")
    contract_amount = _contract_amount(project)
    if contract_amount <= 0:
        raise ValidationError("계약금액이 없어 선급금을 등록할 수 없습니다.")
    advance_amount = (contract_amount * rate / Decimal("100")).quantize(Decimal("0.01"))
    received_amount = Decimal(str(received_amount)) if received_amount not in (None, "") else advance_amount
    if received_amount <= 0 or received_amount > advance_amount:
        raise ValidationError("선급금 수령액은 약정 선급금 범위에서 입력해 주세요.")
    if AdvancePayment.objects.filter(project=project).exists():
        raise ValidationError("이미 등록된 선급금 조건이 있습니다. 변경은 정정 절차로 처리하세요.")
    with transaction.atomic():
        event = CashEvent.objects.create(project=project, event_type=CashEventType.IN, status=CashEventStatus.CONFIRMED, amount=received_amount, event_date=received_date, description="발주처 선급금 수령", created_by=actor)
        advance = AdvancePayment.objects.create(project=project, contract_amount_snapshot=contract_amount, advance_rate_percent=rate, advance_amount=advance_amount, received_amount=received_amount, received_date=received_date, cash_event=event, memo=memo, created_by=actor)
        log_action(actor=actor, action="ADVANCE_PAYMENT_REGISTERED", object_type="AdvancePayment", object_id=advance.id, project=project, request=request, meta={"advance_rate_percent": str(rate), "advance_amount": str(advance_amount), "received_amount": str(received_amount)})
        return advance


def build_progress_billing_preview(project, *, billing_date: date):
    advance = AdvancePayment.objects.filter(project=project).first()
    contract_amount = _contract_amount(project)
    approved_progress = get_approved_progress_percent(project, billing_date)
    cumulative_earned = (contract_amount * approved_progress / Decimal("100")).quantize(Decimal("0.01"))
    prior = ProgressBilling.objects.filter(project=project, billing_date__lt=billing_date).exclude(status__isnull=True)
    previously_billed = prior.aggregate(total=Sum("gross_claim_amount"))["total"] or Decimal("0")
    previously_deducted = prior.aggregate(total=Sum("advance_deduction_amount"))["total"] or Decimal("0")
    gross_claim = cumulative_earned - Decimal(previously_billed)
    advance_amount = Decimal(advance.received_amount) if advance else Decimal("0")
    cumulative_deduction = min(advance_amount, (advance_amount * approved_progress / Decimal("100")).quantize(Decimal("0.01")))
    deduction = cumulative_deduction - Decimal(previously_deducted)
    net_claim = gross_claim - deduction
    blocks = []
    if advance is None:
        blocks.append("선급금 조건을 먼저 등록해 주세요.")
    if contract_amount <= 0:
        blocks.append("계약금액이 없어 기성청구를 생성할 수 없습니다.")
    if approved_progress <= 0:
        blocks.append("승인된 진행률이 없어 기성청구를 생성할 수 없습니다.")
    if gross_claim <= 0:
        blocks.append("이번 기성 청구 대상 금액이 없습니다. 진행률 정정은 정정 절차로 처리하세요.")
    if deduction < 0 or net_claim < 0:
        blocks.append("선급금 공제 계산값이 유효하지 않습니다. 정정 절차가 필요합니다.")
    if ProgressBilling.objects.filter(project=project, billing_date=billing_date).exists():
        blocks.append("해당 기준일의 기성청구가 이미 있습니다.")
    return {"project": project, "billing_date": billing_date, "advance": advance, "contract_amount": contract_amount, "approved_progress_percent": approved_progress, "cumulative_earned_amount": cumulative_earned, "previously_billed_amount": Decimal(previously_billed), "gross_claim_amount": gross_claim, "cumulative_advance_deduction": cumulative_deduction, "advance_deduction_amount": deduction, "net_claim_amount": net_claim, "advance_balance_after": advance_amount - cumulative_deduction, "blocks": blocks, "ready": not blocks}


def issue_progress_billing(*, project, billing_date: date, actor, memo="", request=None):
    _require_hq_for_project(actor, project)
    guard_write(project=project, target_date=billing_date, message_context="기성청구 기준일입니다.", exc=PermissionDenied)
    with transaction.atomic():
        preview = build_progress_billing_preview(project, billing_date=billing_date)
        if not preview["ready"]:
            raise ValidationError(preview["blocks"][0])
        event = CashEvent.objects.create(project=project, event_type=CashEventType.IN, status=CashEventStatus.PLANNED, amount=preview["net_claim_amount"], event_date=billing_date, description="발주처 기성금 청구 예정 수금", created_by=actor)
        billing = ProgressBilling.objects.create(project=project, billing_date=billing_date, contract_amount_snapshot=preview["contract_amount"], approved_progress_percent=preview["approved_progress_percent"], cumulative_earned_amount=preview["cumulative_earned_amount"], previously_billed_amount=preview["previously_billed_amount"], gross_claim_amount=preview["gross_claim_amount"], cumulative_advance_deduction=preview["cumulative_advance_deduction"], advance_deduction_amount=preview["advance_deduction_amount"], net_claim_amount=preview["net_claim_amount"], advance_balance_after=preview["advance_balance_after"], cash_event=event, memo=memo, issued_by=actor)
        log_action(actor=actor, action="PROGRESS_BILLING_ISSUED", object_type="ProgressBilling", object_id=billing.id, project=project, request=request, meta={"billing_date": billing_date.isoformat(), "gross_claim_amount": str(billing.gross_claim_amount), "advance_deduction_amount": str(billing.advance_deduction_amount), "net_claim_amount": str(billing.net_claim_amount)})
        return billing


def collect_progress_billing(*, billing, collected_date: date, actor, request=None):
    _require_hq_for_project(actor, billing.project)
    if billing.status != ProgressBillingStatus.ISSUED:
        raise ValidationError("수금 처리할 수 있는 기성청구가 아닙니다.")
    if collected_date < billing.billing_date:
        raise ValidationError("실제 수금일은 기성청구 기준일보다 빠를 수 없습니다.")
    # A receivable may be collected after both the project and its billing
    # month have closed.  The cash receipt belongs to its actual receipt
    # month, so only that month must be open; a closed historical month still
    # requires the correction process.
    assert_month_open(
        collected_date,
        legal_entity=billing.project.legal_entity,
        message_context="기성금 실제 수금일입니다.",
        exc=PermissionDenied,
    )
    with transaction.atomic():
        billing.status = ProgressBillingStatus.COLLECTED
        billing.collected_by = actor
        billing.collected_at = timezone.now()
        billing.save(update_fields=["status", "collected_by", "collected_at"])
        if billing.cash_event_id:
            billing.cash_event.status = CashEventStatus.CONFIRMED
            billing.cash_event.event_date = collected_date
            billing.cash_event.save(update_fields=["status", "event_date"])
        log_action(actor=actor, action="PROGRESS_BILLING_COLLECTED", object_type="ProgressBilling", object_id=billing.id, project=billing.project, request=request, meta={"billing_date": billing.billing_date.isoformat(), "collected_date": collected_date.isoformat(), "net_claim_amount": str(billing.net_claim_amount)})
        return billing


def get_advance_billing_summary(project_ids):
    advances = AdvancePayment.objects.filter(project_id__in=project_ids)
    billings = ProgressBilling.objects.filter(project_id__in=project_ids)
    advance_received = advances.aggregate(total=Sum("received_amount"))["total"] or Decimal("0")
    advance_recovered = billings.aggregate(total=Sum("advance_deduction_amount"))["total"] or Decimal("0")
    return {
        "advance_received": advance_received,
        "advance_recovered": advance_recovered,
        "advance_balance": Decimal(advance_received) - Decimal(advance_recovered),
        "receivable": billings.filter(status=ProgressBillingStatus.ISSUED).aggregate(total=Sum("net_claim_amount"))["total"] or Decimal("0"),
    }
