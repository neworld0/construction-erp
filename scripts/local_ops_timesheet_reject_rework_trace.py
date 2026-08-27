"""Write a read-only workflow snapshot for local timesheet rework checks."""

import csv
import os
import sys
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
os.environ.setdefault("DJANGO_SETTINGS_MODULE", "config.settings.local")

import django

django.setup()

from apps.labor.models import Timesheet
from apps.labor.services import get_timesheet_workflow_state


OUTPUT = ROOT / "timesheet_reject_rework_state_button_snapshot.csv"


def main():
    fields = [
        "Timesheet_ID", "Status", "Expected_Status", "FIELD_Can_Edit_Expected",
        "FIELD_Can_Edit_Actual", "FIELD_Can_Resubmit_Expected",
        "FIELD_Can_Resubmit_Actual", "HQ_Can_Review_Expected", "HQ_Can_Review_Actual",
        "Rejection_Reason_Visible", "Edit_Button_Rendered", "Save_Button_Rendered",
        "Resubmit_Button_Rendered", "Missing_Reason", "Fix_Target",
    ]
    timesheet = Timesheet.objects.select_related("project", "created_by").filter(id=3).first()
    with OUTPUT.open("w", encoding="utf-8-sig", newline="") as output:
        writer = csv.DictWriter(output, fieldnames=fields)
        writer.writeheader()
        if timesheet is None:
            print("TIMESHEET_ID_3_NOT_FOUND")
            return
        state = get_timesheet_workflow_state(timesheet, user=timesheet.created_by)
        is_rejected = state["is_rejected"]
        writer.writerow(
            {
                "Timesheet_ID": timesheet.id,
                "Status": timesheet.status,
                "Expected_Status": "REJECTED" if is_rejected else timesheet.status,
                "FIELD_Can_Edit_Expected": is_rejected and not state["is_closed_blocked"],
                "FIELD_Can_Edit_Actual": state["can_field_edit"],
                "FIELD_Can_Resubmit_Expected": is_rejected and not state["is_closed_blocked"],
                "FIELD_Can_Resubmit_Actual": state["can_field_resubmit"],
                "HQ_Can_Review_Expected": timesheet.status == "SUBMITTED",
                "HQ_Can_Review_Actual": state["can_hq_review"],
                "Rejection_Reason_Visible": bool(state["rejection_reason"]),
                "Edit_Button_Rendered": state["can_field_edit"],
                "Save_Button_Rendered": state["can_field_save"],
                "Resubmit_Button_Rendered": state["can_field_resubmit"],
                "Missing_Reason": "",
                "Fix_Target": "apps/labor/services.py + FIELD timesheet template",
            }
        )
    print(f"TIMESHEET_REWORK_SNAPSHOT={OUTPUT.name}")


if __name__ == "__main__":
    main()
