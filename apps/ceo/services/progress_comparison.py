from __future__ import annotations

from datetime import date
from decimal import Decimal

from apps.schedule.models import DailyProgress, SchedulePlan, ScheduleTask


def _planned_task_percent(task, as_of_date: date):
    if not task.start_date or not task.end_date or task.end_date < task.start_date:
        return None
    if as_of_date < task.start_date:
        return Decimal("0")
    if as_of_date >= task.end_date:
        return Decimal("100")
    days = (task.end_date - task.start_date).days
    if not days:
        return Decimal("100")
    return Decimal((as_of_date - task.start_date).days) * Decimal("100") / Decimal(days)


def _latest_approved_by_task(project, task_ids, as_of_date):
    values = {}
    for row in (
        DailyProgress.objects.filter(project=project, task_id__in=task_ids, status="approved", report_date__lte=as_of_date)
        .order_by("task_id", "-report_date", "-id")
        .values("task_id", "progress_percent")
    ):
        values.setdefault(row["task_id"], row["progress_percent"] or Decimal("0"))
    return values


def _progress_pair(project, as_of_date):
    plan = SchedulePlan.objects.filter(project=project, is_active=True).first()
    if plan is None:
        return None, Decimal("0"), "기준선 없음"
    tasks = list(ScheduleTask.objects.filter(plan=plan, is_active=True))
    if not tasks or any(_planned_task_percent(task, as_of_date) is None for task in tasks):
        actual = _weighted_actual(project, tasks, as_of_date)
        return None, actual, "기준선 미완성"
    planned = sum(((task.weight_percent or Decimal("0")) * _planned_task_percent(task, as_of_date)) / Decimal("100") for task in tasks)
    return planned, _weighted_actual(project, tasks, as_of_date), "비교 가능"


def _weighted_actual(project, tasks, as_of_date):
    latest = _latest_approved_by_task(project, [task.id for task in tasks], as_of_date)
    return sum(((task.weight_percent or Decimal("0")) * latest.get(task.id, Decimal("0"))) / Decimal("100") for task in tasks)


def build_portfolio_progress_comparison(projects, as_of_date: date):
    rows = []
    for project in projects:
        planned, actual, basis_status = _progress_pair(project, as_of_date)
        rows.append({
            "project_id": project.id,
            "project_name": project.name,
            "planned_progress_percent": planned,
            "actual_progress_percent": actual,
            "gap_percent": (actual - planned) if planned is not None else None,
            "basis_status": basis_status,
        })
    return rows


def build_project_progress_timeline(project, as_of_date: date):
    plan = SchedulePlan.objects.filter(project=project, is_active=True).first()
    if plan is None:
        return {"labels": [], "planned": [], "actual": [], "basis_status": "기준선 없음"}
    tasks = list(ScheduleTask.objects.filter(plan=plan, is_active=True))
    dates = {as_of_date}
    for task in tasks:
        if task.start_date:
            dates.add(task.start_date)
        if task.end_date:
            dates.add(task.end_date)
    dates.update(DailyProgress.objects.filter(project=project, plan=plan, status="approved", report_date__lte=as_of_date).values_list("report_date", flat=True))
    labels, planned_values, actual_values = [], [], []
    for point in sorted(value for value in dates if value <= as_of_date):
        planned, actual, _status = _progress_pair(project, point)
        labels.append(point.isoformat())
        planned_values.append(float(planned) if planned is not None else None)
        actual_values.append(float(actual))
    basis_status = "비교 가능" if tasks and all(_planned_task_percent(task, as_of_date) is not None for task in tasks) else "기준선 미완성"
    return {"labels": labels, "planned": planned_values, "actual": actual_values, "basis_status": basis_status}
