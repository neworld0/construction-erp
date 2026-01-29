from __future__ import annotations

from dataclasses import dataclass
from datetime import date

from django.db.models import Count, Q
from django.utils import timezone

from apps.closing.models import ClosingPeriod, ClosingStatus
from apps.contracts.models import ContractChange, ContractChangeStatus
from apps.core.models import ApprovalRequest, ApprovalStatus
from apps.cost.models import CostActual, CostActualStatus
from apps.field.models import DailyReport, DailyReportStatus
from apps.risk.models import RiskFinding, RiskFindingStatus
from apps.schedule.models import DailyProgress, PlanChangeRequest, PlanChangeStatus

ICON_RED = "\U0001F534"
ICON_ORANGE = "\U0001F7E0"
ICON_GREEN = "\U0001F7E2"


@dataclass
class TodoItem:
    icon: str
    text: str
    count: int
    url: str


def build_hq_todos(risk_counts: dict) -> dict:
    today = timezone.localdate()

    approval_total = _approval_pending_count()
    risk_critical = risk_counts.get("critical", 0)
    risk_high = risk_counts.get("high", 0)
    closing_due = _closing_due_count(today)
    missing_today = _missing_today_count(today)
    delayed_48h = _approval_delayed_48h_count()

    todos = [
        TodoItem(
            icon=_status_icon(approval_total, warn_threshold=1, critical_threshold=5),
            text="\uc2b9\uc778 \ub300\uae30 \ucc98\ub9ac",
            count=approval_total,
            url="/app/hq/#pending-reports",
        )
    ]

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
            url="/app/hq/#risks",
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
            url="/app/hq/projects/",
        )
    )

    if delayed_48h is not None:
        todos.append(
            TodoItem(
                icon=ICON_RED if delayed_48h > 0 else ICON_GREEN,
                text="48\uc2dc\uac04+ \uc2b9\uc778 \uc9c0\uc5f0",
                count=delayed_48h,
                url="/app/hq/#pending-reports",
            )
        )

    todos_sorted = [todos[0]] + sorted(todos[1:], key=lambda item: _icon_rank(item.icon))
    todos_sorted = todos_sorted[:5]

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


def _approval_pending_count() -> int:
    approvals = ApprovalRequest.objects.filter(status=ApprovalStatus.SUBMITTED).count()
    daily_reports = DailyReport.objects.filter(status=DailyReportStatus.SUBMITTED).count()
    costs = CostActual.objects.filter(status=CostActualStatus.SUBMITTED).count()
    plan_changes = PlanChangeRequest.objects.filter(status=PlanChangeStatus.SUBMITTED).count()
    contract_changes = ContractChange.objects.filter(
        status=ContractChangeStatus.SUBMITTED
    ).count()
    return approvals + daily_reports + costs + plan_changes + contract_changes


def _approval_delayed_48h_count() -> int:
    cutoff = timezone.now() - timezone.timedelta(hours=48)
    return ApprovalRequest.objects.filter(
        status=ApprovalStatus.SUBMITTED, created_at__lte=cutoff
    ).count()


def _closing_due_count(today: date) -> int:
    period = ClosingPeriod.objects.filter(
        year=today.year, month=today.month, status=ClosingStatus.OPEN
    ).first()
    return 1 if period else 0


def _missing_today_count(today: date) -> int:
    reports = DailyReport.objects.filter(
        report_date=today, status=DailyReportStatus.DRAFT
    ).count()
    costs = CostActual.objects.filter(
        report_date=today, status=CostActualStatus.DRAFT
    ).count()
    progress = DailyProgress.objects.filter(report_date=today, status="draft").count()
    return reports + costs + progress


def get_risk_counts() -> dict:
    counts = RiskFinding.objects.filter(status=RiskFindingStatus.OPEN).aggregate(
        total=Count("id"),
        critical=Count("id", filter=Q(severity="critical")),
        high=Count("id", filter=Q(severity="high")),
    )
    return counts
