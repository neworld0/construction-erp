from datetime import date
from decimal import Decimal

from django.db.models import Case, Count, IntegerField, Max, Q, Sum, Value, When

from apps.cost.models import CostActualLine, CostActualStatus, RevenueRecognition
from apps.cost.services.accrual_cost import get_accrual_cost_by_project
from apps.finance.services.cash_summary import get_cash_summary
from apps.finance.services.profit_loss import _calculate_margin, get_profit_loss_by_project
from apps.labor.services import get_labor_totals_for_projects
from apps.projects.models import Project
from apps.risk.models import RiskFinding
from django.utils import timezone
from apps.schedule.models import DailyProgress, SchedulePlan, ScheduleTask
from apps.schedule.services.progress_agg import get_project_progress


def _safe_decimal(value):
    return value if value is not None else Decimal("0")


def _risk_counts_by_project(project_ids):
    if not project_ids:
        return {}
    rows = (
        RiskFinding.objects.filter(project_id__in=project_ids)
        .values("project_id")
        .annotate(
            open_count=Count("id", filter=Q(status="open")),
            critical_count=Count("id", filter=Q(status="open", severity="critical")),
        )
    )
    return {
        row["project_id"]: {
            "risk_open_count": row["open_count"],
            "risk_critical_count": row["critical_count"],
        }
        for row in rows
    }


def _latest_risk_updated_at(project_ids):
    if not project_ids:
        return {}
    rows = (
        RiskFinding.objects.filter(project_id__in=project_ids)
        .values("project_id")
        .annotate(latest=Max("updated_at"))
    )
    return {row["project_id"]: row["latest"] for row in rows}


def get_ceo_dashboard(as_of_date=None):
    projects = get_ceo_projects_list({"as_of_date": as_of_date})
    return {
        "as_of_date": as_of_date,
        "projects": projects,
    }


def get_ceo_projects_list(filters):
    filters = filters or {}
    queryset = Project.objects.filter(is_active=True).order_by("id").select_related()
    query = (filters.get("q") or "").strip()
    if query:
        queryset = queryset.filter(name__icontains=query)
    project_ids = list(queryset.values_list("id", flat=True))

    progress_map = _bulk_progress(project_ids, filters.get("as_of_date"))
    accrual_map = _bulk_accrual(project_ids, filters.get("as_of_date"))
    labor_map = get_labor_totals_for_projects(
        project_ids, as_of_date=filters.get("as_of_date") or timezone.localdate()
    )
    profit_map = _bulk_profit(project_ids, filters.get("as_of_date"))
    risk_counts = _risk_counts_by_project(project_ids)
    risk_updates = _latest_risk_updated_at(project_ids)

    results = []
    for project in queryset:
        progress = progress_map.get(project.id, {"overall_progress_percent": Decimal("0")})
        accrual = accrual_map.get(project.id, _empty_accrual())
        labor_summary = labor_map.get(project.id, {})
        labor_cost = _safe_decimal(labor_summary.get("total"))
        if "LABOR" not in accrual.get("by_category", {}):
            accrual["by_category"]["LABOR"] = Decimal("0")
        accrual["by_category"]["LABOR"] += labor_cost
        accrual["total_cost"] += labor_cost
        profit_loss = profit_map.get(project.id, _empty_profit(project.id))
        recognized_revenue = _safe_decimal(profit_loss.get("recognized_revenue"))
        accrual_cost = _safe_decimal(accrual.get("total_cost"))
        profit = recognized_revenue - accrual_cost
        margin_percent = _calculate_margin(recognized_revenue, profit)
        summary = {
            "project_id": project.id,
            "project_name": getattr(project, "name", ""),
            "overall_progress_percent": _safe_decimal(progress.get("overall_progress_percent")),
            "recognized_revenue": recognized_revenue,
            "accrual_cost": accrual_cost,
            "labor_cost": labor_cost,
            "profit": profit,
            "margin_percent": margin_percent,
            "tasks": progress.get("tasks", []),
            "cost_by_category": accrual.get("by_category", {}),
            "updated_at": None,
            "risk_open_count": 0,
            "risk_critical_count": 0,
        }

        risk = risk_counts.get(project.id, {"risk_open_count": 0, "risk_critical_count": 0})
        summary["risk_open_count"] = risk["risk_open_count"]
        summary["risk_critical_count"] = risk["risk_critical_count"]

        summary["updated_at"] = risk_updates.get(project.id)
        results.append(summary)

    sort_key = (filters.get("sort") or "").strip()
    if sort_key == "profit_desc":
        results.sort(key=lambda item: item["profit"], reverse=True)
    elif sort_key == "margin_desc":
        results.sort(key=lambda item: item["margin_percent"], reverse=True)
    elif sort_key == "progress_desc":
        results.sort(key=lambda item: item["overall_progress_percent"], reverse=True)
    elif sort_key == "risk_desc":
        results.sort(key=lambda item: item["risk_open_count"], reverse=True)

    return results


def get_ceo_project_summary(project_id, as_of_date=None):
    if as_of_date is None:
        as_of_date = timezone.localdate()
    period_start = as_of_date.replace(day=1)
    progress = get_project_progress(project_id, as_of_date)
    profit_loss = get_profit_loss_by_project(project_id)
    accrual = get_accrual_cost_by_project(project_id)
    labor_summary = get_labor_totals_for_projects([project_id], as_of_date=as_of_date).get(
        project_id, {}
    )
    labor_cost = _safe_decimal(labor_summary.get("total"))
    if "LABOR" not in accrual.get("by_category", {}):
        accrual["by_category"]["LABOR"] = Decimal("0")
    accrual["by_category"]["LABOR"] += labor_cost
    accrual["total_cost"] += labor_cost
    cash_summary = get_cash_summary(project_id, period_start, as_of_date)
    risk_findings = list(
        RiskFinding.objects.filter(project_id=project_id)
        .annotate(
            status_rank=Case(
                When(status="open", then=Value(0)),
                When(status="ack", then=Value(1)),
                default=Value(2),
                output_field=IntegerField(),
            )
        )
        .order_by("status_rank", "-updated_at")
        .values("id", "title", "severity", "status", "updated_at")[:5]
    )

    return {
        "project_id": project_id,
        "project_name": "",
        "overall_progress_percent": _safe_decimal(progress.get("overall_progress_percent")),
        "tasks": progress.get("tasks", []),
        "recognized_revenue": _safe_decimal(profit_loss.get("recognized_revenue")),
        "accrual_cost": _safe_decimal(accrual.get("total_cost")),
        "labor_cost": labor_cost,
        "cost_by_category": accrual.get("by_category", {}),
        "profit": _safe_decimal(profit_loss.get("profit")),
        "margin_percent": _safe_decimal(profit_loss.get("margin_percent")),
        "cash_summary": cash_summary,
        "risk_findings": risk_findings,
        "risk_open_count": 0,
        "risk_critical_count": 0,
        "updated_at": None,
    }


def _bulk_progress(project_ids, as_of_date):
    if not project_ids:
        return {}
    if as_of_date is None:
        as_of_date = timezone.localdate()
    plans = (
        SchedulePlan.objects.filter(project_id__in=project_ids, is_active=True)
        .values("id", "project_id", "version_no")
    )
    plan_map = {row["id"]: row["project_id"] for row in plans}
    if not plan_map:
        return {}

    tasks = (
        ScheduleTask.objects.filter(plan_id__in=plan_map.keys(), is_active=True)
        .values("id", "plan_id", "name", "weight_percent")
    )
    progress_rows = (
        DailyProgress.objects.filter(plan_id__in=plan_map.keys(), report_date__lte=as_of_date)
        .order_by("task_id", "-report_date", "-id")
        .values("task_id", "progress_percent")
    )
    latest_by_task = {}
    for row in progress_rows:
        task_id = row["task_id"]
        if task_id not in latest_by_task:
            latest_by_task[task_id] = row["progress_percent"]

    summary = {}
    for task in tasks:
        project_id = plan_map.get(task["plan_id"])
        if project_id is None:
            continue
        entry = summary.setdefault(
            project_id,
            {"overall_progress_percent": Decimal("0"), "tasks": []},
        )
        weight = task["weight_percent"] or Decimal("0")
        progress = latest_by_task.get(task["id"], Decimal("0"))
        entry["overall_progress_percent"] += (weight * progress) / Decimal("100")
        entry["tasks"].append(
            {
                "task_id": task["id"],
                "name": task["name"],
                "weight_percent": weight,
                "latest_progress_percent": progress,
            }
        )

    return summary


def _bulk_accrual(project_ids, as_of_date=None):
    if not project_ids:
        return {}
    cost_filters = {
        "cost_actual__project_id__in": project_ids,
        "cost_actual__status__in": [CostActualStatus.APPROVED, CostActualStatus.CLOSED],
    }
    if as_of_date is not None:
        cost_filters["cost_actual__report_date__lte"] = as_of_date
    rows = (
        CostActualLine.objects.filter(**cost_filters)
        .values("cost_actual__project_id", "cost_item__category")
        .annotate(total=Sum("amount"))
    )
    summary = {project_id: _empty_accrual() for project_id in project_ids}
    for row in rows:
        project_id = row["cost_actual__project_id"]
        category = (row["cost_item__category"] or "").upper()
        summary[project_id]["by_category"][category] = row["total"] or Decimal("0")
        summary[project_id]["total_cost"] += row["total"] or Decimal("0")
    return summary


def _bulk_profit(project_ids, as_of_date=None):
    if not project_ids:
        return {}
    projects = Project.objects.filter(id__in=project_ids)
    snapshot_by_project = {}
    for project in projects:
        snapshot = getattr(project, "active_contract_snapshot", None)
        snapshot_by_project[project.id] = getattr(snapshot, "id", None) if snapshot else None

    queryset = RevenueRecognition.objects.filter(project_id__in=project_ids).order_by(
        "project_id", "-as_of_date", "-id"
    )
    if as_of_date is not None:
        queryset = queryset.filter(as_of_date__lte=as_of_date)
    latest_by_project = {}
    for record in queryset:
        snapshot_id = snapshot_by_project.get(record.project_id)
        record_snapshot_id = getattr(record, "contract_snapshot_id", None)
        if snapshot_id is not None and record_snapshot_id != snapshot_id:
            continue
        if record.project_id not in latest_by_project:
            latest_by_project[record.project_id] = record

    summary = {}
    for project_id in project_ids:
        revenue = latest_by_project.get(project_id)
        recognized = revenue.recognized_revenue if revenue else Decimal("0")
        summary[project_id] = {
            "recognized_revenue": recognized,
        }
    return summary


def _empty_accrual():
    return {"total_cost": Decimal("0"), "by_category": {}}


def _empty_profit(project_id):
    return {"project_id": project_id, "recognized_revenue": Decimal("0"), "profit": Decimal("0"), "margin_percent": Decimal("0")}
