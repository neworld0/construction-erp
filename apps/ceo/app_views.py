from __future__ import annotations

from datetime import date
from decimal import Decimal

from django.contrib.auth.decorators import login_required
from django.apps import apps
from django.db import transaction
from django.db.models import Sum
from django.shortcuts import get_object_or_404, redirect, render
from django.utils import timezone

from apps.core.rbac.models import Role
from apps.core.rbac.permissions import get_user_role, require_role
from apps.audit.services.logger import log_action
from apps.contracts.models import ContractChange, ContractChangeStatus
from apps.projects.models import (
    Project,
    WBSChangeLine,
    WBSChangeRequest,
    WBSChangeRequestStatus,
    WBSChangeRequestType,
    WBSItem,
)
from apps.cost.models import CostActual, CostActualStatus
from apps.evidence.services.policy import check_evidence_required
from apps.field.models import DailyReport, DailyReportStatus
from apps.finance.models import CashEvent, CashEventStatus, CashEventType
from apps.finance.services.profit_loss import _calculate_margin
from apps.risk.models import RiskFinding, RiskFindingStatus
from apps.schedule.models import DailyProgress, PlanChangeRequest, PlanChangeStatus
from apps.core.models import ApprovalRequest, ApprovalStatus
from apps.reports.models import FieldReport

from .services.dashboard import get_ceo_dashboard, get_ceo_projects_list
from .services.kpi_engine import compute_project_kpi


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
    include_submitted = request.GET.get("include_submitted") == "1"
    baseline_only = request.GET.get("baseline_only", "1") != "0"
    period_start = as_of_date.replace(day=1)

    dashboard = get_ceo_dashboard(as_of_date)
    projects = dashboard.get("projects", [])
    project_ids = [p["project_id"] for p in projects]
    primary_project_id = project_ids[0] if project_ids else None
    chart_labels = [p.get("project_name") or f"#{p.get('project_id')}" for p in projects]
    chart_values = [float(p.get("overall_progress_percent") or 0) for p in projects]

    total_revenue = sum((_safe_decimal(p.get("recognized_revenue")) for p in projects), Decimal("0"))
    total_cost = sum((_safe_decimal(p.get("accrual_cost")) for p in projects), Decimal("0"))
    total_labor = sum((_safe_decimal(p.get("labor_cost")) for p in projects), Decimal("0"))
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

    query_bits = [f"as_of_date={as_of_date.isoformat()}"]
    if include_submitted:
        query_bits.append("include_submitted=1")
    if not baseline_only:
        query_bits.append("baseline_only=0")
    csv_query = "&".join(query_bits)

    context = {
        "as_of_date": as_of_date,
        "include_submitted": include_submitted,
        "baseline_only": baseline_only,
        "projects": projects,
        "total_revenue": total_revenue,
        "total_cost": total_cost,
        "total_labor": total_labor,
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
        "csv_url": f"/api/ceo/reports/project-summary.csv?{csv_query}",
        "role": get_user_role(request.user),
        "chart_labels": chart_labels,
        "chart_values": chart_values,
        "primary_project_id": primary_project_id,
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


@login_required
def ceo_project_kpi_detail(request, project_id):
    require_role(request.user, [Role.CEO, Role.HQ])
    project = get_object_or_404(Project, id=project_id)
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
    chart_progress_labels = ["계획", "실제"]
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
    require_role(request.user, [Role.CEO])
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
    }
    return render(request, "ceo/wbs_change_list.html", context)


@login_required
def ceo_wbs_change_detail(request, request_id):
    require_role(request.user, [Role.CEO])
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
                "error": "제출 상태가 아닌 요청은 승인할 수 없습니다.",
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
                "error": "변경요청(CHANGE ORDER)이 승인되지 않아 승인할 수 없습니다.",
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
                "error": "가중치 합계 또는 일정 정보를 확인해주세요. (100% 필수)",
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
                "error": "반려 사유를 입력하세요.",
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
