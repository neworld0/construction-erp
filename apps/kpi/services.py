from __future__ import annotations

from dataclasses import dataclass
from decimal import Decimal
from typing import Iterable

from django.db.models import Count, Q, Sum

from apps.closing.adjustments import (
    AdjustmentTargetType,
    get_adjustment_totals,
    has_pending_adjustments,
)
from apps.cost.models import CostActual, CostActualStatus, CostItem
from apps.labor.services import (
    compute_labor_data_quality,
    get_labor_totals_for_projects,
)
from apps.projects.models import (
    BudgetItem,
    Project,
    ProjectContract,
    ProjectContractStatus,
)

# Discovery:
# - contract model: apps.projects.models.ProjectContract (contract_amount)
# - budget model: apps.projects.models.BudgetItem (planned_amount)
# - actual model: apps.cost.models.CostActual (total_amount)
# - status semantics: ProjectContractStatus / BudgetItem.status, CostActualStatus


@dataclass
class KPIQuality:
    baseline_ready: bool
    missing: list[str]
    fallback_used: dict[str, str]
    confidence: str
    notes: list[str]


def compute_project_kpi(project_id, as_of_date=None, include_submitted=False) -> dict:
    result = compute_portfolio_kpi([project_id], as_of_date, include_submitted)
    return result[0] if result else {}


def compute_portfolio_kpi(
    projects_queryset_or_ids: Iterable[int] | Iterable[Project],
    as_of_date=None,
    include_submitted=False,
) -> list[dict]:
    projects = _normalize_projects(projects_queryset_or_ids)
    if not projects:
        return []

    project_ids = [project.id for project in projects]
    projects_map = {project.id: project for project in projects}

    contract_map = _load_contracts(project_ids)
    budget_map = _load_budget_totals(project_ids, include_submitted)
    budget_draft_map = _load_budget_drafts(project_ids)
    budget_lines = _load_budget_lines(project_ids, include_submitted)
    actual_map, draft_map = _load_actuals(project_ids, include_submitted)
    labor_totals = get_labor_totals_for_projects(project_ids, as_of_date=as_of_date)
    adjustment_map = get_adjustment_totals(
        project_ids,
        target_type=AdjustmentTargetType.COST,
        as_of_date=as_of_date,
    )
    pending_adjustments = has_pending_adjustments(
        project_ids,
        target_type=AdjustmentTargetType.COST,
        as_of_date=as_of_date,
    )

    results = []
    cbs_ids = set()
    for labor_summary in labor_totals.values():
        cbs_ids.update(labor_summary.get("by_cbs", {}).keys())
    cbs_map = {item.id: item for item in CostItem.objects.filter(id__in=cbs_ids)}
    for project_id in project_ids:
        project = projects_map[project_id]

        contract_amount, contract_status, contract_source, contract_notes = (
            _get_contract_baseline(project, contract_map.get(project_id))
        )
        budget_amount, budget_status, budget_source, budget_notes = _get_budget_baseline(
            budget_map.get(project_id),
            budget_draft_map.get(project_id),
        )
        budget_line_count = budget_lines.get(project_id, 0)

        labor_summary = labor_totals.get(project_id, {})
        labor_total = labor_summary.get("total")
        labor_sources = labor_summary.get("sources", {})
        labor_by_cbs = labor_summary.get("by_cbs", {})

        actual_submitted = actual_map.get(project_id)
        adjustment_total = adjustment_map.get(project_id) or 0
        if actual_submitted is None:
            actual_submitted = adjustment_total if adjustment_total else None
        else:
            actual_submitted = actual_submitted + adjustment_total
        if labor_total:
            if actual_submitted is None:
                actual_submitted = labor_total
            else:
                actual_submitted = actual_submitted + labor_total
        actual_draft = draft_map.get(project_id)
        actual_status = "OK"
        if actual_submitted is None and actual_draft is not None:
            actual_status = "PARTIAL"
        elif actual_submitted is None and actual_draft is None:
            actual_status = "UNKNOWN"

        metrics = _calc_metrics(contract_amount, budget_amount, actual_submitted)

        missing = []
        fallback_used = {}
        notes = []
        if contract_status == "MISSING":
            missing.append("contract")
        if budget_status == "MISSING":
            missing.append("budget")
        if contract_status == "FALLBACK":
            fallback_used["contract"] = contract_source
        if budget_status == "FALLBACK":
            fallback_used["budget"] = budget_source
        notes.extend(contract_notes)
        notes.extend(budget_notes)
        if include_submitted:
            notes.append("include_submitted=true")
        if project_id in pending_adjustments:
            notes.append("adjustment_pending")
        notes.append("change_order_not_configured")

        quality = _calc_quality(
            missing,
            fallback_used,
            notes,
            pending_adjustment=(project_id in pending_adjustments),
        )
        labor_quality = None
        if as_of_date:
            labor_quality = compute_labor_data_quality(
                project_id, as_of_date.year, as_of_date.month
            )

        results.append(
            {
                "project": {"id": project.id, "name": project.name},
                "contract": {
                    "amount": _to_int(contract_amount),
                    "status": contract_status,
                    "source": contract_source,
                },
                "budget": {
                    "amount": _to_int(budget_amount),
                    "status": budget_status,
                    "lines": budget_line_count,
                    "coverage_rate": None,
                    "source": budget_source,
                },
                "actual": {
                    "submitted": _to_int(actual_submitted),
                    "draft": _to_int(actual_draft),
                    "status": actual_status,
                },
                "labor": {
                    "total": _to_int(labor_total),
                    "timesheet_total": _to_int(labor_sources.get("timesheet_total")),
                    "payroll_total": _to_int(labor_sources.get("payroll_total")),
                    "by_cbs": [
                        {
                            "cbs_id": cbs_id,
                            "cbs_code": cbs_map.get(cbs_id).code if cbs_map.get(cbs_id) else None,
                            "cbs_name": cbs_map.get(cbs_id).get_display_name()
                            if cbs_map.get(cbs_id)
                            else None,
                            "amount": _to_int(amount),
                        }
                        for cbs_id, amount in (labor_by_cbs or {}).items()
                    ],
                    "data_quality": labor_quality,
                },
                "metrics": metrics,
                "data_quality": {
                    "baseline_ready": quality.baseline_ready,
                    "missing": quality.missing,
                    "fallback_used": quality.fallback_used,
                    "confidence": quality.confidence,
                    "notes": quality.notes,
                },
            }
        )

    return results


def _normalize_projects(projects_queryset_or_ids):
    if not projects_queryset_or_ids:
        return []
    if isinstance(projects_queryset_or_ids, Iterable) and not isinstance(
        projects_queryset_or_ids, Project
    ):
        projects = list(projects_queryset_or_ids)
        if projects and isinstance(projects[0], Project):
            return list(
                Project.objects.filter(id__in=[p.id for p in projects]).select_related(
                    "contract"
                )
            )
        return list(Project.objects.filter(id__in=projects).select_related("contract"))
    if isinstance(projects_queryset_or_ids, Project):
        return list(
            Project.objects.filter(id=projects_queryset_or_ids.id).select_related(
                "contract"
            )
        )
    return []


def _load_contracts(project_ids):
    return {
        contract.project_id: contract
        for contract in ProjectContract.objects.filter(project_id__in=project_ids)
    }


def _load_budget_totals(project_ids, include_submitted):
    statuses = [ProjectContractStatus.APPROVED]
    if include_submitted:
        statuses.append(ProjectContractStatus.SUBMITTED)
    return {
        row["project_id"]: row["total"]
        for row in (
            BudgetItem.objects.filter(project_id__in=project_ids, status__in=statuses)
            .values("project_id")
            .annotate(total=Sum("planned_amount"))
        )
    }


def _load_budget_drafts(project_ids):
    return {
        row["project_id"]: row["total"]
        for row in (
            BudgetItem.objects.filter(
                project_id__in=project_ids, status=ProjectContractStatus.DRAFT
            )
            .values("project_id")
            .annotate(total=Sum("planned_amount"))
        )
    }


def _load_budget_lines(project_ids, include_submitted):
    statuses = [ProjectContractStatus.APPROVED]
    if include_submitted:
        statuses.append(ProjectContractStatus.SUBMITTED)
    return {
        row["project_id"]: row["lines"]
        for row in (
            BudgetItem.objects.filter(project_id__in=project_ids, status__in=statuses)
            .values("project_id")
            .annotate(lines=Count("id"))
        )
    }


def _load_actuals(project_ids, include_submitted):
    statuses = [CostActualStatus.APPROVED]
    if include_submitted:
        statuses.append(CostActualStatus.SUBMITTED)
    actual_map = {
        row["project_id"]: row["total"]
        for row in (
            CostActual.objects.filter(project_id__in=project_ids, status__in=statuses)
            .values("project_id")
            .annotate(total=Sum("total_amount"))
        )
    }
    draft_map = {
        row["project_id"]: row["total"]
        for row in (
            CostActual.objects.filter(project_id__in=project_ids, status=CostActualStatus.DRAFT)
            .values("project_id")
            .annotate(total=Sum("total_amount"))
        )
    }
    return actual_map, draft_map


def _get_contract_baseline(project, contract):
    notes = []
    if contract is not None:
        amount = contract.contract_amount
        if contract.status == ProjectContractStatus.DRAFT:
            notes.append("contract_draft_used")
            return amount, "FALLBACK", "ProjectContract:DRAFT", notes
        return amount, "OK", "ProjectContract", notes

    if project.contract_amount is not None and project.contract_amount > 0:
        notes.append("contract_fallback_project")
        return project.contract_amount, "FALLBACK", "ProjectLegacy", notes

    return None, "MISSING", "None", notes


def _get_budget_baseline(approved_amount, draft_amount):
    notes = []
    if approved_amount is not None:
        return approved_amount, "OK", "BudgetItem", notes
    if draft_amount is not None:
        notes.append("budget_draft_used")
        return draft_amount, "FALLBACK", "BudgetItem:DRAFT", notes
    return None, "MISSING", "None", notes


def _calc_metrics(contract_amount, budget_amount, actual_submitted):
    contract_amount = _to_decimal(contract_amount)
    budget_amount = _to_decimal(budget_amount)
    actual_submitted = _to_decimal(actual_submitted)

    cost_variance = None
    cost_overrun_rate = None
    gross_margin_est = None
    gross_margin_rate_est = None
    if budget_amount is not None and actual_submitted is not None:
        cost_variance = actual_submitted - budget_amount
        if budget_amount != 0:
            cost_overrun_rate = actual_submitted / budget_amount
    if contract_amount is not None and actual_submitted is not None:
        gross_margin_est = contract_amount - actual_submitted
        if contract_amount != 0:
            gross_margin_rate_est = gross_margin_est / contract_amount

    return {
        "cost_variance": _to_int(cost_variance),
        "cost_overrun_rate": _to_float(cost_overrun_rate),
        "gross_margin_est": _to_int(gross_margin_est),
        "gross_margin_rate_est": _to_float(gross_margin_rate_est),
    }


def _calc_quality(missing, fallback_used, notes, pending_adjustment=False):
    baseline_ready = not missing
    if missing:
        confidence = "LOW"
    elif fallback_used:
        confidence = "MEDIUM"
    elif pending_adjustment:
        confidence = "MEDIUM"
    else:
        confidence = "HIGH"
    return KPIQuality(
        baseline_ready=baseline_ready,
        missing=missing,
        fallback_used=fallback_used,
        confidence=confidence,
        notes=notes,
    )


def _to_decimal(value):
    if value is None:
        return None
    if isinstance(value, Decimal):
        return value
    return Decimal(str(value))


def _to_int(value):
    if value is None:
        return None
    if isinstance(value, Decimal):
        return int(value)
    return int(value)


def _to_float(value):
    if value is None:
        return None
    return float(value)
