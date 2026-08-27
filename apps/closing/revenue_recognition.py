from __future__ import annotations

from calendar import monthrange
from datetime import date
from decimal import Decimal

from django.core.exceptions import PermissionDenied, ValidationError
from django.db import transaction
from django.db.models import Sum

from apps.audit.services.logger import log_action
from apps.core.rbac.models import Role
from apps.core.rbac.permissions import get_user_role
from apps.cost.models import (
    CostActualLine,
    CostActualStatus,
    RevenueRecognition,
    RevenueRecognitionClose,
    RevenueRecognitionTrigger,
    _get_active_snapshot,
)
from apps.labor.services import get_labor_totals_for_projects
from apps.schedule.models import DailyProgress, SchedulePlan, ScheduleTask

from .services import is_month_closed

VAT_DIVISOR = Decimal("1.10")


def period_end_date(year: int, month: int) -> date:
    return date(year, month, monthrange(year, month)[1])


def _contract_amount(project) -> Decimal:
    """Return the contract total, which operational imports store VAT-inclusive."""
    snapshot = _get_active_snapshot(project)
    if snapshot is not None:
        value = getattr(snapshot, "total_contract_amount", None)
        if value is None:
            value = getattr(snapshot, "total_amount", None)
        if value:
            return Decimal(value)
    contract = getattr(project, "contract", None)
    return Decimal(getattr(contract, "contract_amount", None) or getattr(project, "contract_amount", 0) or 0)


def contract_supply_amount(project) -> Decimal:
    """Return VAT-exclusive contract consideration used for accounting revenue."""
    return (_contract_amount(project) / VAT_DIVISOR).quantize(Decimal("0.01"))


def get_approved_progress_percent(project, as_of_date: date) -> Decimal:
    """Weighted, latest-per-task progress strictly from CEO/HQ-approved entries."""
    plans = SchedulePlan.objects.filter(project=project, is_active=True)
    task_rows = ScheduleTask.objects.filter(plan__in=plans, is_active=True).values("id", "weight_percent")
    task_ids = [row["id"] for row in task_rows]
    latest = {}
    if task_ids:
        for row in (
            DailyProgress.objects.filter(
                project=project,
                task_id__in=task_ids,
                status="approved",
                report_date__lte=as_of_date,
            )
            .order_by("task_id", "-report_date", "-id")
            .values("task_id", "progress_percent")
        ):
            latest.setdefault(row["task_id"], row["progress_percent"] or Decimal("0"))
    return sum(
        ((row["weight_percent"] or Decimal("0")) * latest.get(row["id"], Decimal("0"))) / Decimal("100")
        for row in task_rows
    )


def get_cumulative_eligible_cost(project, as_of_date: date) -> Decimal:
    amount = (
        CostActualLine.objects.filter(
            cost_actual__project=project,
            cost_actual__status__in=[CostActualStatus.APPROVED, CostActualStatus.CLOSED],
            cost_actual__report_date__lte=as_of_date,
        ).aggregate(total=Sum("amount"))["total"]
        or Decimal("0")
    )
    labor = get_labor_totals_for_projects([project.id], as_of_date=as_of_date).get(project.id, {}).get("total") or Decimal("0")
    return Decimal(amount) + Decimal(labor)


def build_revenue_recognition_preview(project, *, close_date: date, trigger_type=RevenueRecognitionTrigger.MONTHLY_CLOSE):
    approved_progress = get_approved_progress_percent(project, close_date)
    contract_amount = contract_supply_amount(project)
    cumulative_revenue = (contract_amount * approved_progress / Decimal("100")).quantize(Decimal("0.01"))
    latest = RevenueRecognition.objects.filter(project=project, as_of_date__lte=close_date).order_by("-as_of_date", "-id").first()
    previous_revenue = Decimal(latest.recognized_revenue) if latest else Decimal("0")
    cumulative_cost = get_cumulative_eligible_cost(project, close_date)
    previous_cost = (
        RevenueRecognitionClose.objects.filter(project=project, recognition_date__lt=close_date)
        .aggregate(total=Sum("recognized_cost_amount"))["total"]
        or Decimal("0")
    )
    duplicate = RevenueRecognitionClose.objects.filter(
        project=project,
        period_year=close_date.year,
        period_month=close_date.month,
        trigger_type=trigger_type,
    ).exists()
    blocks = []
    if not contract_amount:
        blocks.append("계약금액이 없어 매출을 인식할 수 없습니다.")
    if approved_progress <= 0:
        blocks.append("승인된 진행률이 없어 매출을 인식할 수 없습니다.")
    if cumulative_revenue < previous_revenue:
        blocks.append("승인 진행률이 기존 인식 매출보다 낮습니다. 마감 후 수정은 정정 절차가 필요합니다.")
    if cumulative_cost < previous_cost:
        blocks.append("누적 원가가 기존 인식 원가보다 낮습니다. 마감 후 수정은 정정 절차가 필요합니다.")
    if duplicate:
        blocks.append("이미 매출 인식이 완료된 마감입니다.")
    return {
        "project": project,
        "close_date": close_date,
        "period_year": close_date.year,
        "period_month": close_date.month,
        "trigger_type": trigger_type,
        "approved_progress_percent": approved_progress,
        "contract_amount": contract_amount,
        "cumulative_earned_revenue": cumulative_revenue,
        "previously_recognized_revenue": previous_revenue,
        "recognized_revenue_amount": cumulative_revenue - previous_revenue,
        "cumulative_cost": cumulative_cost,
        "previously_recognized_cost": Decimal(previous_cost),
        "recognized_cost_amount": cumulative_cost - Decimal(previous_cost),
        "blocks": blocks,
        "ready": not blocks,
    }


def recognize_revenue_and_cost_for_close(*, project, close_date: date, trigger_type, actor, memo="", request=None):
    if get_user_role(actor) != Role.HQ:
        raise PermissionDenied("HQ 사용자만 매출·원가 인식을 실행할 수 있습니다.")
    if trigger_type == RevenueRecognitionTrigger.MONTHLY_CLOSE and not is_month_closed(close_date, legal_entity=project.legal_entity):
        raise ValidationError("월마감 완료 후 매출·원가 인식을 실행할 수 있습니다.")
    with transaction.atomic():
        preview = build_revenue_recognition_preview(project, close_date=close_date, trigger_type=trigger_type)
        if not preview["ready"]:
            if "이미 매출 인식이 완료된 마감입니다." in preview["blocks"]:
                log_action(actor=actor, action="REVENUE_RECOGNITION_DUPLICATE_BLOCKED", object_type="Project", object_id=project.id, project=project, request=request, meta={"period_month": f"{close_date:%Y-%m}", "trigger_type": trigger_type})
            raise ValidationError(preview["blocks"][0])

        revenue = RevenueRecognition.objects.filter(project=project, as_of_date=close_date).first()
        if revenue is None:
            revenue = RevenueRecognition(
                project=project,
                contract_snapshot=_get_active_snapshot(project),
                as_of_date=close_date,
                progress_percent=preview["approved_progress_percent"],
                recognized_revenue=preview["cumulative_earned_revenue"],
            )
            revenue.save()
        snapshot = RevenueRecognitionClose.objects.create(
            project=project,
            revenue_recognition=revenue,
            recognition_date=close_date,
            period_year=close_date.year,
            period_month=close_date.month,
            trigger_type=trigger_type,
            approved_progress_percent=preview["approved_progress_percent"],
            contract_amount_snapshot=preview["contract_amount"],
            cumulative_earned_revenue=preview["cumulative_earned_revenue"],
            previously_recognized_revenue=preview["previously_recognized_revenue"],
            recognized_revenue_amount=preview["recognized_revenue_amount"],
            cumulative_cost_snapshot=preview["cumulative_cost"],
            previously_recognized_cost=preview["previously_recognized_cost"],
            recognized_cost_amount=preview["recognized_cost_amount"],
            created_by=actor,
            memo=memo,
        )
        log_action(actor=actor, action="REVENUE_RECOGNITION_EXECUTED", object_type="RevenueRecognitionClose", object_id=snapshot.id, project=project, request=request, meta={"period_month": f"{close_date:%Y-%m}", "trigger_type": trigger_type, "approved_progress_percent": str(preview["approved_progress_percent"]), "recognized_revenue_amount": str(preview["recognized_revenue_amount"]), "recognized_cost_amount": str(preview["recognized_cost_amount"])})
        return snapshot
