from __future__ import annotations

import logging
import time
from datetime import date
from decimal import Decimal

from django.apps import apps
from django.db.models import Case, Count, IntegerField, OuterRef, Subquery, Sum, When
from django.utils import timezone

from apps.closing.adjustments import (
    AdjustmentTargetType,
    get_adjustment_totals,
    get_cost_adjustment_by_category,
)
from apps.contracts.models import ContractChange, ContractChangeStatus
from apps.core.models import ApprovalRequest, ApprovalStatus
from apps.cost.models import CostActual, CostActualLine, CostActualStatus, CostItem
from apps.labor.services import get_labor_totals_for_projects
from apps.projects.models import Project, ProjectStatus
from apps.reports.models import FieldReport, FieldReportStatus
from apps.schedule.models import (
    DailyProgress,
    PlanChangeRequest,
    PlanChangeStatus,
    SchedulePlan,
    ScheduleTask,
)


def _safe_decimal(value):
    return value if value is not None else Decimal("0")


def _clamp01(value):
    if value is None:
        return Decimal("0")
    if value < 0:
        return Decimal("0")
    if value > 1:
        return Decimal("1")
    return value


def _status_included(status_value, include_submitted=False):
    if status_value is None:
        return False
    status = str(status_value).lower()
    if status in ("approved", "closed"):
        return True
    if include_submitted and status == "submitted":
        return True
    return False


def _approval_included(object_type, object_id, include_submitted=False):
    qs = ApprovalRequest.objects.filter(object_type=object_type, object_id=object_id)
    if qs.filter(status=ApprovalStatus.APPROVED).exists():
        return True
    if include_submitted and qs.filter(status=ApprovalStatus.SUBMITTED).exists():
        return True
    return False


def _baseline_ready(project, contract_amount, budget_total, planned_progress_percent):
    if not _project_status_is_approved(project.status):
        return False, "baseline_not_approved"
    if contract_amount is None or contract_amount <= 0:
        return False, "missing_contract"
    if budget_total is None or budget_total <= 0:
        return False, "missing_budget"
    if planned_progress_percent is None:
        return False, "missing_plan_dates"
    return True, None


def _project_status_is_approved(status_value):
    if status_value is None:
        return False
    status = str(status_value).lower()
    approved_values = [choice.value for choice in ProjectStatus]
    if any(str(value).lower() == "approved" for value in approved_values):
        return status == "approved"
    return status in ("active", "closed")


def _planned_progress_percent_for_items(project, wbs_items, as_of_date):
    if not wbs_items:
        if project.start_date and project.end_date:
            return _ratio_to_percent(project.start_date, project.end_date, as_of_date)
        return None

    all_have_dates = all(item.plan_start_date and item.plan_end_date for item in wbs_items)
    if all_have_dates:
        total_weight = sum((item.weight or Decimal("0") for item in wbs_items), Decimal("0"))
        if total_weight <= 0:
            return Decimal("0")
        weighted = Decimal("0")
        for item in wbs_items:
            ratio = _date_ratio(item.plan_start_date, item.plan_end_date, as_of_date)
            weighted += (item.weight or Decimal("0")) * ratio
        return (weighted / total_weight) * Decimal("100")

    if project.start_date and project.end_date:
        return _ratio_to_percent(project.start_date, project.end_date, as_of_date)
    return None


def _date_ratio(start, end, as_of_date):
    if not start or not end or not as_of_date:
        return Decimal("0")
    if end <= start:
        return Decimal("1") if as_of_date >= end else Decimal("0")
    if as_of_date <= start:
        return Decimal("0")
    if as_of_date >= end:
        return Decimal("1")
    total_days = (end - start).days
    elapsed = (as_of_date - start).days
    if total_days <= 0:
        return Decimal("0")
    return Decimal(elapsed) / Decimal(total_days)


def _ratio_to_percent(start, end, as_of_date):
    return _date_ratio(start, end, as_of_date) * Decimal("100")


def compute_project_kpi(project, as_of_date=None, include_submitted=False):
    if as_of_date is None:
        as_of_date = timezone.localdate()
    return compute_kpis_for_projects([project], as_of_date, include_submitted).get(
        project.id, {}
    )


def compute_kpis_for_projects(projects_queryset_or_ids, as_of_date=None, include_submitted=False):
    if as_of_date is None:
        as_of_date = timezone.localdate()

    start_ts = time.perf_counter()
    logger = logging.getLogger(__name__)

    if isinstance(projects_queryset_or_ids, (list, tuple, set)):
        project_ids = [
            item.id if isinstance(item, Project) else item
            for item in projects_queryset_or_ids
        ]
    else:
        project_ids = [project.id for project in projects_queryset_or_ids]

    projects = list(
        Project.objects.filter(id__in=project_ids)
        .select_related("contract")
        .prefetch_related("budgetitem_set", "wbsitem_set")
    )
    project_ids = [project.id for project in projects]

    if not project_ids:
        return {}

    if not project_ids:
        return {}

    contract_map = {
        project.id: getattr(project, "contract_amount", None) for project in projects
    }
    contract_model = apps.get_model("projects", "ProjectContract")
    if contract_model:
        for row in contract_model.objects.filter(project_id__in=project_ids).values(
            "project_id", "contract_amount"
        ):
            contract_map[row["project_id"]] = row["contract_amount"]

    budget_by_project = {}
    budget_by_category = {pid: {} for pid in project_ids}
    budget_model = apps.get_model("projects", "BudgetItem")
    if budget_model:
        for row in (
            budget_model.objects.filter(project_id__in=project_ids)
            .values("project_id", "category")
            .annotate(total=Sum("planned_amount"))
        ):
            pid = row["project_id"]
            total = row["total"] or Decimal("0")
            budget_by_project[pid] = budget_by_project.get(pid, Decimal("0")) + total
            budget_by_category[pid][row["category"]] = total

    cost_statuses = [CostActualStatus.APPROVED, CostActualStatus.CLOSED]
    if include_submitted:
        cost_statuses.append(CostActualStatus.SUBMITTED)

    cost_totals = {}
    cost_by_category = {pid: {} for pid in project_ids}
    cost_rows = (
        CostActualLine.objects.filter(
            cost_actual__project_id__in=project_ids,
            cost_actual__status__in=cost_statuses,
        )
        .values("cost_actual__project_id", "cost_item__category")
        .annotate(total=Sum("amount"))
    )
    for row in cost_rows:
        pid = row["cost_actual__project_id"]
        total = row["total"] or Decimal("0")
        cost_totals[pid] = cost_totals.get(pid, Decimal("0")) + total
        cost_by_category[pid][row["cost_item__category"]] = total

    labor_totals = get_labor_totals_for_projects(project_ids, as_of_date=as_of_date)
    labor_cbs_ids = set()
    for summary in labor_totals.values():
        labor_cbs_ids.update((summary.get("by_cbs") or {}).keys())
    labor_cbs_map = {
        item.id: item for item in CostItem.objects.filter(id__in=labor_cbs_ids)
    }

    adjustment_totals = get_adjustment_totals(
        project_ids,
        target_type=AdjustmentTargetType.COST,
        as_of_date=as_of_date,
    )
    adjustment_by_category = get_cost_adjustment_by_category(
        project_ids, as_of_date=as_of_date
    )
    for (project_id, category), amount in adjustment_by_category.items():
        cost_by_category.setdefault(project_id, {})
        cost_by_category[project_id][category] = cost_by_category[project_id].get(
            category, Decimal("0")
        ) + (amount or Decimal("0"))

    progress_statuses = ["approved"]
    if include_submitted:
        progress_statuses.append("submitted")

    progress_by_project = _bulk_actual_progress(project_ids, as_of_date, progress_statuses)

    pending_approvals = _pending_approvals(project_ids)
    pending_changes = _pending_changes(project_ids)

    results = {}
    for project in projects:
        contract_amount = _safe_decimal(contract_map.get(project.id))
        budget_total = _safe_decimal(budget_by_project.get(project.id))
        planned_progress = _planned_progress_percent_for_items(
            project,
            list(project.wbsitem_set.all()),
            as_of_date,
        )
        baseline_ready, excluded_reason = _baseline_ready(
            project, contract_amount, budget_total, planned_progress
        )

        actual_cost_total = _safe_decimal(cost_totals.get(project.id)) + _safe_decimal(
            adjustment_totals.get(project.id)
        )
        labor_summary = labor_totals.get(project.id, {})
        labor_total = _safe_decimal(labor_summary.get("total"))
        if labor_total:
            actual_cost_total += labor_total
            for cbs_id, amount in (labor_summary.get("by_cbs") or {}).items():
                cost_item = labor_cbs_map.get(cbs_id)
                category = (getattr(cost_item, "category", "") or "").upper() or "LABOR"
                cost_by_category.setdefault(project.id, {})
                cost_by_category[project.id][category] = (
                    cost_by_category[project.id].get(category, Decimal("0"))
                    + (amount or Decimal("0"))
                )
        actual_progress = _safe_decimal(
            progress_by_project.get(project.id, Decimal("0"))
        )

        ev = contract_amount * (actual_progress / Decimal("100"))
        pv = contract_amount * (
            (planned_progress or Decimal("0")) / Decimal("100")
        )
        ac = actual_cost_total

        cpi = (ev / ac) if ac > 0 else None
        spi = (ev / pv) if pv > 0 else None
        eac_budget = (budget_total / cpi) if cpi not in (None, 0) else None
        forecast_profit = (contract_amount - eac_budget) if eac_budget is not None else None
        budget_burn_rate = (actual_cost_total / budget_total) if budget_total > 0 else None
        schedule_progress_ratio = (
            actual_progress / planned_progress
            if planned_progress not in (None, 0)
            else None
        )

        risk_score, risk_band = _compute_risk_score(
            budget_burn_rate,
            schedule_progress_ratio,
            pending_approvals.get(project.id, 0),
            baseline_ready,
            pending_changes.get(project.id, False),
        )

        results[project.id] = {
            "flags": {
                "baseline_ready": baseline_ready,
                "excluded_reason": excluded_reason,
            },
            "baseline": {
                "contract_amount": contract_amount,
                "budget_total": budget_total,
                "budget_by_category": budget_by_category.get(project.id, {}),
                "planned_progress_percent": planned_progress,
            },
            "actual": {
                "actual_cost_total": actual_cost_total,
                "actual_cost_by_category": cost_by_category.get(project.id, {}),
                "actual_progress_percent": actual_progress,
                "labor_cost_total": labor_total,
            },
            "EV": ev,
            "PV": pv,
            "AC": ac,
            "CPI": cpi,
            "SPI": spi,
            "EAC_budget": eac_budget,
            "forecast_profit": forecast_profit,
            "budget_burn_rate": budget_burn_rate,
            "schedule_progress_ratio": schedule_progress_ratio,
            "pending_approvals_count": pending_approvals.get(project.id, 0),
            "risk_score": risk_score,
            "risk_band": risk_band,
        }

    if logger.isEnabledFor(logging.DEBUG):
        elapsed = (time.perf_counter() - start_ts) * 1000
        logger.debug(
            "KPI bulk computed for %s projects (include_submitted=%s) in %.2fms",
            len(project_ids),
            include_submitted,
            elapsed,
        )

    return results


def _bulk_actual_progress(project_ids, as_of_date, statuses):
    plans = (
        SchedulePlan.objects.filter(project_id__in=project_ids, is_active=True)
        .values("id", "project_id")
    )
    plan_map = {row["id"]: row["project_id"] for row in plans}
    if not plan_map:
        return {}

    tasks = (
        ScheduleTask.objects.filter(plan_id__in=plan_map.keys(), is_active=True)
        .values("id", "plan_id", "weight_percent")
    )
    progress_rows = (
        DailyProgress.objects.filter(
            plan_id__in=plan_map.keys(),
            report_date__lte=as_of_date,
            status__in=statuses,
        )
        .order_by("task_id", "-report_date", "-id")
        .values("task_id", "progress_percent")
    )

    latest_by_task = {}
    for row in progress_rows:
        task_id = row["task_id"]
        if task_id not in latest_by_task:
            latest_by_task[task_id] = row["progress_percent"]

    summary = {}
    weight_totals = {}
    for task in tasks:
        project_id = plan_map.get(task["plan_id"])
        if project_id is None:
            continue
        weight = task["weight_percent"] or Decimal("0")
        weight_totals[project_id] = weight_totals.get(project_id, Decimal("0")) + weight
        progress = latest_by_task.get(task["id"], Decimal("0"))
        summary[project_id] = summary.get(project_id, Decimal("0")) + (weight * progress)

    result = {}
    for project_id, weighted_sum in summary.items():
        total_weight = weight_totals.get(project_id, Decimal("0"))
        if total_weight > 0:
            result[project_id] = (weighted_sum / total_weight)
        else:
            result[project_id] = Decimal("0")
    return result


def _pending_approvals(project_ids):
    counts = {pid: 0 for pid in project_ids}
    cost_project = CostActual.objects.filter(id=OuterRef("object_id")).values("project_id")[:1]
    progress_project = DailyProgress.objects.filter(id=OuterRef("object_id")).values("project_id")[:1]
    report_project = FieldReport.objects.filter(id=OuterRef("object_id")).values("project_id")[:1]

    approvals = (
        ApprovalRequest.objects.filter(
            status=ApprovalStatus.SUBMITTED,
            object_type__in=["COST_ACTUAL", "DAILY_PROGRESS", "FIELD_REPORT"],
        )
        .annotate(
            project_id=Case(
                When(object_type="COST_ACTUAL", then=Subquery(cost_project)),
                When(object_type="DAILY_PROGRESS", then=Subquery(progress_project)),
                When(object_type="FIELD_REPORT", then=Subquery(report_project)),
                default=None,
                output_field=IntegerField(),
            )
        )
        .filter(project_id__in=project_ids)
        .values("project_id")
        .annotate(total=Count("id"))
    )

    for row in approvals:
        counts[row["project_id"]] = int(row["total"] or 0)

    return counts


def _pending_changes(project_ids):
    pending = {pid: False for pid in project_ids}
    contract_pending = (
        ContractChange.objects.filter(
            project_id__in=project_ids, status=ContractChangeStatus.SUBMITTED
        )
        .values_list("project_id", flat=True)
        .distinct()
    )
    for project_id in contract_pending:
        pending[project_id] = True

    plan_pending = (
        PlanChangeRequest.objects.filter(
            project_id__in=project_ids, status=PlanChangeStatus.SUBMITTED
        )
        .values_list("project_id", flat=True)
        .distinct()
    )
    for project_id in plan_pending:
        pending[project_id] = True
    return pending


def _compute_risk_score(
    budget_burn_rate,
    schedule_progress_ratio,
    pending_count,
    baseline_ready,
    has_pending_change,
):
    budget_risk = _clamp01(
        (Decimal(budget_burn_rate) - Decimal("0.8")) / Decimal("0.2")
        if budget_burn_rate is not None
        else Decimal("0")
    )
    schedule_risk = _clamp01(
        (Decimal("1") - Decimal(schedule_progress_ratio)) / Decimal("0.2")
        if schedule_progress_ratio is not None
        else Decimal("0")
    )
    pending_risk = _clamp01(
        Decimal(pending_count or 0) / Decimal("5")
    )
    if not baseline_ready:
        baseline_change_risk = Decimal("1")
    elif has_pending_change:
        baseline_change_risk = Decimal("0.7")
    else:
        baseline_change_risk = Decimal("0")

    risk_score = (
        Decimal("30") * budget_risk
        + Decimal("30") * schedule_risk
        + Decimal("20") * pending_risk
        + Decimal("20") * baseline_change_risk
    )
    if risk_score >= 60:
        band = "RED"
    elif risk_score >= 30:
        band = "YELLOW"
    else:
        band = "GREEN"
    return risk_score, band
