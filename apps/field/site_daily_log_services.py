from __future__ import annotations

from decimal import Decimal

from django.core.exceptions import PermissionDenied, ValidationError
from django.db import transaction
from django.db.models import Sum
from django.utils import timezone

from apps.audit.services.logger import log_action
from apps.closing.guards import guard_write
from apps.core.rbac.models import Role
from apps.core.rbac.permissions import (
    get_user_role,
    require_legal_entity_access,
    require_project_access,
)

from .models import SiteDailyLog, SiteDailyLogStatus


def _as_decimal(value) -> Decimal:
    return Decimal(value or 0)


def _line_snapshot(line):
    return {
        "mapping_id": line.progress_mapping_id,
        "uom_id": line.uom_id,
        "planned_qty": str(line.planned_qty),
        "prior_approved_qty": str(line.prior_approved_qty),
        "today_qty": str(line.today_qty),
        "cumulative_qty": str(line.cumulative_qty),
        "memo": line.memo,
    }


def _refresh_work_line_totals(log: SiteDailyLog) -> list[dict]:
    """Snapshot approved quantities without creating DailyProgress or cost rows."""
    snapshots = []
    for line in log.work_lines.select_related("progress_mapping").order_by("id"):
        mapping = line.progress_mapping
        prior_total = (
            SiteDailyLog.objects.filter(
                project=log.project,
                status=SiteDailyLogStatus.APPROVED,
                report_date__lt=log.report_date,
                work_lines__progress_mapping=mapping,
            )
            .aggregate(total=Sum("work_lines__today_qty"))
            .get("total")
            or Decimal("0")
        )
        line.planned_qty = mapping.planned_qty
        line.uom_id = mapping.uom_id
        line.prior_approved_qty = prior_total
        line.cumulative_qty = prior_total + _as_decimal(line.today_qty)
        line.full_clean()
        line.save(
            update_fields=[
                "planned_qty",
                "uom",
                "prior_approved_qty",
                "cumulative_qty",
                "updated_at",
            ]
        )
        snapshots.append(_line_snapshot(line))
    return snapshots


def _validate_for_submit(log: SiteDailyLog):
    if not (log.today_work or log.work_lines.exists() or log.equipment_lines.exists()):
        raise ValidationError("금일 작업사항, 물량 또는 장비투입 중 하나는 입력해야 합니다.")
    log.full_clean()
    for line in log.work_lines.select_related("progress_mapping", "uom"):
        line.full_clean()
    for line in log.equipment_lines.select_related("cost_actual"):
        line.full_clean()


@transaction.atomic
def submit_site_daily_log(*, log_id: int, actor, request=None) -> SiteDailyLog:
    log = (
        SiteDailyLog.objects.select_for_update()
        .select_related("project", "project__legal_entity")
        .get(id=log_id)
    )
    require_project_access(actor, log.project_id)
    guard_write(project=log.project, target_date=log.report_date, message_context="공사일보 제출은 불가능합니다.")
    if log.status not in (SiteDailyLogStatus.DRAFT, SiteDailyLogStatus.REJECTED):
        raise ValidationError("임시저장 또는 반려된 공사일보만 제출할 수 있습니다.")
    _validate_for_submit(log)
    work_lines = _refresh_work_line_totals(log)
    before = {"status": log.status}
    log.status = SiteDailyLogStatus.SUBMITTED
    log.submitted_at = timezone.now()
    log.rejected_by = None
    log.rejected_at = None
    log.reject_reason = ""
    log.save(
        update_fields=["status", "submitted_at", "rejected_by", "rejected_at", "reject_reason", "updated_at"]
    )
    log_action(
        actor=actor,
        action="SITE_DAILY_LOG_SUBMIT",
        object_type="SiteDailyLog",
        object_id=log.id,
        project=log.project,
        request=request,
        before=before,
        after={"status": log.status, "work_lines": work_lines},
    )
    return log


@transaction.atomic
def decide_site_daily_log(*, log_id: int, actor, approve: bool, reason: str = "", request=None) -> SiteDailyLog:
    log = (
        SiteDailyLog.objects.select_for_update()
        .select_related("project", "project__legal_entity")
        .get(id=log_id)
    )
    if get_user_role(actor) not in (Role.HQ, Role.CEO):
        raise PermissionDenied("HQ 또는 CEO만 공사일보를 검토할 수 있습니다.")
    require_legal_entity_access(actor, log.project.legal_entity, request=request)
    guard_write(project=log.project, target_date=log.report_date, message_context="공사일보 승인 처리는 불가능합니다.")
    if log.status != SiteDailyLogStatus.SUBMITTED:
        raise ValidationError("제출 상태의 공사일보만 승인 또는 반려할 수 있습니다.")
    if not approve and not reason.strip():
        raise ValidationError("반려 사유를 입력해 주세요.")

    before = {"status": log.status}
    if approve:
        work_lines = _refresh_work_line_totals(log)
        log.status = SiteDailyLogStatus.APPROVED
        log.approved_by = actor
        log.approved_at = timezone.now()
        log.approval_snapshot = {
            "report_date": log.report_date.isoformat(),
            "today_work": log.today_work,
            "tomorrow_work": log.tomorrow_work,
            "special_notes": log.special_notes,
            "work_lines": work_lines,
        }
        action = "SITE_DAILY_LOG_APPROVE"
        after = {"status": log.status, "approval_snapshot": log.approval_snapshot}
    else:
        log.status = SiteDailyLogStatus.REJECTED
        log.rejected_by = actor
        log.rejected_at = timezone.now()
        log.reject_reason = reason.strip()
        action = "SITE_DAILY_LOG_REJECT"
        after = {"status": log.status, "reject_reason": log.reject_reason}
    log.save()
    log_action(
        actor=actor,
        action=action,
        object_type="SiteDailyLog",
        object_id=log.id,
        project=log.project,
        request=request,
        before=before,
        after=after,
    )
    return log
