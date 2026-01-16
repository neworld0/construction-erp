from __future__ import annotations

from datetime import date
from decimal import Decimal

from django.contrib.auth.decorators import login_required
from django.db.models import Sum
from django.shortcuts import render
from django.utils import timezone

from apps.core.rbac.models import Role
from apps.core.rbac.permissions import get_user_role, require_role
from apps.cost.models import CostActual, CostActualStatus
from apps.evidence.services.policy import check_evidence_required
from apps.field.models import DailyReport, DailyReportStatus
from apps.finance.models import CashEvent, CashEventStatus, CashEventType
from apps.finance.services.profit_loss import _calculate_margin
from apps.risk.models import RiskFinding, RiskFindingStatus
from apps.contracts.models import ContractChange, ContractChangeStatus
from apps.schedule.models import PlanChangeRequest, PlanChangeStatus
from apps.core.models import ApprovalRequest, ApprovalStatus

from .services.dashboard import get_ceo_dashboard, get_ceo_projects_list


def _parse_date(value):
    if not value:
        return None
    try:
        return date.fromisoformat(value)
    except ValueError:
        return None


def _safe_decimal(value):
    return value if value is not None else Decimal("0")


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


@login_required
def ceo_home(request):
    require_role(request.user, [Role.CEO, Role.HQ])
    as_of_date = _parse_date(request.GET.get("as_of_date"))
    if as_of_date is None:
        as_of_date = timezone.localdate()
    period_start = as_of_date.replace(day=1)

    dashboard = get_ceo_dashboard(as_of_date)
    projects = dashboard.get("projects", [])
    project_ids = [p["project_id"] for p in projects]
    chart_labels = [p.get("project_name") or f"#{p.get('project_id')}" for p in projects]
    chart_values = [float(p.get("overall_progress_percent") or 0) for p in projects]

    total_revenue = sum((_safe_decimal(p.get("recognized_revenue")) for p in projects), Decimal("0"))
    total_cost = sum((_safe_decimal(p.get("accrual_cost")) for p in projects), Decimal("0"))
    total_profit = total_revenue - total_cost
    avg_progress = (
        sum((_safe_decimal(p.get("overall_progress_percent")) for p in projects), Decimal("0"))
        / Decimal(len(projects))
        if projects
        else Decimal("0")
    )
    margin_percent = _calculate_margin(total_revenue, total_profit)

    cash_summary = _cash_summary(project_ids, period_start, as_of_date)

    risk_open_count = RiskFinding.objects.filter(
        status=RiskFindingStatus.OPEN
    ).count()
    risk_critical_count = RiskFinding.objects.filter(
        status=RiskFindingStatus.OPEN, severity="critical"
    ).count()
    risk_open = list(
        RiskFinding.objects.filter(status=RiskFindingStatus.OPEN)
        .select_related("project", "rule")
        .order_by("-updated_at")[:5]
    )

    pending_reports = DailyReport.objects.filter(status=DailyReportStatus.SUBMITTED).count()
    pending_costs = CostActual.objects.filter(status=CostActualStatus.SUBMITTED).count()
    pending_contracts = ContractChange.objects.filter(
        status=ContractChangeStatus.SUBMITTED
    ).count()
    pending_plans = PlanChangeRequest.objects.filter(
        status=PlanChangeStatus.SUBMITTED
    ).count()
    pending_approvals = ApprovalRequest.objects.filter(
        status=ApprovalStatus.SUBMITTED
    ).count()

    evidence_missing = 0
    for change in ContractChange.objects.filter(status=ContractChangeStatus.SUBMITTED):
        ok, _reason = check_evidence_required("CONTRACT_CHANGE", change.id, "SUBMIT")
        if not ok:
            evidence_missing += 1
    for plan in PlanChangeRequest.objects.filter(status=PlanChangeStatus.SUBMITTED):
        ok, _reason = check_evidence_required("PLAN_CHANGE_REQUEST", plan.id, "SUBMIT")
        if not ok:
            evidence_missing += 1

    context = {
        "as_of_date": as_of_date,
        "projects": projects,
        "total_revenue": total_revenue,
        "total_cost": total_cost,
        "total_profit": total_profit,
        "margin_percent": margin_percent,
        "avg_progress": avg_progress,
        "cash_summary": cash_summary,
        "risk_open_count": risk_open_count,
        "risk_critical_count": risk_critical_count,
        "risk_open": risk_open,
        "pending_reports": pending_reports,
        "pending_costs": pending_costs,
        "pending_contracts": pending_contracts,
        "pending_plans": pending_plans,
        "pending_approvals": pending_approvals,
        "evidence_missing": evidence_missing,
        "csv_url": f"/api/ceo/reports/project-summary.csv?as_of_date={as_of_date.isoformat()}",
        "role": get_user_role(request.user),
        "chart_labels": chart_labels,
        "chart_values": chart_values,
    }
    return render(request, "ceo/app_home.html", context)


@login_required
def ceo_projects_list(request):
    require_role(request.user, [Role.CEO, Role.HQ])
    as_of_date = _parse_date(request.GET.get("as_of_date"))
    projects = get_ceo_projects_list({"as_of_date": as_of_date})
    context = {
        "projects": projects,
        "as_of_date": as_of_date,
        "role": get_user_role(request.user),
    }
    return render(request, "ceo/app_projects.html", context)
