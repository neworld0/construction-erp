from datetime import date
from decimal import Decimal

from django.utils import timezone

from apps.schedule.models import DailyProgress, SchedulePlan, ScheduleTask


def get_task_progress(plan_id, as_of_date):
    if as_of_date is None:
        as_of_date = timezone.localdate()

    tasks = ScheduleTask.objects.filter(plan_id=plan_id, is_active=True).order_by("id")
    progress_rows = (
        DailyProgress.objects.filter(plan_id=plan_id, report_date__lte=as_of_date)
        .order_by("-report_date", "-id")
        .values("task_id", "progress_percent")
    )
    latest_by_task = {}
    for row in progress_rows:
        task_id = row["task_id"]
        if task_id not in latest_by_task:
            latest_by_task[task_id] = row["progress_percent"]

    result = []
    for task in tasks:
        result.append(
            {
                "task_id": task.id,
                "name": task.name,
                "weight_percent": task.weight_percent,
                "latest_progress_percent": latest_by_task.get(task.id, Decimal("0")),
            }
        )
    return result


def get_project_progress(project_id, as_of_date=None):
    if as_of_date is None:
        as_of_date = timezone.localdate()

    plan = SchedulePlan.objects.filter(project_id=project_id, is_active=True).first()
    if plan is None:
        return {
            "project_id": project_id,
            "plan_id": None,
            "plan_version_no": None,
            "as_of_date": as_of_date,
            "overall_progress_percent": Decimal("0"),
            "tasks": [],
        }

    tasks = get_task_progress(plan.id, as_of_date)
    total = Decimal("0")
    for task in tasks:
        weight = task["weight_percent"] or Decimal("0")
        progress = task["latest_progress_percent"] or Decimal("0")
        total += (weight * progress) / Decimal("100")

    return {
        "project_id": project_id,
        "plan_id": plan.id,
        "plan_version_no": plan.version_no,
        "as_of_date": as_of_date,
        "overall_progress_percent": total,
        "tasks": tasks,
    }
