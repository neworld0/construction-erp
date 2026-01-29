import logging
from datetime import date as date_type, timedelta
from decimal import Decimal, ROUND_HALF_UP

from django.core.exceptions import PermissionDenied, ValidationError
from django.db import transaction
from django.db.models import Q, Sum
from django.utils import timezone

from apps.audit.services.logger import log_action
from apps.closing.guards import guard_write
from apps.closing.services import is_month_closed
from apps.core.rbac.models import Role
from apps.core.rbac.permissions import require_project_access, require_role
from apps.cost.models import CostItem, CostItemCategory
from apps.projects.models import Project

from .models import (
    LaborRateScope,
    LaborRateTable,
    LaborRateType,
    LaborRole,
    PayrollAllocationBatch,
    PayrollAllocationLine,
    PayrollAllocationStatus,
    PayrollBatchNumberSequence,
    Timesheet,
    TimesheetLine,
    TimesheetNumberSequence,
    TimesheetStatus,
)

logger = logging.getLogger(__name__)

# Discovery:
# - CostItem: apps/cost/models.py CostItem
# - RBAC: apps/core/rbac/permissions.py require_role
# - HQ master UI pattern: templates/app/hq/master_* + apps/master/web_urls.py

FALLBACK_LABOR_CBS_CODE = "LABOR-GENERAL"
FALLBACK_LABOR_CBS_NAME = "인건비(공통)"


def _log_action_safe(*, actor, action, object_id, summary, metadata, object_type):
    if actor is None:
        return
    try:
        log_action(
            actor=actor,
            action=action,
            object_type=object_type,
            object_id=object_id,
            meta=metadata,
        )
    except Exception:
        logger.warning("AuditLog failed for %s.", action, exc_info=True)


def _resolve_cost_item(value):
    if not value:
        return None
    if isinstance(value, CostItem):
        return value
    return CostItem.objects.filter(id=value).first()


def _resolve_project(value):
    if not value:
        return None
    if isinstance(value, Project):
        return value
    return Project.objects.filter(id=value).first()


def _overlap_q(start, end):
    if end:
        return Q(effective_from__lte=end) & (
            Q(effective_to__isnull=True) | Q(effective_to__gte=start)
        )
    return Q(effective_to__isnull=True) | Q(effective_to__gte=start)


def _month_range(year: int, month: int) -> tuple[date_type, date_type]:
    month = int(month)
    year = int(year)
    start = date_type(year, month, 1)
    if month == 12:
        end = date_type(year, 12, 31)
    else:
        end = date_type(year, month + 1, 1) - timedelta(days=1)
    return start, end


def _get_or_create_fallback_cbs() -> CostItem:
    fallback = CostItem.objects.filter(code=FALLBACK_LABOR_CBS_CODE).first()
    if fallback:
        return fallback
    return CostItem.objects.create(
        code=FALLBACK_LABOR_CBS_CODE,
        name=FALLBACK_LABOR_CBS_NAME,
        category=CostItemCategory.LABOR,
        cost_type="L",
        work_type="99",
        is_direct=False,
        is_active=True,
    )


def compute_labor_data_quality(project_id: int, year: int, month: int) -> str:
    period_date = date_type(int(year), int(month), 1)
    is_closed = is_month_closed(period_date)
    has_timesheet = Timesheet.objects.filter(
        project_id=project_id,
        status=TimesheetStatus.APPROVED,
        work_date__year=year,
        work_date__month=month,
    ).exists()
    has_payroll = PayrollAllocationLine.objects.filter(
        project_id=project_id,
        batch__status__in=[
            PayrollAllocationStatus.SUBMITTED,
            PayrollAllocationStatus.APPROVED,
        ],
        batch__period_year=year,
        batch__period_month=month,
    ).exists()
    if is_closed:
        return "OK" if has_timesheet and has_payroll else "ESTIMATED"
    return "UNSURE"


def get_labor_totals_for_projects(project_ids, *, as_of_date=None) -> dict:
    if not project_ids:
        return {}
    if as_of_date is None:
        as_of_date = timezone.localdate()
    fallback_cbs = _get_or_create_fallback_cbs()

    totals = {
        int(project_id): {
            "total": Decimal("0"),
            "by_cbs": {},
            "sources": {"timesheet_total": Decimal("0"), "payroll_total": Decimal("0")},
        }
        for project_id in project_ids
    }

    timesheet_rows = (
        TimesheetLine.objects.filter(
            timesheet__project_id__in=project_ids,
            timesheet__status=TimesheetStatus.APPROVED,
            timesheet__work_date__lte=as_of_date,
        )
        .values("timesheet__project_id", "labor_role__default_cbs")
        .annotate(total=Sum("amount"))
    )
    for row in timesheet_rows:
        project_id = int(row["timesheet__project_id"])
        cbs_id = row["labor_role__default_cbs"] or fallback_cbs.id
        amount = row["total"] or Decimal("0")
        entry = totals.setdefault(
            project_id,
            {
                "total": Decimal("0"),
                "by_cbs": {},
                "sources": {"timesheet_total": Decimal("0"), "payroll_total": Decimal("0")},
            },
        )
        entry["total"] += amount
        entry["sources"]["timesheet_total"] += amount
        entry["by_cbs"][cbs_id] = entry["by_cbs"].get(cbs_id, Decimal("0")) + amount

    payroll_rows = (
        PayrollAllocationLine.objects.filter(
            project_id__in=project_ids,
            batch__status__in=[
                PayrollAllocationStatus.SUBMITTED,
                PayrollAllocationStatus.APPROVED,
            ],
        )
        .filter(
            Q(batch__period_year__lt=as_of_date.year)
            | Q(
                batch__period_year=as_of_date.year,
                batch__period_month__lte=as_of_date.month,
            )
        )
        .values("project_id", "cbs_id")
        .annotate(total=Sum("amount"))
    )
    for row in payroll_rows:
        project_id = int(row["project_id"])
        cbs_id = row["cbs_id"] or fallback_cbs.id
        amount = row["total"] or Decimal("0")
        entry = totals.setdefault(
            project_id,
            {
                "total": Decimal("0"),
                "by_cbs": {},
                "sources": {"timesheet_total": Decimal("0"), "payroll_total": Decimal("0")},
            },
        )
        entry["total"] += amount
        entry["sources"]["payroll_total"] += amount
        entry["by_cbs"][cbs_id] = entry["by_cbs"].get(cbs_id, Decimal("0")) + amount

    return totals


def get_labor_actual_by_month(project_id: int, year: int, month: int) -> dict:
    fallback_cbs = _get_or_create_fallback_cbs()
    start_date, end_date = _month_range(year, month)

    timesheet_rows = (
        TimesheetLine.objects.filter(
            timesheet__project_id=project_id,
            timesheet__status=TimesheetStatus.APPROVED,
            timesheet__work_date__gte=start_date,
            timesheet__work_date__lte=end_date,
        )
        .values("labor_role__default_cbs")
        .annotate(total=Sum("amount"))
    )
    payroll_rows = (
        PayrollAllocationLine.objects.filter(
            project_id=project_id,
            batch__status__in=[
                PayrollAllocationStatus.SUBMITTED,
                PayrollAllocationStatus.APPROVED,
            ],
            batch__period_year=year,
            batch__period_month=month,
        )
        .values("cbs_id")
        .annotate(total=Sum("amount"))
    )

    by_cbs = {}
    timesheet_total = Decimal("0")
    payroll_total = Decimal("0")
    for row in timesheet_rows:
        cbs_id = row["labor_role__default_cbs"] or fallback_cbs.id
        amount = row["total"] or Decimal("0")
        timesheet_total += amount
        by_cbs[cbs_id] = by_cbs.get(cbs_id, Decimal("0")) + amount
    for row in payroll_rows:
        cbs_id = row["cbs_id"] or fallback_cbs.id
        amount = row["total"] or Decimal("0")
        payroll_total += amount
        by_cbs[cbs_id] = by_cbs.get(cbs_id, Decimal("0")) + amount

    cbs_ids = list(by_cbs.keys())
    cbs_map = {item.id: item for item in CostItem.objects.filter(id__in=cbs_ids)}
    by_cbs_list = []
    for cbs_id, amount in by_cbs.items():
        cbs = cbs_map.get(cbs_id) or fallback_cbs
        by_cbs_list.append(
            {
                "cbs_id": cbs.id,
                "cbs_code": cbs.code,
                "cbs_name": cbs.get_display_name(),
                "amount": amount,
            }
        )

    total = timesheet_total + payroll_total
    quality = compute_labor_data_quality(project_id, year, month)
    return {
        "total": int(total),
        "by_cbs": by_cbs_list,
        "sources": {
            "timesheet_total": int(timesheet_total),
            "payroll_total": int(payroll_total),
        },
        "data_quality": quality,
    }


def _validate_overlap(*, role, rate_type, scope_type, project, start, end, exclude_id=None):
    qs = LaborRateTable.objects.filter(
        labor_role=role,
        rate_type=rate_type,
        scope_type=scope_type,
    )
    if scope_type == LaborRateScope.PROJECT:
        qs = qs.filter(project=project)
    else:
        qs = qs.filter(project__isnull=True)
    qs = qs.filter(_overlap_q(start, end))
    if exclude_id:
        qs = qs.exclude(id=exclude_id)
    if qs.exists():
        raise ValidationError("동일 범위에서 기간이 겹치는 단가가 이미 존재합니다.")


def _assert_month_open(project: Project | None, target_date: date_type, *, message_prefix: str) -> None:
    guard_write(
        project=project,
        target_date=target_date,
        message_context=message_prefix,
        exc=PermissionDenied,
    )


def _ensure_timesheet_editable(timesheet: Timesheet, *, actor):
    if timesheet.status not in (TimesheetStatus.DRAFT, TimesheetStatus.REJECTED):
        raise PermissionDenied(
            "\uc81c\ucd9c \uc774\ud6c4\uc5d0\ub294 \uc218\uc815\ud560 \uc218 \uc5c6\uc2b5\ub2c8\ub2e4."
        )
    if actor and actor != timesheet.created_by:
        raise PermissionDenied(
            "\ubcf8\uc778\uc774 \uc791\uc131\ud55c \ucd9c\uc5ed\ubd80\ub9cc \uc218\uc815 \uac00\ub2a5\ud569\ub2c8\ub2e4."
        )


def create_labor_role(data, *, actor):
    require_role(actor, [Role.HQ, Role.CEO])
    code = str(data.get("code") or "").strip().upper()
    name = str(data.get("name") or "").strip()
    if not code:
        raise ValidationError({"code": "code is required."})
    if not name:
        raise ValidationError({"name": "name is required."})
    role_group = str(data.get("role_group") or "").strip()
    default_cbs = _resolve_cost_item(data.get("default_cbs"))
    role = LaborRole.objects.create(
        code=code,
        name=name,
        role_group=role_group,
        is_active=bool(data.get("is_active", True)),
        sort_order=int(data.get("sort_order") or 0),
        default_cbs=default_cbs,
    )
    _log_action_safe(
        actor=actor,
        action="LABOR_ROLE_CREATE",
        object_id=role.id,
        summary=f"LaborRole create: {role.code}",
        metadata={"role_id": role.id, "role_code": role.code},
        object_type="LaborRole",
    )
    return role


def update_labor_role(role: LaborRole, data, *, actor):
    require_role(actor, [Role.HQ, Role.CEO])
    before_active = role.is_active
    if "code" in data and data["code"]:
        role.code = str(data["code"]).strip().upper()
    if "name" in data and data["name"] is not None:
        role.name = str(data["name"]).strip()
    if "role_group" in data:
        role.role_group = str(data.get("role_group") or "").strip()
    if "sort_order" in data:
        role.sort_order = int(data.get("sort_order") or 0)
    if "is_active" in data:
        role.is_active = bool(data.get("is_active"))
    if "default_cbs" in data:
        role.default_cbs = _resolve_cost_item(data.get("default_cbs"))
    role.save()
    action = "LABOR_ROLE_UPDATE"
    if before_active and not role.is_active:
        action = "LABOR_ROLE_DEACTIVATE"
    _log_action_safe(
        actor=actor,
        action=action,
        object_id=role.id,
        summary=f"LaborRole update: {role.code}",
        metadata={"role_id": role.id, "role_code": role.code, "is_active": role.is_active},
        object_type="LaborRole",
    )
    return role


def create_rate(data, *, actor):
    require_role(actor, [Role.HQ, Role.CEO])
    role = data.get("labor_role")
    if not isinstance(role, LaborRole):
        role = LaborRole.objects.filter(id=role).first()
    if not role:
        raise ValidationError({"labor_role": "labor_role is required."})
    rate_type = str(data.get("rate_type") or LaborRateType.DAY)
    scope_type = str(data.get("scope_type") or LaborRateScope.GLOBAL)
    project = _resolve_project(data.get("project"))
    unit_rate = data.get("unit_rate")
    effective_from = data.get("effective_from")
    effective_to = data.get("effective_to")
    if unit_rate in (None, ""):
        raise ValidationError({"unit_rate": "unit_rate is required."})
    unit_rate = int(unit_rate)
    if unit_rate <= 0:
        raise ValidationError({"unit_rate": "unit_rate must be > 0."})
    if not effective_from:
        raise ValidationError({"effective_from": "effective_from is required."})
    if scope_type == LaborRateScope.PROJECT and not project:
        raise ValidationError({"project": "project is required for PROJECT rates."})
    if scope_type == LaborRateScope.GLOBAL:
        project = None
    if effective_to and effective_to < effective_from:
        raise ValidationError({"effective_to": "effective_to must be >= effective_from."})
    try:
        _validate_overlap(
            role=role,
            rate_type=rate_type,
            scope_type=scope_type,
            project=project,
            start=effective_from,
            end=effective_to,
        )
    except ValidationError as exc:
        _log_action_safe(
            actor=actor,
            action="LABOR_RATE_OVERLAP_BLOCKED",
            object_id=role.id,
            summary=f"LaborRate overlap blocked: {role.code}",
            metadata={
                "role_id": role.id,
                "role_code": role.code,
                "project_id": project.id if project else None,
                "scope_type": scope_type,
                "rate_type": rate_type,
                "effective_from": str(effective_from),
                "effective_to": str(effective_to) if effective_to else None,
            },
            object_type="LaborRateTable",
        )
        raise
    with transaction.atomic():
        rate = LaborRateTable.objects.create(
            labor_role=role,
            rate_type=rate_type,
            unit_rate=unit_rate,
            currency=str(data.get("currency") or "KRW"),
            effective_from=effective_from,
            effective_to=effective_to,
            scope_type=scope_type,
            project=project,
            is_active=bool(data.get("is_active", True)),
            note=str(data.get("note") or "").strip(),
            created_by=actor,
        )
    _log_action_safe(
        actor=actor,
        action="LABOR_RATE_CREATE",
        object_id=rate.id,
        summary=f"LaborRate create: {role.code}",
        metadata={
            "role_id": role.id,
            "role_code": role.code,
            "project_id": project.id if project else None,
            "scope_type": scope_type,
            "rate_type": rate_type,
            "unit_rate": unit_rate,
            "effective_from": str(effective_from),
            "effective_to": str(effective_to) if effective_to else None,
        },
        object_type="LaborRateTable",
    )
    return rate


def update_rate(rate: LaborRateTable, data, *, actor):
    require_role(actor, [Role.HQ, Role.CEO])
    role = rate.labor_role
    rate_type = str(data.get("rate_type") or rate.rate_type)
    scope_type = str(data.get("scope_type") or rate.scope_type)
    project = _resolve_project(data.get("project")) if "project" in data else rate.project
    unit_rate = data.get("unit_rate", rate.unit_rate)
    effective_from = data.get("effective_from", rate.effective_from)
    effective_to = data.get("effective_to", rate.effective_to)
    if unit_rate in (None, ""):
        raise ValidationError({"unit_rate": "unit_rate is required."})
    unit_rate = int(unit_rate)
    if unit_rate <= 0:
        raise ValidationError({"unit_rate": "unit_rate must be > 0."})
    if scope_type == LaborRateScope.PROJECT and not project:
        raise ValidationError({"project": "project is required for PROJECT rates."})
    if scope_type == LaborRateScope.GLOBAL:
        project = None
    if effective_to and effective_to < effective_from:
        raise ValidationError({"effective_to": "effective_to must be >= effective_from."})
    try:
        _validate_overlap(
            role=role,
            rate_type=rate_type,
            scope_type=scope_type,
            project=project,
            start=effective_from,
            end=effective_to,
            exclude_id=rate.id,
        )
    except ValidationError as exc:
        _log_action_safe(
            actor=actor,
            action="LABOR_RATE_OVERLAP_BLOCKED",
            object_id=rate.id,
            summary=f"LaborRate overlap blocked: {role.code}",
            metadata={
                "role_id": role.id,
                "role_code": role.code,
                "project_id": project.id if project else None,
                "scope_type": scope_type,
                "rate_type": rate_type,
                "effective_from": str(effective_from),
                "effective_to": str(effective_to) if effective_to else None,
            },
            object_type="LaborRateTable",
        )
        raise
    before_active = rate.is_active
    rate.rate_type = rate_type
    rate.scope_type = scope_type
    rate.project = project
    rate.unit_rate = unit_rate
    rate.effective_from = effective_from
    rate.effective_to = effective_to
    rate.currency = str(data.get("currency") or rate.currency or "KRW")
    if "note" in data:
        rate.note = str(data.get("note") or "").strip()
    if "is_active" in data:
        rate.is_active = bool(data.get("is_active"))
    rate.save()
    action = "LABOR_RATE_UPDATE"
    if before_active and not rate.is_active:
        action = "LABOR_RATE_DEACTIVATE"
    _log_action_safe(
        actor=actor,
        action=action,
        object_id=rate.id,
        summary=f"LaborRate update: {role.code}",
        metadata={
            "role_id": role.id,
            "role_code": role.code,
            "project_id": project.id if project else None,
            "scope_type": scope_type,
            "rate_type": rate_type,
            "unit_rate": unit_rate,
            "effective_from": str(effective_from),
            "effective_to": str(effective_to) if effective_to else None,
        },
        object_type="LaborRateTable",
    )
    return rate


def get_applicable_rate(project, labor_role, date, *, rate_type=LaborRateType.DAY):
    if not labor_role or not date:
        return None
    if not isinstance(labor_role, LaborRole):
        labor_role = LaborRole.objects.filter(id=labor_role).first()
    if not labor_role:
        return None
    if project and not isinstance(project, Project):
        project = Project.objects.filter(id=project).first()
    target_date = date if isinstance(date, date_type) else None
    if target_date is None:
        return None
    project_rate = (
        LaborRateTable.objects.filter(
            labor_role=labor_role,
            rate_type=rate_type,
            scope_type=LaborRateScope.PROJECT,
            project=project,
            is_active=True,
            effective_from__lte=target_date,
        )
        .filter(Q(effective_to__isnull=True) | Q(effective_to__gte=target_date))
        .order_by("-effective_from")
        .first()
    )
    if project_rate:
        return project_rate
    global_rate = (
        LaborRateTable.objects.filter(
            labor_role=labor_role,
            rate_type=rate_type,
            scope_type=LaborRateScope.GLOBAL,
            project__isnull=True,
            is_active=True,
            effective_from__lte=target_date,
        )
        .filter(Q(effective_to__isnull=True) | Q(effective_to__gte=target_date))
        .order_by("-effective_from")
        .first()
    )
    return global_rate


def _next_timesheet_no(work_date: date_type) -> str:
    key = f"TS-{work_date.strftime('%Y%m')}"
    with transaction.atomic():
        seq, _created = TimesheetNumberSequence.objects.select_for_update().get_or_create(
            key=key, defaults={"last_number": 0}
        )
        seq.last_number += 1
        seq.save(update_fields=["last_number"])
    return f"{key}-{seq.last_number:04d}"


def create_timesheet(*, project, work_date, actor, note="") -> Timesheet:
    require_role(actor, [Role.FIELD, Role.HQ, Role.CEO])
    require_project_access(actor, project.id)
    if not isinstance(work_date, date_type):
        raise ValidationError({"work_date": "\uc791\uc131\uc77c\uc744 \ud655\uc778\ud574 \uc8fc\uc138\uc694."})
    _assert_month_open(project, work_date, message_prefix="\ucd9c\uc5ed\ubd80 \uc785\ub825\uc740 \ubd88\uac00\ub2a5\ud569\ub2c8\ub2e4.")
    sheet_no = _next_timesheet_no(work_date)
    timesheet = Timesheet.objects.create(
        sheet_no=sheet_no,
        project=project,
        work_date=work_date,
        status=TimesheetStatus.DRAFT,
        note=note,
        created_by=actor,
    )
    _log_action_safe(
        actor=actor,
        action="TIMESHEET_CREATE",
        object_id=timesheet.id,
        summary=f"Timesheet create: {timesheet.sheet_no}",
        metadata={
            "timesheet_id": timesheet.id,
            "sheet_no": timesheet.sheet_no,
            "project_id": project.id,
            "work_date": str(work_date),
            "status": timesheet.status,
        },
        object_type="Timesheet",
    )
    return timesheet


def upsert_timesheet_lines(*, timesheet: Timesheet, lines_payload: list[dict], actor):
    require_role(actor, [Role.FIELD, Role.HQ, Role.CEO])
    _ensure_timesheet_editable(timesheet, actor=actor)
    _assert_month_open(timesheet.project, timesheet.work_date, message_prefix="\ucd9c\uc5ed\ubd80 \uc218\uc815\uc740 \ubd88\uac00\ub2a5\ud569\ub2c8\ub2e4.")
    cleaned_lines: list[dict] = []
    for raw in lines_payload:
        role_id = raw.get("labor_role_id") or raw.get("labor_role")
        if not role_id:
            continue
        labor_role = LaborRole.objects.filter(id=role_id, is_active=True).first()
        if not labor_role:
            raise ValidationError("\uc720\ud6a8\ud55c \uc9c1\uc885\uc744 \uc120\ud0dd\ud574 \uc8fc\uc138\uc694.")
        headcount = raw.get("headcount")
        if headcount in (None, ""):
            raise ValidationError("\uc778\uc6d0\uc744 \uc785\ub825\ud574 \uc8fc\uc138\uc694.")
        try:
            headcount_val = Decimal(str(headcount))
        except Exception:
            raise ValidationError("\uc778\uc6d0 \uac12\uc774 \uc62c\ubc14\ub974\uc9c0 \uc54a\uc2b5\ub2c8\ub2e4.")
        if headcount_val <= 0:
            raise ValidationError("\uc778\uc6d0\uc740 0\ubcf4\ub2e4 \ud070 \uac12\uc744 \uc785\ub825\ud574 \uc8fc\uc138\uc694.")
        rate_type = str(raw.get("rate_type") or LaborRateType.DAY)
        hours_val = None
        if rate_type == LaborRateType.HOUR:
            hours = raw.get("hours")
            if hours in (None, ""):
                raise ValidationError("\uc2dc\uac04\uc744 \uc785\ub825\ud574 \uc8fc\uc138\uc694.")
            try:
                hours_val = Decimal(str(hours))
            except Exception:
                raise ValidationError("\uc2dc\uac04 \uac12\uc774 \uc62c\ubc14\ub974\uc9c0 \uc54a\uc2b5\ub2c8\ub2e4.")
            if hours_val <= 0:
                raise ValidationError("\uc2dc\uac04\uc740 0\ubcf4\ub2e4 \ud070 \uac12\uc744 \uc785\ub825\ud574 \uc8fc\uc138\uc694.")
        cleaned_lines.append(
            {
                "labor_role": labor_role,
                "headcount": headcount_val,
                "hours": hours_val,
                "rate_type": rate_type,
                "memo": str(raw.get("memo") or "").strip(),
            }
        )
    if not cleaned_lines:
        raise ValidationError("\ucd9c\uc5ed \ub77c\uc778\uc740 \ucd5c\uc18c 1\uac1c \uc774\uc0c1 \ud544\uc694\ud569\ub2c8\ub2e4.")
    with transaction.atomic():
        TimesheetLine.objects.filter(timesheet=timesheet).delete()
        TimesheetLine.objects.bulk_create(
            [
                TimesheetLine(
                    timesheet=timesheet,
                    labor_role=line["labor_role"],
                    headcount=line["headcount"],
                    hours=line["hours"],
                    rate_type=line["rate_type"],
                    unit_rate=0,
                    amount=0,
                    memo=line["memo"],
                )
                for line in cleaned_lines
            ]
        )
        timesheet.save(update_fields=["updated_at"])
    _log_action_safe(
        actor=actor,
        action="TIMESHEET_UPDATE",
        object_id=timesheet.id,
        summary=f"Timesheet update: {timesheet.sheet_no}",
        metadata={
            "timesheet_id": timesheet.id,
            "sheet_no": timesheet.sheet_no,
            "project_id": timesheet.project_id,
            "work_date": str(timesheet.work_date),
            "line_count": len(cleaned_lines),
            "status": timesheet.status,
        },
        object_type="Timesheet",
    )
    return timesheet


def submit_timesheet(*, timesheet: Timesheet, actor):
    require_role(actor, [Role.FIELD, Role.HQ, Role.CEO])
    if timesheet.status not in (TimesheetStatus.DRAFT, TimesheetStatus.REJECTED):
        raise PermissionDenied("\uc81c\ucd9c \ud560 \uc218 \uc5c6\ub294 \uc0c1\ud0dc\uc785\ub2c8\ub2e4.")
    _assert_month_open(timesheet.project, timesheet.work_date, message_prefix="\ucd9c\uc5ed\ubd80 \uc81c\ucd9c\uc740 \ubd88\uac00\ub2a5\ud569\ub2c8\ub2e4.")
    lines = list(timesheet.lines.select_related("labor_role").all())
    if not lines:
        raise ValidationError("\ucd9c\uc5ed \ub77c\uc778\uc740 \ucd5c\uc18c 1\uac1c \uc774\uc0c1 \ud544\uc694\ud569\ub2c8\ub2e4.")
    total_amount = 0
    with transaction.atomic():
        for line in lines:
            rate = get_applicable_rate(
                timesheet.project,
                line.labor_role,
                timesheet.work_date,
                rate_type=line.rate_type,
            )
            if not rate:
                raise ValidationError("\uc9c1\uc885 \ub2e8\uac00\uac00 \ub4f1\ub85d\ub418\uc9c0 \uc54a\uc558\uc2b5\ub2c8\ub2e4.")
            unit_rate = int(rate.unit_rate)
            if line.rate_type == LaborRateType.HOUR:
                hours = line.hours or Decimal("0")
                amount = (line.headcount * hours * Decimal(unit_rate)).quantize(
                    Decimal("1"), rounding=ROUND_HALF_UP
                )
            else:
                amount = (line.headcount * Decimal(unit_rate)).quantize(
                    Decimal("1"), rounding=ROUND_HALF_UP
                )
            line.unit_rate = unit_rate
            line.amount = int(amount)
            line.save(update_fields=["unit_rate", "amount"])
            total_amount += int(amount)
        timesheet.status = TimesheetStatus.SUBMITTED
        timesheet.submitted_at = timezone.now()
        timesheet.save(update_fields=["status", "submitted_at", "updated_at"])
    _log_action_safe(
        actor=actor,
        action="TIMESHEET_SUBMIT",
        object_id=timesheet.id,
        summary=f"Timesheet submit: {timesheet.sheet_no}",
        metadata={
            "timesheet_id": timesheet.id,
            "sheet_no": timesheet.sheet_no,
            "project_id": timesheet.project_id,
            "work_date": str(timesheet.work_date),
            "line_count": len(lines),
            "total_amount": total_amount,
            "status": timesheet.status,
        },
        object_type="Timesheet",
    )
    return timesheet, total_amount


def approve_timesheet(*, timesheet: Timesheet, actor):
    require_role(actor, [Role.HQ, Role.CEO])
    if timesheet.status != TimesheetStatus.SUBMITTED:
        raise ValidationError("\uc81c\ucd9c \ub300\uae30 \uc0c1\ud0dc\uc758 \ucd9c\uc5ed\ubd80\ub9cc \uc2b9\uc778\ud560 \uc218 \uc788\uc2b5\ub2c8\ub2e4.")
    _assert_month_open(timesheet.project, timesheet.work_date, message_prefix="\ucd9c\uc5ed\ubd80 \uc2b9\uc778\uc740 \ubd88\uac00\ub2a5\ud569\ub2c8\ub2e4.")
    timesheet.status = TimesheetStatus.APPROVED
    timesheet.approved_at = timezone.now()
    timesheet.approved_by = actor
    timesheet.save(update_fields=["status", "approved_at", "approved_by", "updated_at"])
    _log_action_safe(
        actor=actor,
        action="TIMESHEET_APPROVE",
        object_id=timesheet.id,
        summary=f"Timesheet approve: {timesheet.sheet_no}",
        metadata={
            "timesheet_id": timesheet.id,
            "sheet_no": timesheet.sheet_no,
            "project_id": timesheet.project_id,
            "work_date": str(timesheet.work_date),
            "status": timesheet.status,
        },
        object_type="Timesheet",
    )
    return timesheet


def reject_timesheet(*, timesheet: Timesheet, actor, reason: str):
    require_role(actor, [Role.HQ, Role.CEO])
    if timesheet.status != TimesheetStatus.SUBMITTED:
        raise ValidationError("\uc81c\ucd9c \ub300\uae30 \uc0c1\ud0dc\uc758 \ucd9c\uc5ed\ubd80\ub9cc \ubc18\ub824\ud560 \uc218 \uc788\uc2b5\ub2c8\ub2e4.")
    if not reason:
        raise ValidationError("\ubc18\ub824 \uc0ac\uc720\ub97c \uc785\ub825\ud574 \uc8fc\uc138\uc694.")
    _assert_month_open(timesheet.project, timesheet.work_date, message_prefix="\ucd9c\uc5ed\ubd80 \ubc18\ub824\ub294 \ubd88\uac00\ub2a5\ud569\ub2c8\ub2e4.")
    timesheet.status = TimesheetStatus.REJECTED
    timesheet.rejected_at = timezone.now()
    timesheet.rejected_by = actor
    timesheet.reject_reason = reason
    timesheet.save(
        update_fields=[
            "status",
            "rejected_at",
            "rejected_by",
            "reject_reason",
            "updated_at",
        ]
    )
    _log_action_safe(
        actor=actor,
        action="TIMESHEET_REJECT",
        object_id=timesheet.id,
        summary=f"Timesheet reject: {timesheet.sheet_no}",
        metadata={
            "timesheet_id": timesheet.id,
            "sheet_no": timesheet.sheet_no,
            "project_id": timesheet.project_id,
            "work_date": str(timesheet.work_date),
            "status": timesheet.status,
        },
        object_type="Timesheet",
    )
    return timesheet


def _period_date(year: int, month: int) -> date_type:
    return date_type(int(year), int(month), 1)


def _next_payroll_batch_no(*, year: int, month: int) -> str:
    key = f"PA-{year:04d}{month:02d}"
    seq, _ = PayrollBatchNumberSequence.objects.select_for_update().get_or_create(
        key=key, defaults={"last_number": 0}
    )
    seq.last_number += 1
    seq.save(update_fields=["last_number"])
    return f"{key}-{seq.last_number:04d}"


def _ensure_payroll_editable(batch: PayrollAllocationBatch):
    if batch.status not in (PayrollAllocationStatus.DRAFT, PayrollAllocationStatus.REJECTED):
        raise PermissionDenied("제출 이후에는 수정할 수 없습니다.")


def create_payroll_batch(*, year: int, month: int, total_amount: int, actor, note: str = ""):
    require_role(actor, [Role.HQ, Role.CEO])
    period_date = _period_date(year, month)
    _assert_month_open(None, period_date, message_prefix="급여 배부 생성은 불가능합니다.")
    if total_amount is None:
        raise ValidationError({"total_amount": "total_amount is required."})
    total_amount = int(total_amount)
    if total_amount < 0:
        raise ValidationError({"total_amount": "total_amount must be >= 0."})
    if PayrollAllocationBatch.objects.filter(
        period_year=year, period_month=month
    ).exists():
        raise ValidationError("해당 월 배부가 이미 존재합니다.")
    with transaction.atomic():
        batch_no = _next_payroll_batch_no(year=year, month=month)
        batch = PayrollAllocationBatch.objects.create(
            batch_no=batch_no,
            period_year=year,
            period_month=month,
            total_amount=total_amount,
            note=note or "",
            created_by=actor,
        )
    _log_action_safe(
        actor=actor,
        action="PAYROLL_BATCH_CREATE",
        object_id=batch.id,
        summary=f"Payroll batch create: {batch.batch_no}",
        metadata={
            "batch_id": batch.id,
            "batch_no": batch.batch_no,
            "year": batch.period_year,
            "month": batch.period_month,
            "total_amount": batch.total_amount,
            "status": batch.status,
        },
        object_type="PayrollAllocationBatch",
    )
    return batch


def update_payroll_batch(batch: PayrollAllocationBatch, data: dict, *, actor):
    require_role(actor, [Role.HQ, Role.CEO])
    _ensure_payroll_editable(batch)
    period_date = _period_date(batch.period_year, batch.period_month)
    _assert_month_open(None, period_date, message_prefix="급여 배부 수정은 불가능합니다.")
    if "total_amount" in data and data["total_amount"] not in (None, ""):
        total_amount = int(data["total_amount"])
        if total_amount < 0:
            raise ValidationError({"total_amount": "total_amount must be >= 0."})
        batch.total_amount = total_amount
    if "note" in data:
        batch.note = str(data.get("note") or "")
    batch.save(update_fields=["total_amount", "note", "updated_at"])
    _log_action_safe(
        actor=actor,
        action="PAYROLL_BATCH_UPDATE",
        object_id=batch.id,
        summary=f"Payroll batch update: {batch.batch_no}",
        metadata={
            "batch_id": batch.id,
            "batch_no": batch.batch_no,
            "year": batch.period_year,
            "month": batch.period_month,
            "total_amount": batch.total_amount,
            "status": batch.status,
        },
        object_type="PayrollAllocationBatch",
    )
    return batch


def upsert_payroll_lines(
    batch: PayrollAllocationBatch, lines_payload: list[dict], *, actor
):
    require_role(actor, [Role.HQ, Role.CEO])
    _ensure_payroll_editable(batch)
    period_date = _period_date(batch.period_year, batch.period_month)
    _assert_month_open(None, period_date, message_prefix="급여 배부 수정은 불가능합니다.")
    cleaned: list[dict] = []
    for raw in lines_payload:
        project_id = raw.get("project_id") or raw.get("project")
        amount = raw.get("amount")
        if not project_id and amount in (None, "", 0):
            continue
        if not project_id:
            raise ValidationError("프로젝트를 선택해 주세요.")
        project = Project.objects.filter(id=project_id).first()
        if not project:
            raise ValidationError("유효한 프로젝트를 선택해 주세요.")
        if amount in (None, ""):
            raise ValidationError("배부 금액을 입력해 주세요.")
        amount_val = int(amount)
        if amount_val < 0:
            raise ValidationError("배부 금액은 0 이상이어야 합니다.")
        cbs = _resolve_cost_item(raw.get("cbs") or raw.get("cbs_id"))
        if cbs and hasattr(cbs, "is_active") and not cbs.is_active:
            raise ValidationError("비활성 CBS는 선택할 수 없습니다.")
        cleaned.append(
            {
                "project": project,
                "amount": amount_val,
                "cbs": cbs,
                "memo": str(raw.get("memo") or ""),
            }
        )
    if not cleaned:
        raise ValidationError("배부 라인은 최소 1개 이상 입력해야 합니다.")
    with transaction.atomic():
        PayrollAllocationLine.objects.filter(batch=batch).delete()
        PayrollAllocationLine.objects.bulk_create(
            [
                PayrollAllocationLine(
                    batch=batch,
                    project=line["project"],
                    cbs=line["cbs"],
                    amount=line["amount"],
                    memo=line["memo"],
                )
                for line in cleaned
            ]
        )
        batch.save(update_fields=["updated_at"])
    _log_action_safe(
        actor=actor,
        action="PAYROLL_LINES_UPDATE",
        object_id=batch.id,
        summary=f"Payroll lines update: {batch.batch_no}",
        metadata={
            "batch_id": batch.id,
            "batch_no": batch.batch_no,
            "year": batch.period_year,
            "month": batch.period_month,
            "line_count": len(cleaned),
        },
        object_type="PayrollAllocationBatch",
    )
    return batch


def validate_payroll_batch(batch: PayrollAllocationBatch):
    total_lines = (
        PayrollAllocationLine.objects.filter(batch=batch).aggregate(total=Sum("amount"))[
            "total"
        ]
        or 0
    )
    diff = int(batch.total_amount) - int(total_lines)
    return diff == 0, diff, int(total_lines)


def submit_payroll_batch(batch: PayrollAllocationBatch, *, actor):
    require_role(actor, [Role.HQ, Role.CEO])
    _ensure_payroll_editable(batch)
    period_date = _period_date(batch.period_year, batch.period_month)
    _assert_month_open(None, period_date, message_prefix="급여 배부 제출은 불가능합니다.")
    line_count = PayrollAllocationLine.objects.filter(batch=batch).count()
    if line_count == 0:
        raise ValidationError("배부 라인은 최소 1개 이상 입력해야 합니다.")
    ok, diff, sum_lines = validate_payroll_batch(batch)
    if not ok:
        _log_action_safe(
            actor=actor,
            action="PAYROLL_BATCH_VALIDATE_FAIL",
            object_id=batch.id,
            summary=f"Payroll batch validate fail: {batch.batch_no}",
            metadata={
                "batch_id": batch.id,
                "batch_no": batch.batch_no,
                "year": batch.period_year,
                "month": batch.period_month,
                "sum_lines": sum_lines,
                "total_amount": batch.total_amount,
                "diff": diff,
            },
            object_type="PayrollAllocationBatch",
        )
        raise ValidationError("배부 합계가 총액과 일치하지 않습니다.")
    batch.status = PayrollAllocationStatus.SUBMITTED
    batch.submitted_at = timezone.now()
    batch.save(update_fields=["status", "submitted_at", "updated_at"])
    _log_action_safe(
        actor=actor,
        action="PAYROLL_BATCH_SUBMIT",
        object_id=batch.id,
        summary=f"Payroll batch submit: {batch.batch_no}",
        metadata={
            "batch_id": batch.id,
            "batch_no": batch.batch_no,
            "year": batch.period_year,
            "month": batch.period_month,
            "sum_lines": sum_lines,
            "total_amount": batch.total_amount,
            "status": batch.status,
        },
        object_type="PayrollAllocationBatch",
    )
    return batch, sum_lines, diff
