from datetime import date

from django.core.exceptions import PermissionDenied, ValidationError
from django.db import models, transaction
from django.utils import timezone

from apps.audit.services.logger import log_action

from apps.contracts.models import ContractChange, ContractChangeStatus
from apps.inventory.models import Stock, Warehouse, WarehouseType
from apps.projects.models import ApprovalPackage, ApprovalPackageStatus, Project, WBSChangeRequest, WBSChangeRequestStatus

from .models import ClosingPeriod, ClosingStatus, ProjectClose, ProjectCloseStatus


def _validate_year_month(year: int, month: int) -> None:
    if month < 1 or month > 12:
        raise ValidationError("month must be between 1 and 12.")


def get_closing_period(year: int, month: int) -> ClosingPeriod | None:
    _validate_year_month(year, month)
    return ClosingPeriod.objects.filter(year=year, month=month).first()


def is_month_closed(target_date: date) -> bool:
    period = ClosingPeriod.objects.filter(
        year=target_date.year, month=target_date.month
    ).first()
    return bool(period and period.status == ClosingStatus.CLOSED)


def assert_month_open(target_date: date) -> None:
    if is_month_closed(target_date):
        raise PermissionDenied("Month is closed.")


def close_month(year: int, month: int, actor, note: str | None = None) -> ClosingPeriod:
    _validate_year_month(year, month)
    with transaction.atomic():
        period, _created = ClosingPeriod.objects.select_for_update().get_or_create(
            year=year, month=month, defaults={"status": ClosingStatus.OPEN}
        )
        if period.status == ClosingStatus.CLOSED:
            raise ValidationError("ClosingPeriod is already closed.")
        period.status = ClosingStatus.CLOSED
        period.closed_at = timezone.now()
        period.closed_by = actor
        if note is not None:
            period.note = note
        period.save()
        log_action(
            actor=actor,
            action="MONTH_CLOSED",
            object_type="ClosingPeriod",
            object_id=period.id,
            meta={"year": year, "month": month},
        )
        return period


def get_project_close(project: Project) -> ProjectClose:
    close, _created = ProjectClose.objects.get_or_create(project=project)
    return close


def is_project_closed(project: Project | None) -> bool:
    if project is None:
        return False
    close = getattr(project, "close", None)
    if close is None:
        close = ProjectClose.objects.filter(project=project).first()
    return bool(close and close.status == ProjectCloseStatus.CLOSED)


def validate_project_close(project: Project, *, effective_date: date | None = None) -> dict:
    """Validate if project can be closed. Returns dict with ok/blocks/warns/stats."""
    blocks: list[str] = []
    warns: list[str] = []
    stats: dict = {}

    pending_wbs = WBSChangeRequest.objects.filter(
        project=project, status=WBSChangeRequestStatus.SUBMITTED
    ).count()
    stats["pending_wbs"] = pending_wbs
    if pending_wbs:
        blocks.append("승인 대기 중인 WBS 변경 요청이 있습니다.")

    pending_packages = ApprovalPackage.objects.filter(
        project=project, status=ApprovalPackageStatus.SUBMITTED
    ).count()
    stats["pending_packages"] = pending_packages
    if pending_packages:
        blocks.append("승인 대기 중인 패키지 요청이 있습니다.")

    pending_changes = ContractChange.objects.filter(
        project=project, status=ContractChangeStatus.SUBMITTED
    ).count()
    stats["pending_contract_changes"] = pending_changes
    if pending_changes:
        blocks.append("승인 대기 중인 계약 변경이 있습니다.")

    target_date = (
        effective_date
        or getattr(project, "end_date", None)
        or date.today()
    )
    if target_date and not is_month_closed(target_date):
        blocks.append("프로젝트 종료월이 월 마감되지 않았습니다.")

    site_warehouses = Warehouse.objects.filter(
        warehouse_type=WarehouseType.SITE, project=project, is_active=True
    )
    stock_total = (
        Stock.objects.filter(warehouse__in=site_warehouses, qty_on_hand__gt=0)
        .aggregate(total=models.Sum("qty_on_hand"))
        .get("total")
        or 0
    )
    stats["stock_total"] = float(stock_total)
    if stock_total > 0:
        blocks.append("현장 재고가 남아 있습니다.")

    ok = len(blocks) == 0
    return {"ok": ok, "blocks": blocks, "warns": warns, "stats": stats}


def submit_project_close(project: Project, *, actor, note: str = "") -> ProjectClose:
    close = get_project_close(project)
    if close.status == ProjectCloseStatus.CLOSED:
        raise ValidationError("Project is already closed.")
    close.status = ProjectCloseStatus.CLOSING
    close.note = note or close.note
    close.save(update_fields=["status", "note", "updated_at"])
    log_action(
        actor=actor,
        action="PROJECT_CLOSE_SUBMIT",
        object_type="ProjectClose",
        object_id=close.id,
        project=project,
        meta={"project_id": project.id, "status": close.status},
    )
    return close


def approve_project_close(project: Project, *, actor, effective_date: date | None = None) -> ProjectClose:
    close = get_project_close(project)
    if close.status != ProjectCloseStatus.CLOSING:
        raise ValidationError("Project close request is not in closing state.")
    validation = validate_project_close(project, effective_date=effective_date)
    if not validation["ok"]:
        log_action(
            actor=actor,
            action="PROJECT_CLOSE_BLOCKED_VALIDATION_FAIL",
            object_type="ProjectClose",
            object_id=close.id,
            project=project,
            meta=validation,
        )
        raise ValidationError("???? ?? ??? ??????.")
    close.status = ProjectCloseStatus.CLOSED
    close.close_effective_date = effective_date or close.close_effective_date
    close.closed_at = timezone.now()
    close.closed_by = actor
    close.save(update_fields=["status", "close_effective_date", "closed_at", "closed_by", "updated_at"])
    log_action(
        actor=actor,
        action="PROJECT_CLOSE_APPROVE_AND_EXECUTE",
        object_type="ProjectClose",
        object_id=close.id,
        project=project,
        meta={"project_id": project.id, "status": close.status},
    )
    return close


def reject_project_close(project: Project, *, actor, note: str = "") -> ProjectClose:
    close = get_project_close(project)
    if close.status != ProjectCloseStatus.CLOSING:
        raise ValidationError("Project close request is not in closing state.")
    close.status = ProjectCloseStatus.OPEN
    if note:
        close.note = note
    close.save(update_fields=["status", "note", "updated_at"])
    log_action(
        actor=actor,
        action="PROJECT_CLOSE_REJECT",
        object_type="ProjectClose",
        object_id=close.id,
        project=project,
        meta={"project_id": project.id, "status": close.status},
    )
    return close
