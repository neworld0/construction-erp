"""Create or verify a sanitized OPS-1B rehearsal dataset in the local demo DB.

Run with: python ops1b_rerun_seed_script.py --apply
The script refuses any database other than a loopback PostgreSQL database
whose name includes 'demo'. It never creates a WorkerMaster or uploads files.
"""

from __future__ import annotations

import argparse
import os
from datetime import date
from decimal import Decimal

os.environ.setdefault("DJANGO_SETTINGS_MODULE", "config.settings.local")

import django

django.setup()

from django.conf import settings
from django.contrib.auth import get_user_model
from django.db import transaction
from django.test import Client
from django.utils import timezone

from apps.audit.models import AuditLog
from apps.contracts.models import ContractSnapshot
from apps.core.rbac.models import ProjectAssignment, Role, UserProfile
from apps.cost.models import CostActual, CostActualLine, CostActualStatus, CostItem, CostItemCategory, RevenueRecognition
from apps.projects.models import BudgetCategory, BudgetItem, Project, ProjectContract, ProjectStatus, WBSItem
from apps.schedule.models import DailyProgress, SchedulePlan, ScheduleTask


PROJECT_CODE = "OPS1B-RERUN-SAMPLE-001"
PROJECT_NAME = "국도 유지보수 파일럿 공사"
CONTRACT_AMOUNT = Decimal("571022700")
BUDGET_TOTAL = Decimal("390000000")
COST_TOTAL = Decimal("10000000")
TASK_PROGRESS = Decimal("12.5")

ITEMS = (
    ("OPS1B-EARTHWORK", "토공", CostItemCategory.OTHER, BudgetCategory.OTHER, "WBS-01", 20, 50000000),
    ("OPS1B-PAVING", "포장공사", CostItemCategory.MATERIAL, BudgetCategory.MATERIAL, "WBS-02", 45, 250000000),
    ("OPS1B-DRAINAGE", "배수공사", CostItemCategory.OTHER, BudgetCategory.OTHER, "WBS-03", 20, 90000000),
)


def _assert_local_demo_database() -> None:
    database = settings.DATABASES["default"]
    engine = str(database.get("ENGINE", ""))
    name = str(database.get("NAME", "")).lower()
    host = str(database.get("HOST", "")).lower()
    if not (engine.endswith("postgresql") and "demo" in name and host in {"127.0.0.1", "localhost"}):
        raise SystemExit("Refusing to write: OPS-1B rehearsal requires the local demo PostgreSQL database.")


def _require_user(username: str, role: str):
    user = get_user_model().objects.filter(username=username).first()
    if user is None:
        raise SystemExit(f"Required local rehearsal user is missing: {username}")
    profile, _created = UserProfile.objects.get_or_create(user=user, defaults={"role": role})
    if profile.role != role:
        raise SystemExit(f"Required user {username} does not have role {role}")
    return user


def _ensure_cost_item(code: str, name: str, category: str) -> CostItem:
    item, _created = CostItem.objects.get_or_create(
        code=code,
        defaults={
            "name": name,
            "category": category,
            "cost_type": "M" if category == CostItemCategory.MATERIAL else "E",
            "work_type": "99",
            "is_direct": True,
            "is_active": True,
        },
    )
    return item


def _seed() -> dict[str, object]:
    _assert_local_demo_database()
    hq = _require_user("hq", Role.HQ)
    field = _require_user("field1", Role.FIELD)
    today = timezone.localdate()
    if "testserver" not in settings.ALLOWED_HOSTS:
        settings.ALLOWED_HOSTS = [*settings.ALLOWED_HOSTS, "testserver"]
    settings.MIDDLEWARE = [
        middleware
        for middleware in settings.MIDDLEWARE
        if middleware != "apps.core.middleware.two_factor_enforce.TwoFactorEnforceMiddleware"
    ]

    with transaction.atomic():
        project, _created = Project.objects.get_or_create(
            code=PROJECT_CODE,
            defaults={
                "name": PROJECT_NAME,
                "project_type": "civil",
                "client_name": "발주처-비식별",
                "site_address": "현장주소-비식별",
                "contract_amount": CONTRACT_AMOUNT,
                "start_date": date(2026, 1, 1),
                "end_date": date(2026, 12, 31),
                "status": ProjectStatus.ACTIVE,
                "is_active": True,
            },
        )
        ProjectAssignment.objects.update_or_create(user=field, project=project, defaults={"is_active": True})
        ProjectContract.objects.update_or_create(
            project=project,
            defaults={
                "contract_amount": CONTRACT_AMOUNT,
                "start_date": project.start_date,
                "end_date": project.end_date,
                "contract_start_date": project.start_date,
                "contract_end_date": project.end_date,
                "status": "approved",
                "memo": "OPS-1B-RERUN 비식별 계약 기준선",
            },
        )
        snapshot, _created = ContractSnapshot.objects.get_or_create(
            project=project,
            version_no=1,
            defaults={
                "base_contract_amount": CONTRACT_AMOUNT,
                "start_date": project.start_date,
                "end_date": project.end_date,
                "is_active": True,
            },
        )

        wbs_by_code = {}
        for order, (code, name, category, budget_category, wbs_code, weight, amount) in enumerate(ITEMS, start=1):
            cost_item = _ensure_cost_item(code, name, category)
            BudgetItem.objects.update_or_create(
                project=project,
                cost_item=cost_item,
                name=f"{name} 예산",
                defaults={
                    "category": budget_category,
                    "planned_amount": amount,
                    "status": "approved",
                    "note": f"OPS-1B-RERUN 비식별 예산 / {wbs_code}",
                },
            )
            wbs, _created = WBSItem.objects.get_or_create(
                project=project,
                name=name,
                defaults={
                    "weight": Decimal(str(weight)),
                    "sort_order": order,
                    "plan_start_date": project.start_date,
                    "plan_end_date": project.end_date,
                    "is_baseline": True,
                },
            )
            wbs_by_code[wbs_code] = wbs

        plan, _created = SchedulePlan.objects.get_or_create(
            project=project,
            version_no=1,
            defaults={"name": "OPS-1B-RERUN 기준선", "is_active": True, "created_by": hq},
        )
        task_by_name = {}
        for order, (_code, name, _category, _budget_category, _wbs_code, weight, _amount) in enumerate(ITEMS, start=1):
            task, _created = ScheduleTask.objects.get_or_create(
                plan=plan,
                name=name,
                defaults={
                    "start_date": project.start_date,
                    "end_date": project.end_date,
                    "weight_percent": Decimal(str(weight)),
                    "sort_order": order,
                    "is_active": True,
                },
            )
            task_by_name[name] = task

        paving = CostItem.objects.get(code="OPS1B-PAVING")
        cost, _created = CostActual.objects.get_or_create(
            project=project,
            report_date=today,
            defaults={"status": CostActualStatus.APPROVED, "total_amount": Decimal("0")},
        )
        if cost.status != CostActualStatus.APPROVED:
            cost.status = CostActualStatus.APPROVED
            cost.save(update_fields=["status", "updated_at"])
        CostActualLine.objects.update_or_create(
            cost_actual=cost,
            cost_item=paving,
            description="OPS-1B-RERUN 비식별 원가",
            defaults={"quantity": Decimal("1"), "unit_price": COST_TOTAL},
        )
        cost.refresh_from_db()
        revenue, _created = RevenueRecognition.objects.get_or_create(
            project=project,
            contract_snapshot=snapshot,
            as_of_date=today,
            defaults={"progress_percent": TASK_PROGRESS, "recognized_revenue": Decimal("0")},
        )
        if revenue.progress_percent != TASK_PROGRESS:
            revenue.progress_percent = TASK_PROGRESS
            revenue.save()

    client = Client()
    client.force_login(field)
    progress_url = f"/app/field/?tab=progress&project_id={project.id}"
    get_response = client.get(progress_url)
    if get_response.status_code != 200:
        raise RuntimeError(f"FIELD progress screen failed: {get_response.status_code}")
    task = task_by_name["포장공사"]
    progress = DailyProgress.objects.filter(
        project=project, task=task, report_date=today, reporter=field
    ).first()
    if progress is None:
        draft_response = client.post(
            "/app/field/",
            {
                "tab": "progress",
                "project_id": str(project.id),
                "action": "draft",
                "task_id": str(task.id),
                "report_date": today.isoformat(),
                "progress_percent": str(TASK_PROGRESS),
                "note": "OPS-1B-RERUN 현장 진행률 입력 리허설",
            },
        )
        if draft_response.status_code != 302:
            raise RuntimeError(f"FIELD progress draft failed: {draft_response.status_code}")
        progress = DailyProgress.objects.get(project=project, task=task, report_date=today, reporter=field)
        submit_response = client.post(
            "/app/field/",
            {"tab": "progress", "project_id": str(project.id), "action": "submit", "progress_id": str(progress.id)},
        )
        if submit_response.status_code != 302:
            raise RuntimeError(f"FIELD progress submit failed: {submit_response.status_code}")
    progress.refresh_from_db()

    ceo = _require_user("ceo", Role.CEO)
    ceo_client = Client()
    ceo_client.force_login(ceo)
    dashboard_response = ceo_client.get(f"/app/ceo/?as_of_date={today.isoformat()}")
    if dashboard_response.status_code != 200:
        raise RuntimeError(f"CEO dashboard failed: {dashboard_response.status_code}")
    budget_total = sum(project.budget_items.values_list("planned_amount", flat=True))
    return {
        "project_id": project.id,
        "project_code": project.code,
        "budget_total": str(budget_total),
        "contract_amount": str(CONTRACT_AMOUNT),
        "contract_budget_difference": str(CONTRACT_AMOUNT - Decimal(budget_total)),
        "submitted_progress": str(progress.progress_percent),
        "cost_total": str(cost.total_amount),
        "recognized_revenue": str(revenue.recognized_revenue),
        "progress_audit_log_count": AuditLog.objects.filter(object_type="DAILY_PROGRESS", object_id=progress.id).count(),
        "dashboard_status": dashboard_response.status_code,
    }


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--apply", action="store_true", help="write only to the guarded local demo database")
    args = parser.parse_args()
    _assert_local_demo_database()
    if not args.apply:
        print("DRY_RUN: local demo DB guard passed; run with --apply to create the sanitized rehearsal dataset.")
        return
    result = _seed()
    print("SEED_APPLY_PASS")
    for key, value in result.items():
        print(f"{key}={value}")


if __name__ == "__main__":
    main()
