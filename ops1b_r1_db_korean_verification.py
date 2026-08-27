import json
import os
from pathlib import Path

os.environ.setdefault("DJANGO_SETTINGS_MODULE", "config.settings.local")

import django

django.setup()

from apps.projects.models import BudgetItem, Project, WBSItem
from apps.schedule.models import SchedulePlan, ScheduleTask


PROJECT_CODE = "OPS1B-RERUN-SAMPLE-001"

project = Project.objects.get(code=PROJECT_CODE)

budget_rows = [
    {"id": row.id, "name": row.name, "planned_amount": str(row.planned_amount)}
    for row in BudgetItem.objects.filter(project=project).order_by("id")
]
wbs_rows = [
    {"id": row.id, "name": row.name, "weight": str(row.weight)}
    for row in WBSItem.objects.filter(project=project).order_by("sort_order", "id")
]
task_rows = [
    {"id": task.id, "name": task.name, "weight_percent": str(task.weight_percent)}
    for plan in SchedulePlan.objects.filter(project=project).order_by("id")
    for task in ScheduleTask.objects.filter(plan=plan).order_by("sort_order", "id")
]

payload = {
    "project_code": project.code,
    "project_name": project.name,
    "budget_rows": budget_rows,
    "wbs_rows": wbs_rows,
    "task_rows": task_rows,
}

Path("ops1b_r1_db_korean_verification.json").write_text(
    json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8"
)
print("DB_KOREAN_VERIFICATION_WRITTEN=ops1b_r1_db_korean_verification.json")
