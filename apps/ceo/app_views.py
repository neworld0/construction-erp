from __future__ import annotations

from datetime import date
from urllib.parse import urlencode
from decimal import Decimal
import logging
import re

from django.contrib import messages
from django.contrib.auth.decorators import login_required
from django.apps import apps
from django.core.exceptions import PermissionDenied, ValidationError
from django.db import transaction
from django.db.models import Count, Sum
from django.shortcuts import get_object_or_404, redirect, render
from django.utils import timezone

from apps.closing.guards import guard_write
from apps.closing.models import Adjustment, AdjustmentStatus, ClosingApprovalPolicy, ClosingPeriod
from apps.core.rbac.models import Role
from apps.core.rbac.permissions import get_user_legal_entities, get_user_role, require_role
from apps.audit.services.logger import log_action
from apps.contracts.models import ContractChange, ContractChangeStatus
from apps.contracts.services import approve_contract_change
from apps.projects.models import (
    ApprovalPackage,
    ApprovalPackageStatus,
    Project,
    WBSChangeLine,
    WBSChangeRequest,
    WBSChangeRequestStatus,
    WBSChangeRequestType,
    WBSItem,
)
from apps.cost.models import CostActual, CostActualLine, CostActualStatus, RevenueRecognition, RevenueRecognitionClose
from apps.evidence.models import Evidence
from apps.evidence.services.policy import check_evidence_required
from apps.field.models import DailyReport, DailyReportStatus
from apps.labor.models import (
    OfficePayrollCorrection,
    OfficePayrollCorrectionStatus,
    PayrollAllocationLine,
    PayrollAllocationStatus,
    Timesheet,
    TimesheetLine,
    TimesheetStatus,
)
from apps.labor.services import approve_timesheet, reject_timesheet
from apps.projects.services.approval_package import approve_package, reject_package
from apps.projects.services.wbs_change_approval import approve_wbs_change_request
from apps.finance.models import AdvancePayment, CashEvent, CashEventStatus, CashEventType, ProgressBilling, ProgressBillingStatus
from apps.finance.services.profit_loss import _calculate_margin
from apps.finance.services.progress_billing import get_advance_billing_summary
from apps.risk.models import RiskFinding, RiskFindingStatus, RiskSeverity
from apps.risk.dashboard_visibility import get_operational_dashboard_risk_queryset
from apps.schedule.models import DailyProgress, PlanChangeRequest, PlanChangeStatus, ProgressCorrectionRequest, ScheduleTask
from apps.schedule.services.plan_change import approve_change_request
from apps.core.models import ApprovalRequest, ApprovalStatus
from apps.core.services.approvals import approve_request, reject_request
from apps.reports.models import FieldReport, FieldReportStatus

from .services.dashboard import get_ceo_dashboard, get_ceo_projects_list
from .services.kpi_engine import compute_project_kpi
from .services.kpi_utils import (
    build_trend,
    compare_windows,
    project_elapsed_percent,
    schedule_status,
)
from .risk_summary import build_risk_summary
from .services.progress_comparison import build_portfolio_progress_comparison

logger = logging.getLogger(__name__)


def _parse_date(value):
    if not value:
        return None
    try:
        return date.fromisoformat(value)
    except ValueError:
        return None


def _safe_decimal(value):
    return value if value is not None else Decimal("0")


def _resolve_ceo_entity_scope(request):
    """Return a membership-bound CEO dashboard scope, never an unrestricted one."""
    entities = list(get_user_legal_entities(request.user))
    by_code = {entity.code: entity for entity in entities}
    requested = (
        request.GET.get("entity_scope")
        or (request.session.get("current_entity_scope") if hasattr(request, "session") else "")
        or ""
    ).upper()
    has_group_scope = {"ASAN", "MISAN"}.issubset(by_code)
    if requested == "GROUP" and has_group_scope:
        return "GROUP", [by_code["ASAN"].id, by_code["MISAN"].id], "아미산"
    if requested in by_code:
        return requested, [by_code[requested].id], by_code[requested].legal_name
    if has_group_scope:
        return "GROUP", [by_code["ASAN"].id, by_code["MISAN"].id], "아미산"
    if entities:
        entity = entities[0]
        return entity.code, [entity.id], entity.legal_name
    return "NONE", [], "조회 가능 법인 없음"


def _cash_summary(project_ids, date_from, date_to):
    if not project_ids:
        return {
            "inflow_confirmed": Decimal("0"),
            "outflow_confirmed": Decimal("0"),
            "net_confirmed": Decimal("0"),
            "inflow_planned": Decimal("0"),
            "outflow_planned": Decimal("0"),
            "net_planned": Decimal("0"),
        }
    rows = (
        CashEvent.objects.filter(
            project_id__in=project_ids, event_date__gte=date_from, event_date__lte=date_to
        )
        .values("status", "event_type")
        .annotate(total=Sum("amount"))
    )
    summary = {
        "inflow_confirmed": Decimal("0"),
        "outflow_confirmed": Decimal("0"),
        "net_confirmed": Decimal("0"),
        "inflow_planned": Decimal("0"),
        "outflow_planned": Decimal("0"),
        "net_planned": Decimal("0"),
    }
    for row in rows:
        status = row["status"]
        event_type = row["event_type"]
        total = row["total"] or Decimal("0")
        if status == CashEventStatus.CONFIRMED:
            if event_type == CashEventType.IN:
                summary["inflow_confirmed"] += total
            else:
                summary["outflow_confirmed"] += total
        if status == CashEventStatus.PLANNED:
            if event_type == CashEventType.IN:
                summary["inflow_planned"] += total
            else:
                summary["outflow_planned"] += total
    summary["net_confirmed"] = summary["inflow_confirmed"] - summary["outflow_confirmed"]
    summary["net_planned"] = summary["inflow_planned"] - summary["outflow_planned"]
    return summary


_TYPE_LABELS = {
    "APPROVAL_REQUEST": "승인요청",
    "PROJECT_BASELINE": "프로젝트 기준선",
    "DAILY_PROGRESS": "진행률",
    "PROGRESS_CORRECTION": "진행률 정정·취소",
    "DAILY_REPORT": "일일보고",
    "FIELD_REPORT": "기존 현장보고",
    "COST_ACTUAL": "원가",
    "CONTRACT_CHANGE": "변경요청(계약)",
    "PLAN_CHANGE_REQUEST": "변경요청(계획)",
    "WBS_CHANGE_REQUEST": "WBS 변경",
    "APPROVAL_PACKAGE": "승인 패키지",
    "ADJUSTMENT": "정정",
    "TIMESHEET": "출역부",
    "PAYROLLALLOCATIONBATCH": "급여 배부",
    "PAYROLL_BATCH": "급여 배부",
    "OFFICE_PAYROLL_CORRECTION": "본사 급여 정정",
}


def _detail_url_for_item(object_type: str, object_id: int) -> str:
    mapping = {
        "APPROVAL_REQUEST": f"/app/ceo/approvals/{object_id}/",
        "DAILY_REPORT": f"/app/ceo/reports/{object_id}/",
        "DAILY_PROGRESS": f"/app/ceo/progress/{object_id}/",
        "PROGRESS_CORRECTION": f"/app/ceo/progress/corrections/{object_id}/",
        "FIELD_REPORT": f"/app/ceo/field-reports/{object_id}/",
        "COST_ACTUAL": f"/app/ceo/costs/{object_id}/",
        "CONTRACT_CHANGE": f"/app/ceo/contract-changes/{object_id}/",
        "PLAN_CHANGE_REQUEST": f"/app/ceo/plan-change-requests/{object_id}/",
        "WBS_CHANGE_REQUEST": f"/app/ceo/wbs-change/requests/{object_id}/",
        "APPROVAL_PACKAGE": f"/app/ceo/approval-packages/{object_id}/",
        "ADJUSTMENT": f"/app/ceo/adjustments/{object_id}/",
        "TIMESHEET": f"/app/ceo/labor/timesheets/{object_id}/",
        "OFFICE_PAYROLL_CORRECTION": f"/app/hq/labor/office-payroll/corrections/{object_id}/",
    }
    return mapping.get(object_type, "")

def _resolve_approval_target(approval: ApprovalRequest):
    object_type = (approval.object_type or "").upper()
    object_id = approval.object_id
    visited = set()
    while object_type == "APPROVAL_REQUEST" and object_id and object_id not in visited:
        visited.add(object_id)
        nested = ApprovalRequest.objects.filter(id=object_id).first()
        if nested is None:
            break
        object_type = (nested.object_type or "").upper()
        object_id = nested.object_id
    return object_type, object_id

def _build_recent_approved_items(limit: int = 10):
    approved_qs = (
        ApprovalRequest.objects.filter(status=ApprovalStatus.APPROVED)
        .select_related("approved_by", "submitted_by")
        .order_by("-approved_at", "-updated_at", "-created_at")
    )
    items = []
    for approval in approved_qs:
        target_type, target_id = _resolve_approval_target(approval)
        target_obj = None
        if target_type and target_id:
            model_map = {
                "PROJECT_BASELINE": Project,
                "CONTRACT_CHANGE": ContractChange,
                "PLAN_CHANGE_REQUEST": PlanChangeRequest,
                "WBS_CHANGE_REQUEST": WBSChangeRequest,
                "ADJUSTMENT": Adjustment,
                "TIMESHEET": Timesheet,
                "APPROVAL_PACKAGE": ApprovalPackage,
                "COST_ACTUAL": CostActual,
                "DAILY_REPORT": DailyReport,
                "DAILY_PROGRESS": DailyProgress,
                "PROGRESS_CORRECTION": ProgressCorrectionRequest,
                "FIELD_REPORT": FieldReport,
            }
            model = model_map.get(target_type)
            if model:
                if target_type == "PROJECT_BASELINE":
                    target_obj = model.objects.filter(id=target_id).first()
                else:
                    rels = ["project"]
                    if target_type == "DAILY_PROGRESS":
                        rels.append("task")
                    target_obj = model.objects.filter(id=target_id).select_related(*rels).first()
        project = target_obj if target_type == "PROJECT_BASELINE" else getattr(target_obj, "project", None)
        # ApprovalRequest has no project FK. Do not present a deleted target as
        # a "전사" approval on the operational CEO dashboard.
        if project is None or not project.is_active:
            continue
        title, detail = _build_target_summary(
            target_type,
            target_obj,
            f"{target_type or 'APPROVAL'} #{target_id or approval.id}",
        )
        formatted_detail = _format_amount_tokens(str(detail or ""))
        items.append(
            {
                "object_type": target_type or (approval.object_type or "").upper(),
                "object_id": target_id or approval.object_id,
                "project_id": project.id,
                "type_label": _TYPE_LABELS.get(target_type or "", "승인요청"),
                "project_name": project.name if project else "전사",
                "title": title,
                "detail_summary": formatted_detail,
                "detail_summary_display": formatted_detail,
                "approved_at": approval.approved_at or approval.updated_at or approval.created_at,
                "approved_by_name": (
                    approval.approved_by.get_username()
                    if getattr(approval.approved_by, "get_username", None)
                    else "-"
                ),
                "detail_url": _detail_url_for_item(target_type, target_id)
                if target_type and target_id
                else "",
                "attachments": _get_attachments_for_object(target_type, target_id),
            }
        )
        if len(items) >= limit:
            break
    return items


def _get_attachments_for_object(object_type: str, object_id: int):
    normalized_type = (object_type or "").upper().strip()
    if not normalized_type or not object_id:
        return []
    evidences = (
        Evidence.objects.filter(object_type=normalized_type, object_id=object_id)
        .prefetch_related("files")
        .order_by("-created_at")
    )
    files = []
    seen_ids = set()
    for evidence in evidences:
        for evidence_file in evidence.files.all().order_by("-created_at"):
            if evidence_file.id in seen_ids:
                continue
            seen_ids.add(evidence_file.id)
            files.append(evidence_file)
    return files


def _build_target_summary(object_type: str, obj, fallback_title: str):
    if obj is None:
        return fallback_title, ""

    if object_type == "PROJECT_BASELINE":
        project_code = (getattr(obj, "code", "") or "").strip()
        title = "프로젝트 기준선 승인"
        detail = f"프로젝트 코드 {project_code}" if project_code else "프로젝트 기준선"
        return title, detail

    if object_type == "DAILY_PROGRESS":
        task_name = getattr(getattr(obj, "task", None), "name", "-")
        progress = getattr(obj, "progress_percent", None)
        report_date = getattr(obj, "report_date", None)
        title = f"{task_name} / {progress}%" if progress is not None else task_name
        detail = f"작성일 {report_date:%Y-%m-%d}" if report_date else ""
        return title, detail

    if object_type == "PROGRESS_CORRECTION":
        action = "취소" if obj.correction_type == "CANCEL" else "정정"
        return f"진행률 {action} 요청", f"원본 #{obj.original_progress_id} / {obj.original_report_date:%Y-%m-%d}"

    if object_type == "DAILY_REPORT":
        report_date = getattr(obj, "report_date", None)
        note = (getattr(obj, "note", "") or "").strip()
        title = f"일일보고 / {report_date:%Y-%m-%d}" if report_date else "일일보고"
        return title, (note[:80] if note else "")

    if object_type == "FIELD_REPORT":
        report_date = getattr(obj, "report_date", None)
        title_text = (getattr(obj, "title", "") or "현장보고서").strip()
        title = f"{title_text} / {report_date:%Y-%m-%d}" if report_date else title_text
        return title, ""

    if object_type == "COST_ACTUAL":
        report_date = getattr(obj, "report_date", None)
        total_amount = getattr(obj, "total_amount", None)
        title = f"원가 실적 / {report_date:%Y-%m-%d}" if report_date else "원가 실적"
        if total_amount is not None:
            try:
                amount_text = f"{float(total_amount):,.2f}"
            except (TypeError, ValueError):
                amount_text = str(total_amount)
            detail = f"합계 {amount_text}"
        else:
            detail = ""
        return title, detail

    if object_type == "TIMESHEET":
        return fallback_title, f"작성일 {obj.work_date:%Y-%m-%d}"

    if object_type in {"CONTRACT_CHANGE", "PLAN_CHANGE_REQUEST", "WBS_CHANGE_REQUEST", "ADJUSTMENT"}:
        reason = (getattr(obj, "reason", "") or "").strip()
        return fallback_title, (reason[:80] if reason else "")

    return fallback_title, ""


def _risk_rank(item):
    if item.get("risk_critical"):
        return 0
    if item.get("risk_high"):
        return 1
    return 2


def _submitted_at_value(item):
    submitted_at = item.get("submitted_at")
    if submitted_at is None:
        return timezone.now()
    if timezone.is_naive(submitted_at):
        return timezone.make_aware(submitted_at, timezone.get_current_timezone())
    return submitted_at


_AMOUNT_TOKEN_RE = re.compile(r"\b(\d{4,})(\.\d+)?\b")


def _format_amount_tokens(text: str) -> str:
    if not text:
        return text

    def _replace(match):
        integer_part = match.group(1)
        decimal_part = match.group(2) or ""
        # Keep date fragments like 2026-02-12 untouched.
        if len(integer_part) == 4:
            next_index = match.end()
            if next_index < len(text) and text[next_index] in ("-", "/"):
                return match.group(0)
        try:
            formatted_integer = f"{int(integer_part):,}"
        except (TypeError, ValueError):
            return match.group(0)
        return f"{formatted_integer}{decimal_part}"

    return _AMOUNT_TOKEN_RE.sub(_replace, text)



def _ceo_next_url(request, default: str = "/app/ceo/") -> str:
    next_url = (request.POST.get("next") or request.GET.get("next") or "").strip()
    if next_url.startswith("/app/ceo/"):
        return next_url
    return default

def _as_datetime(value):
    if value is None:
        return None
    if isinstance(value, date):
        return timezone.make_aware(
            timezone.datetime.combine(value, timezone.datetime.min.time()),
            timezone.get_current_timezone(),
        )
    return value


def _resolve_guard_context(item):
    object_type = item["object_type"]
    obj = item.get("_obj")
    if obj is None:
        return item.get("project"), timezone.localdate()

    if object_type == "APPROVAL_REQUEST":
        nested_type = ((obj.object_type or "").strip()).upper()
        nested_item = {
            "object_type": nested_type,
            "object_id": obj.object_id,
            "project": item.get("project"),
            "_obj": item.get("_target_obj"),
        }
        return _resolve_guard_context(nested_item)
    if object_type == "ADJUSTMENT":
        return obj.project, obj.period_date
    if object_type == "PROGRESS_CORRECTION":
        return obj.project, obj.original_report_date
    if object_type in {"DAILY_PROGRESS", "DAILY_REPORT", "FIELD_REPORT", "COST_ACTUAL"}:
        # ApprovalRequest has no own business date.  Use the underlying
        # field record's report date, not the approval submission date or
        # today's date, when checking the monthly-close guard.
        return obj.project, obj.report_date
    if object_type == "TIMESHEET":
        return obj.project, obj.work_date
    if object_type == "PLAN_CHANGE_REQUEST":
        target_dt = _as_datetime(obj.requested_at) or obj.updated_at
        return obj.project, target_dt.date()
    if object_type == "CONTRACT_CHANGE":
        target_dt = _as_datetime(obj.submitted_at) or obj.updated_at
        return obj.project, target_dt.date()
    if object_type == "WBS_CHANGE_REQUEST":
        target_dt = _as_datetime(obj.created_at) or obj.updated_at
        return obj.project, target_dt.date()
    if object_type == "APPROVAL_PACKAGE":
        target_dt = _as_datetime(obj.submitted_at) or obj.updated_at
        return obj.project, target_dt.date()
    return item.get("project"), timezone.localdate()


def _check_quick_action_allowed(item):
    # A closing-period approval is the control action that closes a month;
    # it is not a back-dated business transaction.  Applying the common
    # write guard here incorrectly checks today's already-closed month and
    # blocks approval of a different, still-open target month.
    approval = item.get("_obj")
    # Approving a payroll-correction request does not itself rewrite a closed
    # payroll period; the separately audited HQ "apply" action does that.
    if (item.get("object_type") or "").upper() == "OFFICE_PAYROLL_CORRECTION":
        return True, ""
    if isinstance(approval, ApprovalRequest):
        target_type, _target_id = _resolve_approval_target(approval)
        if target_type == "CLOSING_PERIOD":
            return True, ""

    project, target_date = _resolve_guard_context(item)
    try:
        guard_write(
            project=project,
            target_date=target_date,
            message_context="승인 처리는 불가능합니다.",
        )
    except PermissionDenied as exc:
        return False, str(exc)
    return True, ""


def _build_pending_items():
    # Discovery:
    # - Primary source: ApprovalRequest(status=submitted) from apps.core.models
    # - Additional CEO-final queues: ContractChange, PlanChangeRequest, WBSChangeRequest,
    #   ApprovalPackage, Adjustment, Timesheet.
    # - Detail URLs reuse existing HQ/CEO detail pages.
    items = []

    approval_qs = ApprovalRequest.objects.filter(status=ApprovalStatus.SUBMITTED).select_related(
        "submitted_by"
    )
    report_approval_ids = set()
    for approval in approval_qs:
        resolved_type, resolved_id = _resolve_approval_target(approval)
        if resolved_type == "CLOSING_PERIOD":
            period = ClosingPeriod.objects.filter(id=resolved_id).only("approval_policy").first()
            if period is None or period.approval_policy != ClosingApprovalPolicy.CEO:
                continue
        item = {
            "object_type": "APPROVAL_REQUEST",
            "object_id": approval.id,
            "title": f"{(approval.object_type or '').upper()} #{approval.object_id}",
            "detail_summary": "",
            "project": None,
            "submitted_at": approval.submitted_at or approval.created_at,
            "submitted_by": approval.submitted_by,
            "detail_url": _detail_url_for_item("APPROVAL_REQUEST", approval.id),
            "_obj": approval,
            "display_object_type": resolved_type or ((approval.object_type or "").strip()).upper(),
        }
        target_type = resolved_type
        target_id = resolved_id
        if target_type and target_id:
            model_map = {
                "CONTRACT_CHANGE": ContractChange,
                "PLAN_CHANGE_REQUEST": PlanChangeRequest,
                "WBS_CHANGE_REQUEST": WBSChangeRequest,
                "ADJUSTMENT": Adjustment,
                "TIMESHEET": Timesheet,
                "APPROVAL_PACKAGE": ApprovalPackage,
                "COST_ACTUAL": CostActual,
                "DAILY_REPORT": DailyReport,
                "DAILY_PROGRESS": DailyProgress,
                "PROGRESS_CORRECTION": ProgressCorrectionRequest,
                "FIELD_REPORT": FieldReport,
            }
            model = model_map.get(target_type)
            if model:
                rels = ["project"]
                if target_type == "DAILY_PROGRESS":
                    rels.append("task")
                target_obj = model.objects.filter(id=target_id).select_related(*rels).first()
                item["_target_obj"] = target_obj
                project = getattr(target_obj, "project", None)
                if project is not None:
                    item["project"] = project
                target_detail_url = _detail_url_for_item(target_type, target_id)
                if target_detail_url:
                    item["detail_url"] = target_detail_url
                item["title"], item["detail_summary"] = _build_target_summary(
                    target_type,
                    target_obj,
                    item["title"],
                )
            if target_type == "FIELD_REPORT":
                report_approval_ids.add(target_id)
        items.append(item)

    missing_reports_qs = FieldReport.objects.filter(status=FieldReportStatus.SUBMITTED)
    if report_approval_ids:
        missing_reports_qs = missing_reports_qs.exclude(id__in=report_approval_ids)
    for report in missing_reports_qs.select_related("project", "created_by"):
        title, detail = _build_target_summary(
            "FIELD_REPORT",
            report,
            (report.title or "").strip() or "현장보고서",
        )
        items.append(
            {
                "object_type": "FIELD_REPORT",
                "object_id": report.id,
                "title": title,
                "detail_summary": detail,
                "project": report.project,
                "submitted_at": report.submitted_at or report.updated_at or report.created_at,
                "submitted_by": report.created_by,
                "detail_url": _detail_url_for_item("FIELD_REPORT", report.id),
                "_obj": report,
            }
        )

    # Payroll corrections have their own audited workflow rather than a core
    # ApprovalRequest.  Surface them in the same CEO inbox so a required
    # second-person approval cannot be missed.
    for correction in OfficePayrollCorrection.objects.filter(
        status=OfficePayrollCorrectionStatus.SUBMITTED
    ).select_related("run", "requested_by"):
        items.append(
            {
                "object_type": "OFFICE_PAYROLL_CORRECTION",
                "object_id": correction.id,
                "title": f"{correction.run.period_year}년 {correction.run.period_month}월 본사 급여 정정 요청",
                "detail_summary": (correction.reason or "정정 사유 미입력")[:80],
                "project": None,
                "submitted_at": correction.submitted_at or correction.updated_at or correction.created_at,
                "submitted_by": correction.requested_by,
                "detail_url": _detail_url_for_item("OFFICE_PAYROLL_CORRECTION", correction.id),
                "_obj": correction,
            }
        )

    return _decorate_pending_items(items)


def _decorate_pending_items(items):
    now = timezone.now()
    for item in items:
        object_type = (item.get("object_type") or "").upper()
        display_object_type = (item.get("display_object_type") or object_type).upper()
        project = item.get("project")
        submitted_by = item.get("submitted_by")
        submitted_at = item.get("submitted_at")

        item["type_label"] = _TYPE_LABELS.get(display_object_type, _TYPE_LABELS.get(object_type, "승인요청"))
        item["project_name"] = project.name if project else "전사"
        item["submitted_by_name"] = (
            submitted_by.get_username()
            if submitted_by and getattr(submitted_by, "get_username", None)
            else "-"
        )
        item["submitted_at"] = submitted_at

        submitted_ts = _submitted_at_value(item)
        elapsed = now - submitted_ts
        item["is_overdue_48h"] = elapsed >= timezone.timedelta(hours=48)
        item["is_overdue_24h"] = elapsed >= timezone.timedelta(hours=24)

        item["risk_critical"] = bool(item.get("risk_critical"))
        item["risk_high"] = bool(item.get("risk_high"))
        formatted_summary = _format_amount_tokens(str(item.get("detail_summary", "") or ""))
        item["detail_summary"] = formatted_summary
        item["detail_summary_display"] = formatted_summary

        can_process = object_type in {"APPROVAL_REQUEST", "OFFICE_PAYROLL_CORRECTION"}
        if can_process:
            allowed, block_message = _check_quick_action_allowed(item)
            item["can_approve"] = allowed
            item["can_reject"] = allowed
            item["block_message"] = block_message if not allowed else ""
        else:
            item["can_approve"] = False
            item["can_reject"] = False
    return items


def _find_pending_item(object_type, object_id):
    object_type = (object_type or "").upper().strip()
    try:
        object_id = int(object_id)
    except (TypeError, ValueError):
        return None
    for item in _build_pending_items():
        if (item.get("object_type") or "").upper() == object_type and item.get("object_id") == object_id:
            return item
    return None


def _run_ceo_quick_action(object_type, object_id, action, actor, request=None, reason=None):
    object_type = (object_type or "").upper().strip()
    if object_type == "APPROVAL_REQUEST":
        if action == "approve":
            return approve_request(object_id, actor, request=request)
        if action == "reject":
            return reject_request(object_id, actor, reject_reason=reason, request=request)
    if object_type == "OFFICE_PAYROLL_CORRECTION":
        with transaction.atomic():
            correction = OfficePayrollCorrection.objects.select_for_update().get(id=object_id)
            if correction.status != OfficePayrollCorrectionStatus.SUBMITTED:
                raise ValidationError("승인 대기 상태의 급여 정정 요청만 처리할 수 있습니다.")
            if correction.requested_by_id == actor.id:
                raise PermissionDenied("요청자는 자신의 급여 정정 요청을 승인하거나 반려할 수 없습니다.")
            if action == "approve":
                correction.status = OfficePayrollCorrectionStatus.APPROVED
                correction.approved_by = actor
                correction.approved_at = timezone.now()
                correction.save(update_fields=["status", "approved_by", "approved_at", "updated_at"])
                log_action(actor=actor, action="OFFICE_PAYROLL_CORRECTION_APPROVE", object_type="OfficePayrollCorrection", object_id=correction.id, after={"status": correction.status})
                return correction
            if action == "reject":
                correction.status = OfficePayrollCorrectionStatus.REJECTED
                correction.rejection_reason = (reason or "").strip()
                correction.save(update_fields=["status", "rejection_reason", "updated_at"])
                log_action(actor=actor, action="OFFICE_PAYROLL_CORRECTION_REJECT", object_type="OfficePayrollCorrection", object_id=correction.id, after={"status": correction.status})
                return correction
    raise ValidationError("요청 형식이 올바르지 않습니다.")


@login_required
def ceo_home(request):
    require_role(request.user, [Role.CEO, Role.HQ])
    ceo_read_only = get_user_role(request.user) != Role.CEO

    as_of_date = _parse_date(request.GET.get("as_of_date")) or timezone.localdate()
    compare_mode = (request.GET.get("compare") or request.GET.get("compare_mode") or "month").lower()
    if compare_mode not in {"month", "week"}:
        compare_mode = "month"
    include_submitted = request.GET.get("include_submitted") == "1"
    baseline_only = request.GET.get("baseline_only") == "1"
    entity_scope, legal_entity_ids, entity_scope_label = _resolve_ceo_entity_scope(request)
    accessible_entity_codes = set(
        get_user_legal_entities(request.user).values_list("code", flat=True)
    )

    period_start, period_end, prev_period_start, prev_period_end = compare_windows(
        as_of_date, compare_mode
    )

    dashboard = get_ceo_dashboard(as_of_date, legal_entity_ids=legal_entity_ids)
    projects = dashboard.get("projects", [])
    project_ids = [p.get("project_id") for p in projects if p.get("project_id")]
    primary_project_id = request.GET.get("project_id") or (project_ids[0] if project_ids else None)

    portfolio_progress = build_portfolio_progress_comparison(
        Project.objects.filter(id__in=project_ids).order_by("id"), as_of_date
    )
    chart_labels = [p["project_name"] for p in portfolio_progress]
    chart_values = [float(p["actual_progress_percent"] or 0) for p in portfolio_progress]
    chart_planned_values = [float(p["planned_progress_percent"]) if p["planned_progress_percent"] is not None else None for p in portfolio_progress]
    chart_project_ids = [p["project_id"] for p in portfolio_progress]

    total_revenue = sum((_safe_decimal(p.get("recognized_revenue")) for p in projects), Decimal("0"))
    total_provisional_revenue = sum(
        (_safe_decimal(p.get("provisional_progress_revenue")) for p in projects), Decimal("0")
    )
    total_cost = sum((_safe_decimal(p.get("accrual_cost")) for p in projects), Decimal("0"))
    total_labor = sum((_safe_decimal(p.get("labor_cost")) for p in projects), Decimal("0"))
    total_profit = total_revenue - total_cost
    total_provisional_profit = total_provisional_revenue - total_cost
    revenue_recognition_status = (
        "인식 완료"
        if projects and all(p.get("revenue_recognition_status") == "인식 완료" for p in projects)
        else "월마감 전"
    )
    avg_progress = (
        sum((_safe_decimal(p.get("overall_progress_percent")) for p in projects), Decimal("0"))
        / Decimal(len(projects))
        if projects
        else Decimal("0")
    )
    margin_percent = _calculate_margin(total_revenue, total_profit)

    cash_summary = _cash_summary(project_ids, period_start, period_end)
    advance_billing_summary = get_advance_billing_summary(project_ids)

    prev_dashboard = get_ceo_dashboard(prev_period_end, legal_entity_ids=legal_entity_ids)
    prev_projects = prev_dashboard.get("projects", [])
    prev_total_revenue = sum(
        (_safe_decimal(p.get("recognized_revenue")) for p in prev_projects), Decimal("0")
    )
    prev_total_cost = sum(
        (_safe_decimal(p.get("accrual_cost")) for p in prev_projects), Decimal("0")
    )
    prev_total_profit = prev_total_revenue - prev_total_cost
    prev_margin_percent = _calculate_margin(prev_total_revenue, prev_total_profit)
    prev_cash_summary = _cash_summary(project_ids, prev_period_start, prev_period_end)

    kpi_trends = {
        "revenue": build_trend(total_revenue, prev_total_revenue),
        "cost": build_trend(total_cost, prev_total_cost),
        "profit": build_trend(total_profit, prev_total_profit),
        "margin": build_trend(margin_percent, prev_margin_percent),
        "cashflow": build_trend(
            _safe_decimal(cash_summary.get("net_planned")),
            _safe_decimal(prev_cash_summary.get("net_planned")),
        ),
    }
    if not projects:
        kpi_trends = {
            "revenue": build_trend(None, None),
            "cost": build_trend(None, None),
            "profit": build_trend(None, None),
            "margin": build_trend(None, None),
            "cashflow": build_trend(None, None),
        }

    project_qs = Project.objects.filter(id__in=project_ids).select_related("contract")
    elapsed_values = []
    for project in project_qs:
        elapsed = project_elapsed_percent(project, as_of_date)
        if elapsed is not None:
            elapsed_values.append(elapsed)
    avg_elapsed_percent = (
        sum(elapsed_values, Decimal("0")) / Decimal(len(elapsed_values))
        if elapsed_values
        else None
    )
    schedule_vs_progress = schedule_status(avg_progress, avg_elapsed_percent)

    # The CEO project dashboard must not surface findings whose project was
    # deleted. RiskFinding.project is nullable (SET_NULL), and this model has
    # no separate global/system scope, so projectless findings are excluded.
    open_project_risks = get_operational_dashboard_risk_queryset().filter(project_id__in=project_ids)
    risk_open_count = open_project_risks.count()
    risk_critical_count = open_project_risks.filter(severity=RiskSeverity.CRITICAL).count()
    risk_high_count = open_project_risks.filter(severity=RiskSeverity.HIGH).count()
    stale_threshold = timezone.now() - timezone.timedelta(hours=48)
    risk_stale_48h_count = open_project_risks.filter(created_at__lte=stale_threshold).count()
    top_reason_row = (
        open_project_risks
        .values("rule__name")
        .annotate(total=Count("id"))
        .order_by("-total", "rule__name")
        .first()
    )
    top_reason = (top_reason_row or {}).get("rule__name") or ""
    sample_project_obj = (
        open_project_risks.filter(severity=RiskSeverity.CRITICAL)
        .select_related("project")
        .order_by("-updated_at")
        .first()
        or open_project_risks
        .select_related("project")
        .order_by("-updated_at")
        .first()
    )
    sample_project = (
        sample_project_obj.project.name
        if sample_project_obj and getattr(sample_project_obj, "project", None)
        else ""
    )
    risk_open = list(
        open_project_risks
        .select_related("project", "rule")
        .order_by("-updated_at")[:5]
    )

    pending_reports = DailyReport.objects.filter(project_id__in=project_ids, status=DailyReportStatus.SUBMITTED).count()
    pending_costs = CostActual.objects.filter(project_id__in=project_ids, status=CostActualStatus.SUBMITTED).count()
    pending_contracts = ContractChange.objects.filter(project_id__in=project_ids, status=ContractChangeStatus.SUBMITTED).count()
    pending_plans = PlanChangeRequest.objects.filter(project_id__in=project_ids, status=PlanChangeStatus.SUBMITTED).count()

    approvals_inbox = [
        item for item in _build_pending_items()
        if getattr(item.get("project"), "id", None) in set(project_ids)
    ]
    if ceo_read_only:
        for item in approvals_inbox:
            item["can_approve"] = False
            item["can_reject"] = False
    approvals_pending_count = len(approvals_inbox)
    pending_approvals = approvals_pending_count

    risk_summary = build_risk_summary(
        open_count=risk_open_count,
        critical_count=risk_critical_count,
        high_count=risk_high_count,
        stale_48h_count=risk_stale_48h_count,
        pending_approvals_count=pending_approvals,
        closing_block_count=0,
        top_reason=top_reason,
        sample_project=sample_project,
    )

    evidence_missing = 0
    for change in ContractChange.objects.filter(project_id__in=project_ids, status=ContractChangeStatus.SUBMITTED):
        ok, _reason = check_evidence_required("CONTRACT_CHANGE", change.id, "SUBMIT")
        if not ok:
            evidence_missing += 1
    for plan in PlanChangeRequest.objects.filter(project_id__in=project_ids, status=PlanChangeStatus.SUBMITTED):
        ok, _reason = check_evidence_required("PLAN_CHANGE_REQUEST", plan.id, "SUBMIT")
        if not ok:
            evidence_missing += 1

    query_bits = [f"as_of_date={as_of_date.isoformat()}"]
    query_bits.append(f"entity_scope={entity_scope}")
    if include_submitted:
        query_bits.append("include_submitted=1")
    if not baseline_only:
        query_bits.append("baseline_only=0")
    csv_query = "&".join(query_bits)

    recent_approvals = [
        item for item in _build_recent_approved_items()
        if item.get("project_id") in set(project_ids)
    ]
    context = {
        "as_of_date": as_of_date,
        "compare_mode": compare_mode,
        "include_submitted": include_submitted,
        "baseline_only": baseline_only,
        "entity_scope": entity_scope,
        "entity_scope_label": entity_scope_label,
        "has_group_entity_scope": {"ASAN", "MISAN"}.issubset(accessible_entity_codes),
        "has_asan_entity_scope": "ASAN" in accessible_entity_codes,
        "has_misan_entity_scope": "MISAN" in accessible_entity_codes,
        "projects": projects,
        "portfolio_progress": portfolio_progress,
        "chart_labels": chart_labels,
        "chart_values": chart_values,
        "chart_planned_values": chart_planned_values,
        "chart_project_ids": chart_project_ids,
        "total_revenue": total_revenue,
        "total_provisional_revenue": total_provisional_revenue,
        "total_cost": total_cost,
        "total_labor": total_labor,
        "total_profit": total_profit,
        "total_provisional_profit": total_provisional_profit,
        "revenue_recognition_status": revenue_recognition_status,
        "margin_percent": margin_percent,
        "avg_progress": avg_progress,
        "cash_summary": cash_summary,
        "advance_billing_summary": advance_billing_summary,
        "kpi_trends": kpi_trends,
        "compare_label": "전주 대비" if compare_mode == "week" else "전월 대비",
        "schedule_vs_progress": schedule_vs_progress,
        "risk_open_count": risk_open_count,
        "risk_critical_count": risk_critical_count,
        "risk_high_count": risk_high_count,
        "risk_stale_48h_count": risk_stale_48h_count,
        "risk_summary": risk_summary,
        "risk_open": risk_open,
        "pending_reports": pending_reports,
        "pending_costs": pending_costs,
        "pending_contracts": pending_contracts,
        "pending_plans": pending_plans,
        "pending_approvals": pending_approvals,
        "approvals_inbox": approvals_inbox[:5],
        "approvals_pending_count": approvals_pending_count,
        "approvals_inbox_has_more": approvals_pending_count > 5,
        "recent_approvals": recent_approvals,
        "recent_approvals_total": len(recent_approvals),
        "evidence_missing": evidence_missing,
        "csv_url": f"/api/ceo/reports/project-summary.csv?{csv_query}",
        "role": get_user_role(request.user),
        "ceo_read_only": ceo_read_only,
        "metric_urls": {key: f"/app/ceo/dashboard/metrics/{key}/?" + urlencode({"as_of_date": as_of_date.isoformat(), "compare": compare_mode, "entity_scope": entity_scope}) for key in ("revenue", "provisional_revenue", "cost", "labor", "profit", "provisional_profit", "revenue_status", "advance_balance", "receivable", "progress", "cash")},
        "chart_labels": chart_labels,
        "chart_values": chart_values,
        "primary_project_id": primary_project_id,
    }
    return render(request, "ceo/app_home.html", context)


@login_required
def ceo_metric_detail(request, metric):
    require_role(request.user, [Role.CEO, Role.HQ])
    labels = {"revenue":"실제 누적 매출(VAT 별도)", "provisional_revenue":"잠정 진행률 매출(VAT 별도)", "cost":"누적 원가(VAT 별도)", "labor":"승인 인건비", "profit":"실제 손익(VAT 별도)", "provisional_profit":"잠정 손익(VAT 별도)", "revenue_status":"매출 인식 상태", "advance_balance":"선급금 잔액(VAT 포함)", "receivable":"기성 미수금(VAT 포함)", "progress":"평균 진행률", "cash":"예정 현금흐름(VAT 포함)"}
    if metric not in labels:
        raise PermissionDenied("지원하지 않는 상세 지표입니다.")
    as_of_date = _parse_date(request.GET.get("as_of_date")) or timezone.localdate()
    compare_mode = request.GET.get("compare") or "month"
    entity_scope, legal_entity_ids, entity_scope_label = _resolve_ceo_entity_scope(request)
    period_start, period_end, _previous_start, _previous_end = compare_windows(as_of_date, compare_mode)
    projects = get_ceo_dashboard(as_of_date, legal_entity_ids=legal_entity_ids).get("projects", [])
    ledger = _build_metric_ledger(metric, projects, as_of_date, period_start, period_end)
    return render(request, "ceo/metric_detail.html", {
        "metric_label": labels[metric], "metric": metric, "as_of_date": as_of_date,
        "compare_mode": compare_mode, "entity_scope": entity_scope,
        "entity_scope_label": entity_scope_label, **ledger,
    })


def _ledger_row(*, event_date, project_name, source, description, amount, status="확정"):
    return {"event_date": event_date, "project_name": project_name, "source": source,
            "description": description or "-", "amount": Decimal(amount or 0), "status": status}


def _labor_ledger_rows(project_ids, as_of_date):
    from django.db.models import Q

    rows = []
    lines = TimesheetLine.objects.filter(
        timesheet__project_id__in=project_ids, timesheet__status=TimesheetStatus.APPROVED,
        timesheet__work_date__lte=as_of_date,
    ).select_related("timesheet__project", "timesheet", "worker", "labor_role").order_by("timesheet__work_date", "id")
    for line in lines:
        worker_name = getattr(line.worker, "name", "") or line.labor_role.name
        rows.append(_ledger_row(event_date=line.timesheet.work_date, project_name=line.timesheet.project.name,
            source="출역부 인건비", description=f"{line.timesheet.sheet_no} · {worker_name}", amount=line.amount))
    payroll_lines = PayrollAllocationLine.objects.filter(
        project_id__in=project_ids,
        batch__status__in=[PayrollAllocationStatus.SUBMITTED, PayrollAllocationStatus.APPROVED],
    ).filter(
        Q(batch__period_year__lt=as_of_date.year)
        | Q(batch__period_year=as_of_date.year, batch__period_month__lte=as_of_date.month)
    ).select_related("project", "batch", "cbs").order_by("batch__period_year", "batch__period_month", "id")
    for line in payroll_lines:
        rows.append(_ledger_row(event_date=date(line.batch.period_year, line.batch.period_month, 1), project_name=line.project.name,
            source="급여 배부", description=f"{line.batch.batch_no} · {getattr(line.cbs, 'name', '') or line.memo}", amount=line.amount,
            status="승인" if line.batch.status == PayrollAllocationStatus.APPROVED else "제출"))
    return rows


def _cost_ledger_rows(project_ids, as_of_date):
    rows = []
    lines = CostActualLine.objects.filter(
        cost_actual__project_id__in=project_ids,
        cost_actual__status__in=[CostActualStatus.APPROVED, CostActualStatus.CLOSED],
        cost_actual__report_date__lte=as_of_date,
    ).select_related("cost_actual__project", "cost_item").order_by("cost_actual__report_date", "id")
    for line in lines:
        rows.append(_ledger_row(event_date=line.cost_actual.report_date, project_name=line.cost_actual.project.name,
            source="원가 실적", description=line.description or line.cost_item.name, amount=line.accounting_cost_amount,
            status="승인" if line.cost_actual.status == CostActualStatus.APPROVED else "마감"))
    return rows + _labor_ledger_rows(project_ids, as_of_date)


def _build_metric_ledger(metric, projects, as_of_date, period_start, period_end):
    project_ids = [project["project_id"] for project in projects]
    rows, note = [], "집계에 반영된 발생 내역입니다."
    if metric in {"cost", "labor"}:
        rows = _cost_ledger_rows(project_ids, as_of_date) if metric == "cost" else _labor_ledger_rows(project_ids, as_of_date)
        if metric == "cost":
            note = "공제 가능한 매입세액은 제외하고, 노무비는 VAT 변환 없이 전액 반영합니다."
    elif metric == "revenue":
        seen = set()
        recognitions = RevenueRecognition.objects.filter(project_id__in=project_ids, as_of_date__lte=as_of_date).select_related("project").order_by("project_id", "-as_of_date", "-id")
        for record in recognitions:
            if record.project_id not in seen:
                seen.add(record.project_id)
                rows.append(_ledger_row(event_date=record.as_of_date, project_name=record.project.name, source="매출 인식", description=f"승인 진행률 {record.progress_percent}%", amount=record.recognized_revenue))
        note = "프로젝트별 기준일 현재의 최신 매출 인식 스냅샷입니다."
    elif metric == "provisional_revenue":
        rows = [_ledger_row(event_date=as_of_date, project_name=p["project_name"], source="잠정 진행률 매출", description=f"승인 진행률 {p['overall_progress_percent']}% 기준", amount=p["provisional_progress_revenue"], status="잠정") for p in projects]
        note = "승인 진행률과 계약금액으로 계산한 잠정 매출입니다."
    elif metric in {"profit", "provisional_profit"}:
        source_metric = "revenue" if metric == "profit" else "provisional_revenue"
        rows.extend(_build_metric_ledger(source_metric, projects, as_of_date, period_start, period_end)["rows"])
        for row in _cost_ledger_rows(project_ids, as_of_date):
            row["source"] = f"{row['source']} (손익 차감)"
            row["amount"] = -row["amount"]
            rows.append(row)
        note = "매출은 더하고, 승인된 원가·인건비는 차감하여 손익을 계산합니다."
    elif metric == "cash":
        events = CashEvent.objects.filter(project_id__in=project_ids, status=CashEventStatus.PLANNED, event_date__range=(period_start, period_end)).select_related("project").order_by("event_date", "id")
        for event in events:
            amount = event.amount if event.event_type == CashEventType.IN else -event.amount
            source = "예정 현금 유입" if event.event_type == CashEventType.IN else "예정 현금 유출"
            rows.append(_ledger_row(event_date=event.event_date, project_name=event.project.name, source=source, description=event.description, amount=amount, status="예정"))
        note = f"{period_start:%Y-%m-%d}~{period_end:%Y-%m-%d} 예정 현금흐름입니다. 유출은 음수로 표시됩니다."
    elif metric == "revenue_status":
        closes = RevenueRecognitionClose.objects.filter(project_id__in=project_ids, recognition_date__lte=as_of_date).select_related("project").order_by("-recognition_date", "-id")
        for close in closes:
            rows.append(_ledger_row(event_date=close.recognition_date, project_name=close.project.name, source="매출 인식 마감", description=f"{close.period_year}년 {close.period_month}월 · {close.trigger_type}", amount=close.recognized_revenue_amount, status=close.status))
        note = "매출 인식 마감 스냅샷 목록입니다."
    elif metric == "advance_balance":
        for advance in AdvancePayment.objects.filter(project_id__in=project_ids).select_related("project").order_by("received_date", "id"):
            rows.append(_ledger_row(event_date=advance.received_date, project_name=advance.project.name, source="선급금", description=f"수령 {advance.received_amount:,.0f}원 · 회수 후 잔액", amount=get_advance_billing_summary([advance.project_id])["advance_balance"], status="잔액"))
        note = "선급금 수령액에서 기성청구 선급금 공제 누계를 차감한 잔액입니다."
    elif metric == "receivable":
        billings = ProgressBilling.objects.filter(project_id__in=project_ids, status=ProgressBillingStatus.ISSUED).select_related("project").order_by("billing_date", "id")
        for billing in billings:
            rows.append(_ledger_row(event_date=billing.billing_date, project_name=billing.project.name, source="기성 미수금", description=f"기성청구 · 선급금 공제 {billing.advance_deduction_amount:,.0f}원", amount=billing.net_claim_amount, status="미수"))
        note = "수금 처리되지 않은 기성청구의 순청구 금액입니다."
    elif metric == "progress":
        task_rows = ScheduleTask.objects.filter(
            plan__project_id__in=project_ids, plan__is_active=True, is_active=True,
        ).select_related("plan__project").order_by("plan__project_id", "sort_order", "id")
        task_ids = [task.id for task in task_rows]
        latest_by_task = {}
        progress_rows = DailyProgress.objects.filter(
            project_id__in=project_ids, task_id__in=task_ids, status="approved",
            report_date__lte=as_of_date,
        ).select_related("task").order_by("project_id", "task_id", "-report_date", "-id")
        for progress in progress_rows:
            latest_by_task.setdefault((progress.project_id, progress.task_id), progress)
        for task in task_rows:
            progress = latest_by_task.get((task.plan.project_id, task.id))
            approved_percent = progress.progress_percent if progress else Decimal("0")
            contribution = (task.weight_percent or Decimal("0")) * approved_percent / Decimal("100")
            report_date = progress.report_date if progress else None
            description = (
                f"가중치 {task.weight_percent:.3f}% × 승인 진행률 {approved_percent:.3f}% "
                f"= 기여도 {contribution:.3f}%"
            )
            rows.append(_ledger_row(event_date=report_date, project_name=task.plan.project.name,
                source=f"{task.name}", description=description, amount=contribution,
                status="승인" if progress else "미입력"))
        note = "활성 WBS별 가중치와 기준일 현재 최신 승인 진행률의 곱으로 계산한 기여도입니다."
    total = sum((row["amount"] for row in rows), Decimal("0"))
    if metric == "progress":
        total = total / Decimal(len(projects)) if projects else Decimal("0")
    return {"rows": rows, "ledger_note": note, "ledger_total": total, "ledger_total_label": "평균" if metric == "progress" else "합계", "is_percent": metric == "progress", "is_status": metric == "revenue_status"}


@login_required
def ceo_project_metric_detail(request, project_id, metric):
    """Show a distinct, metric-specific detail page for one project."""
    require_role(request.user, [Role.CEO, Role.HQ])
    labels = {"revenue":"실제 누적 매출(VAT 별도)", "provisional_revenue":"잠정 진행률 매출(VAT 별도)", "cost":"누적 원가(VAT 별도)", "labor":"승인 인건비", "profit":"실제 손익(VAT 별도)", "provisional_profit":"잠정 손익(VAT 별도)", "revenue_status":"매출 인식 상태", "advance_balance":"선급금 잔액(VAT 포함)", "receivable":"기성 미수금(VAT 포함)", "progress":"평균 진행률", "cash":"예정 현금흐름(VAT 포함)"}
    if metric not in labels:
        raise PermissionDenied("지원하지 않는 상세 지표입니다.")
    project = get_object_or_404(Project, id=project_id)
    as_of_date = _parse_date(request.GET.get("as_of_date")) or timezone.localdate()
    compare_mode = request.GET.get("compare") or "month"
    period_start, period_end, _previous_start, _previous_end = compare_windows(as_of_date, compare_mode)
    dashboard_project = next(
        (item for item in get_ceo_dashboard(as_of_date).get("projects", []) if item["project_id"] == project.id),
        None,
    )
    if dashboard_project is None:
        raise PermissionDenied("대시보드에서 조회할 수 없는 프로젝트입니다.")
    ledger = _build_metric_ledger(metric, [dashboard_project], as_of_date, period_start, period_end)
    return render(request, "ceo/metric_detail.html", {
        "metric_label": labels[metric], "metric": metric, "as_of_date": as_of_date,
        "selected_project": project, "compare_mode": compare_mode, **ledger,
    })


@login_required
def ceo_approval_quick_approve(request):
    require_role(request.user, [Role.CEO])
    if request.method != "POST":
        raise PermissionDenied("POST 요청만 허용합니다.")

    object_type = (request.POST.get("object_type") or "").upper().strip()
    object_id_raw = request.POST.get("object_id")
    try:
        object_id = int(object_id_raw)
    except (TypeError, ValueError):
        messages.error(request, "요청 형식이 올바르지 않습니다.")
        return redirect(_ceo_next_url(request))

    pending_item = _find_pending_item(object_type, object_id)
    if pending_item is None:
        messages.error(request, "승인 대기 목록에서 항목을 찾을 수 없습니다.")
        return redirect(_ceo_next_url(request))

    if not pending_item.get("can_approve", False):
        messages.error(
            request,
            pending_item.get("block_message") or "현재 상태에서는 처리할 수 없습니다.",
        )
        return redirect(_ceo_next_url(request))

    try:
        _run_ceo_quick_action(
            object_type=object_type,
            object_id=object_id,
            action="approve",
            actor=request.user,
            request=request,
        )
    except (ValidationError, PermissionDenied, ValueError) as exc:
        messages.error(request, str(exc))
    except Exception:
        messages.error(request, "승인 처리 중 오류가 발생했습니다.")
    else:
        messages.success(request, "승인 처리했습니다.")
    return redirect(_ceo_next_url(request))


@login_required
def ceo_approval_quick_reject(request):
    require_role(request.user, [Role.CEO])
    if request.method != "POST":
        raise PermissionDenied("POST 요청만 허용합니다.")

    object_type = (request.POST.get("object_type") or "").upper().strip()
    object_id_raw = request.POST.get("object_id")
    reason = (request.POST.get("reason") or "").strip()
    try:
        object_id = int(object_id_raw)
    except (TypeError, ValueError):
        messages.error(request, "요청 형식이 올바르지 않습니다.")
        return redirect(_ceo_next_url(request))

    pending_item = _find_pending_item(object_type, object_id)
    if pending_item is None:
        messages.error(request, "승인 대기 목록에서 항목을 찾을 수 없습니다.")
        return redirect(_ceo_next_url(request))

    if not pending_item.get("can_reject", False):
        messages.error(
            request,
            pending_item.get("block_message") or "현재 상태에서는 처리할 수 없습니다.",
        )
        return redirect(_ceo_next_url(request))

    if not reason:
        messages.error(request, "반려 사유를 입력해 주세요.")
        return redirect(_ceo_next_url(request))

    try:
        _run_ceo_quick_action(
            object_type=object_type,
            object_id=object_id,
            action="reject",
            actor=request.user,
            request=request,
            reason=reason,
        )
    except (ValidationError, PermissionDenied, ValueError) as exc:
        messages.error(request, str(exc))
    except Exception:
        messages.error(request, "반려 처리 중 오류가 발생했습니다.")
    else:
        messages.success(request, "반려 처리했습니다.")
    return redirect(_ceo_next_url(request))


@login_required
def ceo_projects_list(request):
    require_role(request.user, [Role.CEO, Role.HQ])
    as_of_date = _parse_date(request.GET.get("as_of_date"))
    entity_scope, legal_entity_ids, entity_scope_label = _resolve_ceo_entity_scope(request)
    projects = get_ceo_projects_list(
        {"as_of_date": as_of_date, "legal_entity_ids": legal_entity_ids}
    )
    context = {
        "projects": projects,
        "as_of_date": as_of_date,
        "entity_scope": entity_scope,
        "entity_scope_label": entity_scope_label,
        "role": get_user_role(request.user),
    }
    return render(request, "ceo/app_projects.html", context)


@login_required
def ceo_project_kpi_detail(request, project_id):
    require_role(request.user, [Role.CEO, Role.HQ])
    project = get_object_or_404(Project, id=project_id)
    _entity_scope, legal_entity_ids, _entity_scope_label = _resolve_ceo_entity_scope(request)
    if project.legal_entity_id not in legal_entity_ids:
        raise PermissionDenied("선택한 운영 법인 범위에 포함되지 않은 프로젝트입니다.")
    as_of_date = _parse_date(request.GET.get("as_of_date"))
    if as_of_date is None:
        as_of_date = timezone.localdate()
    include_submitted = request.GET.get("include_submitted") == "1"

    kpi = compute_project_kpi(
        project, as_of_date=as_of_date, include_submitted=include_submitted
    )

    budget_by_category = (kpi.get("baseline") or {}).get("budget_by_category", {})
    actual_by_category = (kpi.get("actual") or {}).get("actual_cost_by_category", {})
    categories = sorted(set(budget_by_category.keys()) | set(actual_by_category.keys()))
    category_rows = []
    chart_category_labels = []
    chart_category_budget = []
    chart_category_actual = []
    for category in categories:
        budget = budget_by_category.get(category) or Decimal("0")
        actual = actual_by_category.get(category) or Decimal("0")
        diff = budget - actual
        category_rows.append(
            {
                "category": category,
                "budget": budget,
                "actual": actual,
                "diff": diff,
            }
        )
        chart_category_labels.append(category)
        chart_category_budget.append(float(budget))
        chart_category_actual.append(float(actual))

    planned_progress = (kpi.get("baseline") or {}).get("planned_progress_percent") or Decimal(
        "0"
    )
    actual_progress = (kpi.get("actual") or {}).get("actual_progress_percent") or Decimal(
        "0"
    )
    chart_progress_labels = ["怨꾪쉷", "?ㅼ젣"]
    chart_progress_values = [float(planned_progress), float(actual_progress)]

    wbs_rows = []
    wbs_model = apps.get_model("projects", "WBSItem")
    if wbs_model:
        for item in wbs_model.objects.filter(project=project).order_by("sort_order", "id"):
            wbs_rows.append(
                {
                    "name": item.name,
                    "weight": item.weight or Decimal("0"),
                    "plan_start": item.plan_start_date,
                    "plan_end": item.plan_end_date,
                    "actual_progress": None,
                }
            )

    cost_ids = list(CostActual.objects.filter(project=project).values_list("id", flat=True))
    progress_ids = list(
        DailyProgress.objects.filter(project=project).values_list("id", flat=True)
    )
    report_ids = list(FieldReport.objects.filter(project=project).values_list("id", flat=True))
    pending_breakdown = {
        "cost": ApprovalRequest.objects.filter(
            status=ApprovalStatus.SUBMITTED,
            object_type="COST_ACTUAL",
            object_id__in=cost_ids,
        ).count()
        if cost_ids
        else 0,
        "progress": ApprovalRequest.objects.filter(
            status=ApprovalStatus.SUBMITTED,
            object_type="DAILY_PROGRESS",
            object_id__in=progress_ids,
        ).count()
        if progress_ids
        else 0,
        "report": ApprovalRequest.objects.filter(
            status=ApprovalStatus.SUBMITTED,
            object_type="FIELD_REPORT",
            object_id__in=report_ids,
        ).count()
        if report_ids
        else 0,
    }

    context = {
        "project": project,
        "as_of_date": as_of_date,
        "include_submitted": include_submitted,
        "kpi": kpi,
        "category_rows": category_rows,
        "wbs_rows": wbs_rows,
        "pending_breakdown": pending_breakdown,
        "chart_category_labels": chart_category_labels,
        "chart_category_budget": chart_category_budget,
        "chart_category_actual": chart_category_actual,
        "chart_progress_labels": chart_progress_labels,
        "chart_progress_values": chart_progress_values,
    }
    return render(request, "ceo/kpi_detail.html", context)


def _get_wbs_baseline_items(project, base_version):
    qs = WBSItem.objects.filter(project=project, baseline_version=base_version).order_by(
        "sort_order", "id"
    )
    if qs.exists():
        return list(qs)
    return list(
        WBSItem.objects.filter(project=project, is_baseline=True).order_by(
            "sort_order", "id"
        )
    )


def _get_max_baseline_version(project):
    return (
        WBSItem.objects.filter(project=project)
        .order_by("-baseline_version")
        .values_list("baseline_version", flat=True)
        .first()
        or 1
    )


def _sum_request_weights(lines):
    total = Decimal("0")
    for line in lines:
        total += Decimal(str(line.weight or 0))
    return total


@login_required
def ceo_wbs_change_list(request):
    require_role(request.user, [Role.CEO, Role.HQ])
    status_filter = (request.GET.get("status") or "submitted").lower()
    qs = WBSChangeRequest.objects.select_related("project", "requested_by").order_by(
        "-created_at"
    )
    if status_filter == "submitted":
        qs = qs.filter(status=WBSChangeRequestStatus.SUBMITTED)
    elif status_filter == "approved":
        qs = qs.filter(status=WBSChangeRequestStatus.APPROVED)
    elif status_filter == "rejected":
        qs = qs.filter(status=WBSChangeRequestStatus.REJECTED)

    context = {
        "requests": qs,
        "status_filter": status_filter,
        "ceo_read_only": get_user_role(request.user) != Role.CEO,
    }
    return render(request, "ceo/wbs_change_list.html", context)


@login_required
def ceo_wbs_change_detail(request, request_id):
    require_role(request.user, [Role.CEO, Role.HQ])
    change_request = get_object_or_404(WBSChangeRequest, id=request_id)
    project = change_request.project
    base_version = change_request.base_version
    baseline_items = _get_wbs_baseline_items(project, base_version)
    request_lines = list(
        change_request.lines.order_by("order", "id").all()
    )
    weight_sum = _sum_request_weights(request_lines)
    weight_valid = abs(weight_sum - Decimal("100")) <= Decimal("0.1")
    context = {
        "change_request": change_request,
        "project": project,
        "baseline_items": baseline_items,
        "request_lines": request_lines,
        "weight_sum": weight_sum,
        "weight_valid": weight_valid,
        "ceo_read_only": get_user_role(request.user) != Role.CEO,
    }
    return render(request, "ceo/wbs_change_detail.html", context)


@login_required
def ceo_wbs_change_approve(request, request_id):
    require_role(request.user, [Role.CEO])
    change_request = get_object_or_404(WBSChangeRequest, id=request_id)
    if change_request.status != WBSChangeRequestStatus.SUBMITTED:
        return render(
            request,
            "ceo/wbs_change_detail.html",
            {
                "change_request": change_request,
                "project": change_request.project,
                "baseline_items": _get_wbs_baseline_items(
                    change_request.project, change_request.base_version
                ),
                "request_lines": list(change_request.lines.order_by("order", "id")),
                "weight_sum": _sum_request_weights(change_request.lines.all()),
                "weight_valid": False,
                "error": "현재 상태에서는 승인할 수 없습니다.",
            },
        )
    if (
        change_request.request_type == WBSChangeRequestType.DESIGN_CONTRACT_CHANGE
        and change_request.change_order
        and change_request.change_order.status != ContractChangeStatus.APPROVED
    ):
        return render(
            request,
            "ceo/wbs_change_detail.html",
            {
                "change_request": change_request,
                "project": change_request.project,
                "baseline_items": _get_wbs_baseline_items(
                    change_request.project, change_request.base_version
                ),
                "request_lines": list(change_request.lines.order_by("order", "id")),
                "weight_sum": _sum_request_weights(change_request.lines.all()),
                "weight_valid": False,
                "error": "설계/계약 변경 요청은 승인된 CHANGE ORDER가 있어야 승인할 수 있습니다.",
            },
        )

    request_lines = list(change_request.lines.order_by("order", "id"))
    weight_sum = _sum_request_weights(request_lines)
    date_error = False
    for line in request_lines:
        if line.planned_start and line.planned_end and line.planned_start > line.planned_end:
            date_error = True
            break

    if abs(weight_sum - Decimal("100")) > Decimal("0.1") or not request_lines or date_error:
        return render(
            request,
            "ceo/wbs_change_detail.html",
            {
                "change_request": change_request,
                "project": change_request.project,
                "baseline_items": _get_wbs_baseline_items(
                    change_request.project, change_request.base_version
                ),
                "request_lines": request_lines,
                "weight_sum": weight_sum,
                "weight_valid": False,
                "error": "제출 라인/일정/가중치 조건이 유효하지 않습니다. (가중치 합계 100% 필요)",
            },
        )

    with transaction.atomic():
        project = Project.objects.select_for_update().get(id=change_request.project_id)
        max_version = _get_max_baseline_version(project)
        new_version = max_version + 1

        WBSItem.objects.bulk_create(
            [
                WBSItem(
                    project=project,
                    name=line.task_name,
                    weight=line.weight,
                    plan_start_date=line.planned_start,
                    plan_end_date=line.planned_end,
                    sort_order=idx,
                    baseline_version=new_version,
                    is_baseline=True,
                )
                for idx, line in enumerate(request_lines, start=1)
            ]
        )

        change_request.proposed_version = new_version
        change_request.status = WBSChangeRequestStatus.APPROVED
        change_request.approved_by = request.user
        change_request.approved_at = timezone.now()
        change_request.save(
            update_fields=[
                "proposed_version",
                "status",
                "approved_by",
                "approved_at",
                "updated_at",
            ]
        )

    log_action(
        actor=request.user,
        action="WBS_CHANGE_REQUEST_APPROVE",
        object_type="WBSChangeRequest",
        object_id=change_request.id,
        project=project,
        request=request,
        after={
            "base_version": change_request.base_version,
            "new_version": change_request.proposed_version,
            "lines_count": len(request_lines),
        },
    )
    return redirect("/app/ceo/wbs-change/requests/")


@login_required
def ceo_wbs_change_reject(request, request_id):
    require_role(request.user, [Role.CEO])
    change_request = get_object_or_404(WBSChangeRequest, id=request_id)
    if change_request.status != WBSChangeRequestStatus.SUBMITTED:
        return redirect(f"/app/ceo/wbs-change/requests/{change_request.id}/")
    decision_note = (request.POST.get("decision_note") or "").strip()
    if not decision_note:
        return render(
            request,
            "ceo/wbs_change_detail.html",
            {
                "change_request": change_request,
                "project": change_request.project,
                "baseline_items": _get_wbs_baseline_items(
                    change_request.project, change_request.base_version
                ),
                "request_lines": list(change_request.lines.order_by("order", "id")),
                "weight_sum": _sum_request_weights(change_request.lines.all()),
                "weight_valid": True,
                "error": "반려 사유를 입력해 주세요.",
            },
        )
    change_request.status = WBSChangeRequestStatus.REJECTED
    change_request.approved_by = request.user
    change_request.approved_at = timezone.now()
    change_request.decision_note = decision_note
    change_request.save(
        update_fields=["status", "approved_by", "approved_at", "decision_note", "updated_at"]
    )
    log_action(
        actor=request.user,
        action="WBS_CHANGE_REQUEST_REJECT",
        object_type="WBSChangeRequest",
        object_id=change_request.id,
        project=change_request.project,
        request=request,
        after={
            "base_version": change_request.base_version,
            "decision_note": decision_note,
        },
    )
    return redirect("/app/ceo/wbs-change/requests/")



