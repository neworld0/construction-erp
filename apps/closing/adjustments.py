from __future__ import annotations

from datetime import date

from django.core.exceptions import PermissionDenied, ValidationError
from django.db import transaction
from django.db.models import Q, Sum
from django.utils import timezone

from apps.audit.constants import (
    ADJUSTMENT_APPROVE,
    ADJUSTMENT_CREATE,
    ADJUSTMENT_REJECT,
    ADJUSTMENT_SUBMIT,
)
from apps.audit.services.logger import log_action
from apps.cost.models import CostItem

from .models import (
    Adjustment,
    AdjustmentStatus,
    AdjustmentTargetType,
    ClosingPeriod,
    ClosingStatus,
)


def _validate_closed_period(year: int, month: int, *, legal_entity) -> None:
    if not (1 <= month <= 12):
        raise ValidationError("month must be between 1 and 12.")
    is_closed = ClosingPeriod.objects.filter(
        legal_entity=legal_entity, year=year, month=month, status=ClosingStatus.CLOSED
    ).exists()
    if not is_closed:
        raise ValidationError("마감된 월에만 정정할 수 있습니다.")


def create_adjustment(
    *,
    actor,
    project,
    target_type: str,
    period_year: int,
    period_month: int,
    amount_delta: int,
    reason: str,
    cbs: CostItem | None = None,
    target_ref=None,
) -> Adjustment:
    _validate_closed_period(period_year, period_month, legal_entity=project.legal_entity)
    with transaction.atomic():
        adjustment = Adjustment(
            target_type=target_type,
            project=project,
            cbs=cbs,
            period_year=period_year,
            period_month=period_month,
            amount_delta=amount_delta,
            reason=reason,
            status=AdjustmentStatus.DRAFT,
            created_by=actor,
        )
        if target_ref is not None:
            adjustment.target_ref = target_ref
        adjustment.full_clean()
        adjustment.save()
        try:
            log_action(
                actor=actor,
                action=ADJUSTMENT_CREATE,
                object_type="Adjustment",
                object_id=adjustment.id,
                project=project,
                after={
                    "status": adjustment.status,
                    "target_type": adjustment.target_type,
                    "period_year": adjustment.period_year,
                    "period_month": adjustment.period_month,
                    "amount_delta": adjustment.amount_delta,
                },
            )
        except Exception:
            pass
        return adjustment


def submit_adjustment(adjustment: Adjustment, *, actor, request=None) -> Adjustment:
    if adjustment.status not in (AdjustmentStatus.DRAFT, AdjustmentStatus.REJECTED):
        raise ValidationError("Only draft or rejected adjustments can be submitted.")
    _validate_closed_period(adjustment.period_year, adjustment.period_month, legal_entity=adjustment.project.legal_entity)
    adjustment.status = AdjustmentStatus.SUBMITTED
    adjustment.save(update_fields=["status", "updated_at"])
    try:
        log_action(
            actor=actor,
            action=ADJUSTMENT_SUBMIT,
            object_type="Adjustment",
            object_id=adjustment.id,
            project=adjustment.project,
            request=request,
            after={"status": adjustment.status},
        )
    except Exception:
        pass
    return adjustment


def approve_adjustment(adjustment: Adjustment, *, actor, request=None) -> Adjustment:
    if adjustment.status != AdjustmentStatus.SUBMITTED:
        raise ValidationError("Only submitted adjustments can be approved.")
    with transaction.atomic():
        adjustment = Adjustment.objects.select_for_update().get(id=adjustment.id)
        if adjustment.status != AdjustmentStatus.SUBMITTED:
            raise ValidationError("Only submitted adjustments can be approved.")
        adjustment.status = AdjustmentStatus.APPROVED
        adjustment.approved_by = actor
        adjustment.approved_at = timezone.now()
        adjustment.save(update_fields=["status", "approved_by", "approved_at", "updated_at"])
    try:
        log_action(
            actor=actor,
            action=ADJUSTMENT_APPROVE,
            object_type="Adjustment",
            object_id=adjustment.id,
            project=adjustment.project,
            request=request,
            after={"status": adjustment.status},
        )
    except Exception:
        pass
    return adjustment


def reject_adjustment(
    adjustment: Adjustment, *, actor, request=None, note: str | None = None
) -> Adjustment:
    if adjustment.status != AdjustmentStatus.SUBMITTED:
        raise ValidationError("Only submitted adjustments can be rejected.")
    with transaction.atomic():
        adjustment = Adjustment.objects.select_for_update().get(id=adjustment.id)
        if adjustment.status != AdjustmentStatus.SUBMITTED:
            raise ValidationError("Only submitted adjustments can be rejected.")
        adjustment.status = AdjustmentStatus.REJECTED
        adjustment.approved_by = actor
        adjustment.approved_at = timezone.now()
        if note:
            adjustment.reason = f"{adjustment.reason}\n\n[반려 사유]\n{note}"
        adjustment.save(update_fields=["status", "approved_by", "approved_at", "reason", "updated_at"])
    try:
        log_action(
            actor=actor,
            action=ADJUSTMENT_REJECT,
            object_type="Adjustment",
            object_id=adjustment.id,
            project=adjustment.project,
            request=request,
            after={"status": adjustment.status},
            meta={"note": note} if note else None,
        )
    except Exception:
        pass
    return adjustment


def _period_filter(as_of_date: date):
    if as_of_date is None:
        return Q()
    return Q(period_year__lt=as_of_date.year) | Q(
        period_year=as_of_date.year, period_month__lte=as_of_date.month
    )


def get_adjustment_totals(project_ids, *, target_type, as_of_date=None, statuses=None):
    if statuses is None:
        statuses = [AdjustmentStatus.APPROVED]
    qs = Adjustment.objects.filter(
        project_id__in=project_ids, target_type=target_type, status__in=statuses
    )
    qs = qs.filter(_period_filter(as_of_date))
    return {
        row["project_id"]: row["total"]
        for row in qs.values("project_id").annotate(total=Sum("amount_delta"))
    }


def get_cost_adjustment_by_category(project_ids, *, as_of_date=None, statuses=None):
    if statuses is None:
        statuses = [AdjustmentStatus.APPROVED]
    qs = Adjustment.objects.filter(
        project_id__in=project_ids,
        target_type=AdjustmentTargetType.COST,
        status__in=statuses,
        cbs__isnull=False,
    ).select_related("cbs")
    qs = qs.filter(_period_filter(as_of_date))
    return {
        (row["project_id"], row["cbs__category"]): row["total"]
        for row in qs.values("project_id", "cbs__category").annotate(
            total=Sum("amount_delta")
        )
    }


def has_pending_adjustments(project_ids, *, target_type, as_of_date=None):
    pending_statuses = [AdjustmentStatus.DRAFT, AdjustmentStatus.SUBMITTED]
    qs = Adjustment.objects.filter(
        project_id__in=project_ids, target_type=target_type, status__in=pending_statuses
    )
    qs = qs.filter(_period_filter(as_of_date))
    return set(qs.values_list("project_id", flat=True))
