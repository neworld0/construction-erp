"""Write read-only LOCAL-OPS LaborRole and timesheet rate diagnostics."""

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

from apps.labor.models import LaborRateTable, LaborRole, TimesheetLine
from apps.labor.rate_master import LOCAL_OPS_LABOR_RATE_SPECS
from apps.labor.services import get_applicable_rate


ROLE_OUTPUT = ROOT / "labor_rate_master_role_rate_snapshot.csv"
TIMESHEET_OUTPUT = ROOT / "labor_rate_master_timesheet_rate_resolution_snapshot.csv"
CHECK_DATES = (date(2026, 8, 14), date(2026, 8, 31))


def write_role_snapshot():
    required_codes = {code for code, _amount in LOCAL_OPS_LABOR_RATE_SPECS}
    fields = [
        "LaborRole_ID",
        "LaborRole_Code",
        "LaborRole_Name",
        "Is_Active",
        "Required_For_LOCAL_OPS",
        "Rate_Model",
        "Rate_ID",
        "Rate_Type",
        "Effective_From",
        "Effective_To",
        "Daily_Rate",
        "Hourly_Rate",
        "Project_Specific",
        "Rate_Resolved_For_2026_08_14",
        "Rate_Resolved_For_2026_08_31",
        "Gap",
        "Notes",
    ]
    with ROLE_OUTPUT.open("w", encoding="utf-8-sig", newline="") as output:
        writer = csv.DictWriter(output, fieldnames=fields)
        writer.writeheader()
        for role in LaborRole.objects.order_by("sort_order", "code"):
            rates = list(role.rates.order_by("-effective_from", "id"))
            rate = rates[0] if rates else None
            resolved = [get_applicable_rate(None, role, check_date) for check_date in CHECK_DATES]
            writer.writerow(
                {
                    "LaborRole_ID": role.id,
                    "LaborRole_Code": role.code,
                    "LaborRole_Name": role.name,
                    "Is_Active": role.is_active,
                    "Required_For_LOCAL_OPS": role.code in required_codes,
                    "Rate_Model": "LaborRateTable",
                    "Rate_ID": rate.id if rate else "",
                    "Rate_Type": rate.rate_type if rate else "",
                    "Effective_From": rate.effective_from if rate else "",
                    "Effective_To": rate.effective_to if rate else "",
                    "Daily_Rate": rate.unit_rate if rate and rate.rate_type == "DAY" else "",
                    "Hourly_Rate": rate.unit_rate if rate and rate.rate_type == "HOUR" else "",
                    "Project_Specific": bool(rate and rate.project_id),
                    "Rate_Resolved_For_2026_08_14": resolved[0].unit_rate if resolved[0] else "",
                    "Rate_Resolved_For_2026_08_31": resolved[1].unit_rate if resolved[1] else "",
                    "Gap": "MISSING_RATE" if role.code in required_codes and not all(resolved) else "",
                    "Notes": "주민등록번호, 연락처, 계좌번호는 포함하지 않습니다.",
                }
            )


def write_timesheet_snapshot():
    fields = [
        "Timesheet_ID",
        "Timesheet_Date",
        "Worker",
        "LaborRole",
        "Rate_Type",
        "Expected_Rate",
        "Resolved_Rate",
        "Missing_Rate",
        "Submit_Blocked",
        "Error_Message",
        "Result",
    ]
    lines = TimesheetLine.objects.select_related(
        "timesheet__project", "worker", "labor_role"
    ).order_by("timesheet__work_date", "id")
    with TIMESHEET_OUTPUT.open("w", encoding="utf-8-sig", newline="") as output:
        writer = csv.DictWriter(output, fieldnames=fields)
        writer.writeheader()
        for line in lines:
            rate = get_applicable_rate(
                line.timesheet.project,
                line.labor_role,
                line.timesheet.work_date,
                rate_type=line.rate_type,
            )
            missing = rate is None
            writer.writerow(
                {
                    "Timesheet_ID": line.timesheet_id,
                    "Timesheet_Date": line.timesheet.work_date,
                    "Worker": line.worker.name if line.worker_id else "집계 입력",
                    "LaborRole": line.labor_role.name,
                    "Rate_Type": line.rate_type,
                    "Expected_Rate": line.unit_rate or "",
                    "Resolved_Rate": rate.unit_rate if rate else "",
                    "Missing_Rate": missing,
                    "Submit_Blocked": missing,
                    "Error_Message": (
                        f"{line.labor_role.name} 단가가 등록되지 않았습니다. "
                        "HQ에서 노무 역할 단가를 먼저 등록해 주세요."
                        if missing
                        else ""
                    ),
                    "Result": "RATE_RESOLVED" if rate else "MISSING_RATE",
                }
            )


if __name__ == "__main__":
    write_role_snapshot()
    write_timesheet_snapshot()
    print(f"RATE_ROW_COUNT={LaborRateTable.objects.count()}")
    print(f"ROLE_SNAPSHOT={ROLE_OUTPUT.name}")
    print(f"TIMESHEET_SNAPSHOT={TIMESHEET_OUTPUT.name}")
