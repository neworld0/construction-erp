"""Read-only FIELD timesheet worker-attendance diagnostic."""

import csv
import os
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
os.environ.setdefault("DJANGO_SETTINGS_MODULE", "config.settings.local")

import django

django.setup()

from apps.labor.models import TimesheetLine, WorkerMaster


def write_worker_snapshot():
    fields = [
        "Worker_ID",
        "Worker_Name_Masked_Or_Display",
        "Default_Labor_Role_Code",
        "Default_Labor_Role_Name",
        "Is_Active",
        "Visible_To_FIELD_Timesheet",
        "Project_Assigned",
        "Required_For_LOCAL_OPS",
        "Gap",
        "Notes",
    ]
    required_names = {"김로컬", "박포장", "이장비", "최다짐", "정도색"}
    with (ROOT / "field_timesheet_worker_worker_role_snapshot.csv").open(
        "w", encoding="utf-8-sig", newline=""
    ) as output:
        writer = csv.DictWriter(output, fieldnames=fields)
        writer.writeheader()
        for worker in WorkerMaster.objects.select_related("default_labor_role").order_by(
            "name", "id"
        ):
            role = worker.default_labor_role
            writer.writerow(
                {
                    "Worker_ID": worker.id,
                    "Worker_Name_Masked_Or_Display": worker.name,
                    "Default_Labor_Role_Code": role.code if role else "",
                    "Default_Labor_Role_Name": role.name if role else "",
                    "Is_Active": worker.active,
                    "Visible_To_FIELD_Timesheet": worker.active,
                    "Project_Assigned": "N/A (no worker-project assignment model)",
                    "Required_For_LOCAL_OPS": worker.name in required_names,
                    "Gap": "MISSING_DEFAULT_ROLE" if worker.active and role is None else "",
                    "Notes": "No resident number, phone, or account data exported.",
                }
            )


def write_model_snapshot():
    fields = [
        "Model",
        "Has_Project",
        "Has_Work_Date",
        "Has_WBS",
        "Has_WorkerMaster_FK",
        "Has_LaborRole_FK",
        "Has_Headcount",
        "Has_Hours",
        "Has_Rate_Type",
        "Has_Memo",
        "Suitable_For_Worker_Level_Attendance",
        "Notes",
    ]
    rows = [
        {
            "Model": "TimesheetLine",
            "Has_Project": "Via Timesheet",
            "Has_Work_Date": "Via Timesheet",
            "Has_WBS": "No",
            "Has_WorkerMaster_FK": "Yes",
            "Has_LaborRole_FK": "Yes",
            "Has_Headcount": "Yes (work unit)",
            "Has_Hours": "Yes",
            "Has_Rate_Type": "Yes",
            "Has_Memo": "Yes",
            "Suitable_For_Worker_Level_Attendance": "Yes",
            "Notes": "Canonical FIELD attendance source before HQ confirmation.",
        },
        {
            "Model": "LaborWorkLedger",
            "Has_Project": "Yes",
            "Has_Work_Date": "Yes",
            "Has_WBS": "No",
            "Has_WorkerMaster_FK": "Yes",
            "Has_LaborRole_FK": "Yes",
            "Has_Headcount": "Yes (work unit)",
            "Has_Hours": "Yes",
            "Has_Rate_Type": "No",
            "Has_Memo": "Yes",
            "Suitable_For_Worker_Level_Attendance": "No",
            "Notes": "HQ ledger and reconciliation source; FIELD does not write it directly.",
        },
    ]
    with (ROOT / "field_timesheet_worker_timesheet_model_snapshot.csv").open(
        "w", encoding="utf-8-sig", newline=""
    ) as output:
        writer = csv.DictWriter(output, fieldnames=fields)
        writer.writeheader()
        writer.writerows(rows)


if __name__ == "__main__":
    write_worker_snapshot()
    write_model_snapshot()
    print(f"WORKER_LEVEL_TIMESHEET_LINE_COUNT={TimesheetLine.objects.filter(worker__isnull=False).count()}")
    print("WORKER_SNAPSHOT=field_timesheet_worker_worker_role_snapshot.csv")
    print("MODEL_SNAPSHOT=field_timesheet_worker_timesheet_model_snapshot.csv")
