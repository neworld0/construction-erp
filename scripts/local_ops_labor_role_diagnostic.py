"""Read-only LOCAL-OPS LaborRole and worker-form visibility diagnostic."""

import csv
import os
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
os.environ.setdefault("DJANGO_SETTINGS_MODULE", "config.settings.local")

import django

django.setup()

from apps.labor.models import LaborRole
from apps.labor.role_master import LOCAL_OPS_LABOR_ROLE_SPECS


REQUIRED_CODES = {spec[0] for spec in LOCAL_OPS_LABOR_ROLE_SPECS}


def write_snapshot():
    rows = []
    for role in LaborRole.objects.order_by("sort_order", "code"):
        required = role.code in REQUIRED_CODES
        rows.append(
            {
                "LaborRole_ID": role.id,
                "Code": role.code,
                "Name": role.name,
                "Category": role.role_group,
                "Is_Active": role.is_active,
                "Sort_Order": role.sort_order,
                "Has_Default_Rate": role.rates.filter(is_active=True).exists(),
                "Used_By_Worker_Count": role.worker_masters.count(),
                "Visible_In_Worker_Form": role.is_active,
                "Required_For_LOCAL_OPS": required,
                "Gap": "" if not required or role.is_active else "INACTIVE",
                "Notes": "",
            }
        )

    for code, name, _role_group, _sort_order in LOCAL_OPS_LABOR_ROLE_SPECS:
        if not any(row["Code"] == code for row in rows):
            rows.append(
                {
                    "LaborRole_ID": "",
                    "Code": code,
                    "Name": name,
                    "Category": "",
                    "Is_Active": False,
                    "Sort_Order": "",
                    "Has_Default_Rate": False,
                    "Used_By_Worker_Count": 0,
                    "Visible_In_Worker_Form": False,
                    "Required_For_LOCAL_OPS": True,
                    "Gap": "MISSING",
                    "Notes": "Run seed_labor_roles.",
                }
            )

    fields = list(rows[0]) if rows else []
    with (ROOT / "labor_role_master_role_snapshot.csv").open(
        "w", encoding="utf-8-sig", newline=""
    ) as output:
        writer = csv.DictWriter(output, fieldnames=fields)
        writer.writeheader()
        writer.writerows(rows)

    with (ROOT / "labor_role_master_worker_form_dropdown_snapshot.csv").open(
        "w", encoding="utf-8-sig", newline=""
    ) as output:
        writer = csv.DictWriter(
            output,
            fieldnames=["URL", "Role_Code", "Role_Name", "Rendered_In_Dropdown", "Selected_Allowed", "Notes"],
        )
        writer.writeheader()
        for role in LaborRole.objects.filter(is_active=True).order_by("sort_order", "code"):
            writer.writerow(
                {
                    "URL": "/app/hq/labor/workers/new/",
                    "Role_Code": role.code,
                    "Role_Name": role.name,
                    "Rendered_In_Dropdown": "YES",
                    "Selected_Allowed": "YES",
                    "Notes": "Active LaborRole",
                }
            )
    return rows


if __name__ == "__main__":
    snapshot = write_snapshot()
    print(f"LABOR_ROLE_COUNT={len(snapshot)}")
    print("ROLE_SNAPSHOT=labor_role_master_role_snapshot.csv")
    print("DROPDOWN_SNAPSHOT=labor_role_master_worker_form_dropdown_snapshot.csv")
