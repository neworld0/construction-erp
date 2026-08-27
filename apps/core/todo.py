from __future__ import annotations

from dataclasses import dataclass
from datetime import date

from django.db.models import Count, Q
from django.utils import timezone

from apps.closing.models import ClosingApprovalPolicy, ClosingPeriod, ClosingStatus
from apps.core.models import ApprovalRequest, ApprovalStatus
from apps.cost.models import CostActual, CostActualStatus
from apps.field.models import (
    DailyReport,
    DailyReportStatus,
    RetroactiveEntryRequest,
    RetroactiveEntryRequestStatus,
    RetroactiveEntryRequestType,
)
from apps.labor.models import Timesheet, TimesheetStatus
from apps.finance.models import ExpenseExecution, ExpenseExecutionStatus
from apps.risk.dashboard_visibility import get_operational_dashboard_risk_queryset
from apps.schedule.models import DailyProgress, PlanChangeRequest, ProgressCorrectionRequest, ProgressCorrectionStatus

ICON_RED = "\U0001F534"
ICON_ORANGE = "\U0001F7E0"
ICON_GREEN = "\U0001F7E2"


@dataclass
class TodoItem:
    icon: str
    text: str
    count: int
    url: str


def build_hq_todos(risk_counts: dict, *, legal_entity=None) -> dict:
    today = timezone.localdate()

    approval_total = _approval_pending_count(legal_entity=legal_entity)
    risk_critical = risk_counts.get("critical", 0)
    risk_high = risk_counts.get("high", 0)
    closing_due = _closing_due_count(today, legal_entity=legal_entity)
    missing_today = _missing_today_count(today, legal_entity=legal_entity)
    # Generic approval timestamps have no direct project FK. Until each
    # approval target is resolved with its submitted timestamp, omit this
    # secondary badge in a legal-entity view rather than overstate a delay.
    delayed_48h = _approval_delayed_48h_count() if legal_entity is None else None
    retro_progress_pending = _retroactive_progress_pending_count(legal_entity=legal_entity)
    timesheet_approval_pending = _timesheet_approval_pending_count(legal_entity=legal_entity)
    expense_execution_pending = _expense_execution_pending_count(legal_entity=legal_entity)
    progress_correction_pending = _progress_correction_pending_count(legal_entity=legal_entity)
    hq_dual_closing_pending = _hq_dual_closing_pending_count(legal_entity=legal_entity)

    todos = [
        TodoItem(
            icon=_status_icon(approval_total, warn_threshold=1, critical_threshold=5),
            text="\uc2b9\uc778 \ub300\uae30 \ucc98\ub9ac",
            count=approval_total,
            url="/app/hq/inbox/",
        )
    ]

    # Retroactive progress entry is not an ApprovalRequest. Keep it as a
    # first-class HQ operation so it cannot be missed in the generic inbox.
    todos.append(
        TodoItem(
            icon=_status_icon(retro_progress_pending, warn_threshold=1, critical_threshold=5),
            text="진행률 소급 입력 요청",
            count=retro_progress_pending,
            url="/app/hq/progress/retro-requests/?status=PENDING",
        )
    )

    # Timesheets use their own HQ approval workflow rather than the generic
    # ApprovalRequest inbox.  Surface them here so FIELD submissions are not
    # invisible until an HQ user happens to open the labor module.
    todos.append(
        TodoItem(
            icon=_status_icon(timesheet_approval_pending, warn_threshold=1, critical_threshold=5),
            text="출역부 승인 대기",
            count=timesheet_approval_pending,
            url="/app/hq/labor/timesheets/?status=SUBMITTED",
        )
    )

    todos.append(
        TodoItem(
            icon=_status_icon(expense_execution_pending, warn_threshold=1, critical_threshold=5),
            text="비용 집행 대상",
            count=expense_execution_pending,
            url="/app/hq/finance/expense-executions/?status=open",
        )
    )

    todos.append(
        TodoItem(
            icon=_status_icon(progress_correction_pending, warn_threshold=1, critical_threshold=5),
            text="진행률 정정·취소 요청",
            count=progress_correction_pending,
            url="/app/hq/progress/corrections/?status=HQ_REVIEW",
        )
    )

    # HQ 2단계 마감은 CEO 결재함으로 보내지지 않는다. 별도 허브 알림으로
    # 노출해 2차 확정자가 목록 화면을 열어 보지 않아도 처리할 수 있게 한다.
    todos.append(
        TodoItem(
            icon=_status_icon(hq_dual_closing_pending, warn_threshold=1, critical_threshold=3),
            text="HQ 2차 월마감 검토",
            count=hq_dual_closing_pending,
            url="/app/hq/closing/?status=OPEN",
        )
    )

    risk_count = risk_critical + risk_high
    risk_icon = ICON_GREEN
    if risk_critical > 0:
        risk_icon = ICON_RED
    elif risk_high > 0:
        risk_icon = ICON_ORANGE
    todos.append(
        TodoItem(
            icon=risk_icon,
            text="CRITICAL/HIGH \ub9ac\uc2a4\ud06c \ud655\uc778",
            count=risk_count,
            url="/app/hq/risks/",
        )
    )

    todos.append(
        TodoItem(
            icon=ICON_RED if closing_due > 0 else ICON_GREEN,
            text="\ub9c8\uac10 \uc0c1\ud0dc \uc810\uac80",
            count=closing_due,
            url="/app/hq/closing/",
        )
    )

    todos.append(
        TodoItem(
            icon=ICON_ORANGE if missing_today > 0 else ICON_GREEN,
            text="\uc624\ub298 \ub204\ub77d \uc810\uac80",
            count=missing_today,
            url="/app/hq/missing/",
        )
    )

    if delayed_48h is not None:
        todos.append(
            TodoItem(
                icon=ICON_RED if delayed_48h > 0 else ICON_GREEN,
                text="48\uc2dc\uac04+ \uc2b9\uc778 \uc9c0\uc5f0",
                count=delayed_48h,
                url="/app/hq/inbox/",
            )
        )

    # Risk visibility is a standing HQ control, not an optional green item.
    # Keep it in the compact hub even when other queues are empty/green.
    risk_todo = next(
        (item for item in todos if item.text == "CRITICAL/HIGH 리스크 확인"),
        None,
    )
    remaining_todos = [item for item in todos[1:] if item is not risk_todo]
    todos_sorted = [todos[0]]
    if risk_todo is not None:
        todos_sorted.append(risk_todo)
    todos_sorted += sorted(remaining_todos, key=lambda item: _icon_rank(item.icon))
    todos_sorted = todos_sorted[:6]

    all_clear = all(item.count == 0 for item in todos_sorted)
    return {
        "items": todos_sorted,
        "all_clear": all_clear,
    }


def _status_icon(count: int, warn_threshold: int, critical_threshold: int) -> str:
    if count >= critical_threshold:
        return ICON_RED
    if count >= warn_threshold:
        return ICON_ORANGE
    return ICON_GREEN


def _icon_rank(icon: str) -> int:
    if icon == ICON_RED:
        return 0
    if icon == ICON_ORANGE:
        return 1
    return 2


def _approval_pending_count(*, legal_entity=None) -> int:
    approvals = list(
        ApprovalRequest.objects.filter(status=ApprovalStatus.SUBMITTED).only(
            "id", "object_type", "object_id"
        )
    )
    approval_by_id = {approval.id: approval for approval in approvals}

    def _normalize_object_type(object_type: str) -> str:
        normalized = (object_type or "").upper().strip()
        aliases = {
            "COST": "COST_ACTUAL",
            "COSTACTUAL": "COST_ACTUAL",
            "DAILYPROGRESS": "DAILY_PROGRESS",
            "FIELDREPORT": "FIELD_REPORT",
            "DAILYREPORT": "DAILY_REPORT",
        }
        return aliases.get(normalized, normalized)

    def _resolved_key(approval_obj):
        object_type = _normalize_object_type(getattr(approval_obj, "object_type", ""))
        object_id = getattr(approval_obj, "object_id", None)
        visited = set()
        while object_type == "APPROVAL_REQUEST" and object_id and object_id not in visited:
            visited.add(object_id)
            nested = approval_by_id.get(object_id)
            if nested is None:
                nested = ApprovalRequest.objects.filter(id=object_id).only(
                    "id", "object_type", "object_id"
                ).first()
                if nested is not None:
                    approval_by_id[nested.id] = nested
            if nested is None:
                break
            object_type = _normalize_object_type(nested.object_type)
            object_id = nested.object_id
        return object_type, object_id

    unique_keys = set()
    for approval in approvals:
        key = _resolved_key(approval)
        if key[0] and key[1]:
            unique_keys.add(key)
    if legal_entity is None:
        return len(unique_keys)

    # ApprovalRequest is a generic pointer.  Resolve only project-backed and
    # entity-backed targets; unknown/global rows must never leak into a legal
    # entity HQ queue.
    from apps.contracts.models import ContractChange
    from apps.field.models import DailyReport
    from apps.projects.models import ApprovalPackage, WBSChangeRequest
    from apps.reports.models import FieldReport

    project_models = {
        "COST_ACTUAL": CostActual,
        "DAILY_REPORT": DailyReport,
        "DAILY_PROGRESS": DailyProgress,
        "FIELD_REPORT": FieldReport,
        "CONTRACT_CHANGE": ContractChange,
        "PLAN_CHANGE_REQUEST": PlanChangeRequest,
        "WBS_CHANGE_REQUEST": WBSChangeRequest,
        "APPROVAL_PACKAGE": ApprovalPackage,
        "TIMESHEET": Timesheet,
        "PROGRESS_CORRECTION": ProgressCorrectionRequest,
    }
    scoped_count = 0
    for object_type, object_id in unique_keys:
        model = project_models.get(object_type)
        if model and model.objects.filter(id=object_id, project__legal_entity=legal_entity).exists():
            scoped_count += 1
        elif object_type == "CLOSING_PERIOD" and ClosingPeriod.objects.filter(
            id=object_id, legal_entity=legal_entity
        ).exists():
            scoped_count += 1
    return scoped_count


def _approval_delayed_48h_count() -> int:
    cutoff = timezone.now() - timezone.timedelta(hours=48)
    return ApprovalRequest.objects.filter(
        status=ApprovalStatus.SUBMITTED, created_at__lte=cutoff
    ).count()


def _retroactive_progress_pending_count(*, legal_entity=None) -> int:
    queryset = RetroactiveEntryRequest.objects.filter(
        request_type=RetroactiveEntryRequestType.PROGRESS,
        status=RetroactiveEntryRequestStatus.PENDING,
        project__is_active=True,
    )
    if legal_entity is not None:
        queryset = queryset.filter(project__legal_entity=legal_entity)
    return queryset.count()


def _timesheet_approval_pending_count(*, legal_entity=None) -> int:
    """Count only submitted sheets in active projects that HQ can approve."""
    queryset = Timesheet.objects.filter(
        status=TimesheetStatus.SUBMITTED,
        project__is_active=True,
    )
    if legal_entity is not None:
        queryset = queryset.filter(project__legal_entity=legal_entity)
    return queryset.count()


def _expense_execution_pending_count(*, legal_entity=None) -> int:
    queryset = ExpenseExecution.objects.filter(
        status__in=[ExpenseExecutionStatus.READY, ExpenseExecutionStatus.SCHEDULED],
        cost_actual__project__is_active=True,
    )
    if legal_entity is not None:
        queryset = queryset.filter(cost_actual__project__legal_entity=legal_entity)
    return queryset.count()


def _progress_correction_pending_count(*, legal_entity=None) -> int:
    queryset = ProgressCorrectionRequest.objects.filter(
        status=ProgressCorrectionStatus.HQ_REVIEW,
        project__is_active=True,
    )
    if legal_entity is not None:
        queryset = queryset.filter(project__legal_entity=legal_entity)
    return queryset.count()


def _hq_dual_closing_pending_count(*, legal_entity=None) -> int:
    period_ids = ClosingPeriod.objects.filter(
        approval_policy=ClosingApprovalPolicy.HQ_DUAL,
        status=ClosingStatus.OPEN,
    )
    if legal_entity is not None:
        period_ids = period_ids.filter(legal_entity=legal_entity)
    period_ids = period_ids.values("id")
    return ApprovalRequest.objects.filter(
        object_type="CLOSING_PERIOD",
        object_id__in=period_ids,
        status=ApprovalStatus.SUBMITTED,
    ).count()


def _closing_due_count(today: date, *, legal_entity=None) -> int:
    queryset = ClosingPeriod.objects.filter(
        year=today.year, month=today.month, status=ClosingStatus.OPEN
    )
    if legal_entity is not None:
        queryset = queryset.filter(legal_entity=legal_entity)
    period = queryset.first()
    return 1 if period else 0


def _missing_today_count(today: date, *, legal_entity=None) -> int:
    report_qs = DailyReport.objects.filter(report_date=today, status=DailyReportStatus.DRAFT)
    cost_qs = CostActual.objects.filter(report_date=today, status=CostActualStatus.DRAFT)
    progress_qs = DailyProgress.objects.filter(report_date=today, status="draft")
    if legal_entity is not None:
        report_qs = report_qs.filter(project__legal_entity=legal_entity)
        cost_qs = cost_qs.filter(project__legal_entity=legal_entity)
        progress_qs = progress_qs.filter(project__legal_entity=legal_entity)
    reports = report_qs.count()
    costs = cost_qs.count()
    progress = progress_qs.count()
    return reports + costs + progress


def get_risk_counts(*, legal_entity=None) -> dict:
    queryset = get_operational_dashboard_risk_queryset()
    if legal_entity is not None:
        queryset = queryset.filter(project__legal_entity=legal_entity)
    counts = queryset.aggregate(
        total=Count("id"),
        critical=Count("id", filter=Q(severity="critical")),
        high=Count("id", filter=Q(severity="high")),
    )
    return counts
