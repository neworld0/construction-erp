"""Align the OPS-1B sanitized pilot baseline with policy A.

Run with --apply only against the guarded local demo database.
"""

from __future__ import annotations

import argparse
import os
from decimal import Decimal

os.environ.setdefault("DJANGO_SETTINGS_MODULE", "config.settings.local")

import django

django.setup()

from django.conf import settings
from django.db import transaction
from django.db.models import Sum

from apps.contracts.models import ContractSnapshot
from apps.cost.models import CostItem, CostItemCategory, RevenueRecognition
from apps.projects.models import BudgetCategory, BudgetItem, Project, WBSItem
from apps.schedule.models import DailyProgress, SchedulePlan, ScheduleTask


PROJECT_CODE = "OPS1B-RERUN-SAMPLE-001"
RESIDUAL_CODE = "OPS1B-RESIDUAL"
RESIDUAL_NAME = "기타공정"
RESIDUAL_WEIGHT = Decimal("15")
RESIDUAL_BUDGET = 181_022_700


def _assert_local_demo_database() -> None:
    database = settings.DATABASES["default"]
    engine = str(database.get("ENGINE", ""))
    name = str(database.get("NAME", "")).lower()
    host = str(database.get("HOST", "")).lower()
    if not (engine.endswith("postgresql") and "demo" in name and host in {"127.0.0.1", "localhost"}):
        raise SystemExit("SEED_UPDATE_HOLD: unsafe database guard")


def _project() -> Project:
    project = Project.objects.filter(code=PROJECT_CODE).first()
    if project is None:
        raise SystemExit("SEED_UPDATE_HOLD: PILOT_PROJECT_NOT_FOUND")
    return project


def _sum(queryset, field: str) -> Decimal:
    return Decimal(queryset.aggregate(total=Sum(field))["total"] or 0)


def _latest_progress_by_task(plan: SchedulePlan, as_of_date):
    latest = {}
    rows = (
        DailyProgress.objects.filter(plan=plan, report_date__lte=as_of_date)
        .order_by("task_id", "-report_date", "-id")
        .values_list("task_id", "progress_percent")
    )
    for task_id, progress in rows:
        latest.setdefault(task_id, Decimal(progress or 0))
    return latest


def _snapshot(project: Project) -> dict[str, Decimal]:
    plan = SchedulePlan.objects.filter(project=project, is_active=True).first()
    budget_total = _sum(BudgetItem.objects.filter(project=project), "planned_amount")
    wbs_total = _sum(WBSItem.objects.filter(project=project, is_baseline=True), "weight")
    task_total = _sum(ScheduleTask.objects.filter(plan=plan, is_active=True), "weight_percent") if plan else Decimal("0")
    latest_revenue = RevenueRecognition.objects.filter(project=project).order_by("-as_of_date", "-id").first()
    cost_total = Decimal("0")
    from apps.cost.models import CostActual

    cost_total = _sum(CostActual.objects.filter(project=project), "total_amount")
    return {
        "budget_total": budget_total,
        "wbs_total": wbs_total,
        "task_total": task_total,
        "recognized_revenue": Decimal(latest_revenue.recognized_revenue or 0) if latest_revenue else Decimal("0"),
        "revenue_progress": Decimal(latest_revenue.progress_percent or 0) if latest_revenue else Decimal("0"),
        "cost_total": cost_total,
    }


def _apply() -> dict[str, object]:
    _assert_local_demo_database()
    project = _project()
    before = _snapshot(project)
    with transaction.atomic():
        residual_item, _created = CostItem.objects.get_or_create(
            code=RESIDUAL_CODE,
            defaults={
                "name": RESIDUAL_NAME,
                "category": CostItemCategory.OTHER,
                "cost_type": "E",
                "work_type": "99",
                "is_direct": True,
                "is_active": True,
            },
        )
        BudgetItem.objects.update_or_create(
            project=project,
            cost_item=residual_item,
            name=f"{RESIDUAL_NAME} 예산",
            defaults={
                "category": BudgetCategory.OTHER,
                "planned_amount": RESIDUAL_BUDGET,
                "status": "approved",
                "note": "OPS-1B-R1 POLICY A contract-budget residual baseline",
            },
        )
        WBSItem.objects.update_or_create(
            project=project,
            name=RESIDUAL_NAME,
            defaults={
                "weight": RESIDUAL_WEIGHT,
                "sort_order": 4,
                "plan_start_date": project.start_date,
                "plan_end_date": project.end_date,
                "baseline_version": 1,
                "is_baseline": True,
            },
        )
        plan = SchedulePlan.objects.filter(project=project, is_active=True).first()
        if plan is None:
            raise RuntimeError("SEED_UPDATE_HOLD: active schedule plan not found")
        ScheduleTask.objects.update_or_create(
            plan=plan,
            name=RESIDUAL_NAME,
            defaults={
                "start_date": project.start_date,
                "end_date": project.end_date,
                "weight_percent": RESIDUAL_WEIGHT,
                "sort_order": 4,
                "is_active": True,
            },
        )
        as_of_date = DailyProgress.objects.filter(project=project).order_by("-report_date", "-id").values_list("report_date", flat=True).first()
        if as_of_date is None:
            raise RuntimeError("SEED_UPDATE_HOLD: no pilot progress row")
        latest_by_task = _latest_progress_by_task(plan, as_of_date)
        weighted_progress = sum(
            (Decimal(task.weight_percent or 0) * latest_by_task.get(task.id, Decimal("0"))) / Decimal("100")
            for task in ScheduleTask.objects.filter(plan=plan, is_active=True)
        )
        snapshot = ContractSnapshot.objects.filter(project=project, is_active=True).order_by("-version_no").first()
        if snapshot is None:
            raise RuntimeError("SEED_UPDATE_HOLD: active contract snapshot not found")
        revenue, _created = RevenueRecognition.objects.get_or_create(
            project=project,
            contract_snapshot=snapshot,
            as_of_date=as_of_date,
            defaults={"progress_percent": weighted_progress, "recognized_revenue": Decimal("0")},
        )
        revenue.progress_percent = weighted_progress
        revenue.save()
    after = _snapshot(project)
    recognized = Decimal(revenue.recognized_revenue or 0).quantize(Decimal("0.01"))
    profit = (recognized - after["cost_total"]).quantize(Decimal("0.01"))
    margin = (profit / recognized * Decimal("100")).quantize(Decimal("0.01")) if recognized else Decimal("0")
    return {
        "project_id": project.id,
        "contract_amount": str(snapshot.total_contract_amount),
        "budget_before": str(before["budget_total"]),
        "budget_after": str(after["budget_total"]),
        "wbs_before": str(before["wbs_total"]),
        "wbs_after": str(after["wbs_total"]),
        "task_weight_before": str(before["task_total"]),
        "task_weight_after": str(after["task_total"]),
        "revenue_before": str(before["recognized_revenue"]),
        "revenue_after": str(recognized),
        "weighted_progress": str(weighted_progress),
        "cost_total": str(after["cost_total"]),
        "profit_after": str(profit),
        "margin_after": str(margin),
    }


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--apply", action="store_true")
    args = parser.parse_args()
    _assert_local_demo_database()
    project = _project()
    if not args.apply:
        print(f"DRY_RUN: project_id={project.id} code={project.code}")
        print(_snapshot(project))
        return
    result = _apply()
    print("SEED_UPDATE_PASS")
    for key, value in result.items():
        print(f"{key}={value}")


if __name__ == "__main__":
    main()
