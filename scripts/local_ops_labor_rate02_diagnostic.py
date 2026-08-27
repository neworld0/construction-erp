"""Write read-only HQ labor-rate and rate-resolution diagnostics."""

import csv
import os
import sys
from datetime import date
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
os.environ.setdefault("DJANGO_SETTINGS_MODULE", "config.settings.local")

import django

django.setup()

from apps.labor.models import LaborRateTable, LaborRateType, WorkerMaster
from apps.labor.rate_master import LOCAL_OPS_LABOR_RATE_SPECS
from apps.labor.services import get_rate_scope, resolve_labor_rate


RATE_OUTPUT = ROOT / "labor_rate02_rate_master_snapshot.csv"
RESOLUTION_OUTPUT = ROOT / "labor_rate02_rate_resolution_snapshot.csv"
CHECK_DATE = date(2026, 8, 14)
PRIORITY = {
    "PROJECT_WORKER": 100,
    "PROJECT_ROLE": 80,
    "WORKER": 60,
    "ROLE_BASE": 40,
}


def _has_overlap(rate):
    other_rates = LaborRateTable.objects.filter(
        labor_role=rate.labor_role,
        rate_type=rate.rate_type,
        scope_type=rate.scope_type,
        project_id=rate.project_id,
        worker_id=rate.worker_id,
        is_active=True,
    ).exclude(id=rate.id)
    if rate.effective_to:
        other_rates = other_rates.filter(effective_from__lte=rate.effective_to)
    return other_rates.filter(
        effective_to__isnull=True
    ).exists() or other_rates.filter(effective_to__gte=rate.effective_from).exists()


def write_rate_snapshot():
    required_codes = {code for code, _amount in LOCAL_OPS_LABOR_RATE_SPECS}
    fields = [
        "Rate_ID", "Scope", "Project_ID", "Project_Name", "Worker_ID", "Worker_Name",
        "LaborRole_Code", "LaborRole_Name", "Rate_Type", "Daily_Rate", "Hourly_Rate",
        "Effective_From", "Effective_To", "Is_Active", "Priority", "Conflict_Group",
        "Has_Overlap", "Required_For_LOCAL_OPS", "Notes",
    ]
    rates = LaborRateTable.objects.select_related("project", "worker", "labor_role").order_by("id")
    with RATE_OUTPUT.open("w", encoding="utf-8-sig", newline="") as output:
        writer = csv.DictWriter(output, fieldnames=fields)
        writer.writeheader()
        for rate in rates:
            scope = get_rate_scope(rate)
            writer.writerow({
                "Rate_ID": rate.id,
                "Scope": scope,
                "Project_ID": rate.project_id or "",
                "Project_Name": rate.project.name if rate.project_id else "",
                "Worker_ID": rate.worker_id or "",
                "Worker_Name": rate.worker.name if rate.worker_id else "",
                "LaborRole_Code": rate.labor_role.code,
                "LaborRole_Name": rate.labor_role.name,
                "Rate_Type": rate.rate_type,
                "Daily_Rate": rate.unit_rate if rate.rate_type == LaborRateType.DAY else "",
                "Hourly_Rate": rate.unit_rate if rate.rate_type == LaborRateType.HOUR else "",
                "Effective_From": rate.effective_from,
                "Effective_To": rate.effective_to or "",
                "Is_Active": rate.is_active,
                "Priority": PRIORITY[scope],
                "Conflict_Group": f"{rate.labor_role_id}:{rate.rate_type}:{scope}:{rate.project_id or ''}:{rate.worker_id or ''}",
                "Has_Overlap": _has_overlap(rate),
                "Required_For_LOCAL_OPS": rate.labor_role.code in required_codes,
                "Notes": rate.note,
            })


def write_resolution_snapshot():
    fields = [
        "Scenario", "Worker", "LaborRole", "Project", "Work_Date", "Rate_Type",
        "Expected_Priority", "Resolved_Rate_ID", "Resolved_Rate", "Resolved_Scope",
        "Missing", "Conflict", "Result",
    ]
    workers = WorkerMaster.objects.select_related("default_labor_role").filter(active=True)
    with RESOLUTION_OUTPUT.open("w", encoding="utf-8-sig", newline="") as output:
        writer = csv.DictWriter(output, fieldnames=fields)
        writer.writeheader()
        for worker in workers:
            role = worker.default_labor_role
            if not role:
                continue
            try:
                rate, scope = resolve_labor_rate(
                    worker=worker,
                    labor_role=role,
                    project=None,
                    work_date=CHECK_DATE,
                    rate_type=LaborRateType.DAY,
                )
                row = {
                    "Scenario": "활성 근로자 기본 단가 확인",
                    "Worker": worker.name,
                    "LaborRole": role.name,
                    "Project": "",
                    "Work_Date": CHECK_DATE,
                    "Rate_Type": LaborRateType.DAY,
                    "Expected_Priority": "WORKER 또는 ROLE_BASE",
                    "Resolved_Rate_ID": rate.id,
                    "Resolved_Rate": rate.unit_rate,
                    "Resolved_Scope": scope,
                    "Missing": False,
                    "Conflict": False,
                    "Result": "RATE_RESOLVED",
                }
            except Exception as exc:
                message = " ".join(getattr(exc, "messages", [str(exc)]))
                row = {
                    "Scenario": "활성 근로자 기본 단가 확인",
                    "Worker": worker.name,
                    "LaborRole": role.name,
                    "Project": "",
                    "Work_Date": CHECK_DATE,
                    "Rate_Type": LaborRateType.DAY,
                    "Expected_Priority": "WORKER 또는 ROLE_BASE",
                    "Resolved_Rate_ID": "",
                    "Resolved_Rate": "",
                    "Resolved_Scope": "",
                    "Missing": "등록되지 않았습니다" in message,
                    "Conflict": "중복 등록" in message,
                    "Result": message,
                }
            writer.writerow(row)


if __name__ == "__main__":
    write_rate_snapshot()
    write_resolution_snapshot()
    print(f"RATE_MASTER_SNAPSHOT={RATE_OUTPUT.name}")
    print(f"RATE_RESOLUTION_SNAPSHOT={RESOLUTION_OUTPUT.name}")
