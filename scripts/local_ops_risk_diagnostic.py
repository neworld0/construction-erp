"""Read-only local/demo diagnostic for CEO dashboard risk visibility."""

from __future__ import annotations

import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from local_ops_reset_project_data import ARTIFACT, db_guard, setup_django, write_csv


def classify_finding(finding, existing_project_ids):
    object_type = str(finding.object_type or "").upper()
    project_exists = finding.project_id in existing_project_ids if finding.project_id else False
    object_exists = finding.object_id in existing_project_ids if object_type == "PROJECT" else None
    is_project_scoped = bool(finding.project_id) or object_type == "PROJECT"
    if finding.status != "open":
        classification = "CLOSED_RISK"
        show_on_dashboard = False
        action = "PRESERVE"
        reason = "Open-risk summary excludes closed or acknowledged findings."
    elif finding.project_id and project_exists and finding.project.is_active:
        classification = "VALID_PROJECT_RISK"
        show_on_dashboard = True
        action = "PRESERVE"
        reason = "Linked to an active project."
    elif object_type == "PROJECT" and not object_exists:
        classification = "ORPHAN_PROJECT_RISK"
        show_on_dashboard = False
        action = "DELETE_LOCAL_RESET"
        reason = "PROJECT generic reference no longer exists."
    else:
        classification = "PROJECTLESS_NON_SYSTEM_RISK"
        show_on_dashboard = False
        action = "PRESERVE_AND_EXCLUDE_FROM_PROJECT_SUMMARY"
        reason = "No global/system scope exists on RiskFinding."
    return {
        "classification": classification,
        "project_exists": project_exists,
        "object_exists": object_exists,
        "is_project_scoped": is_project_scoped,
        "is_orphan": classification == "ORPHAN_PROJECT_RISK",
        "is_global_system": False,
        "show_on_dashboard": show_on_dashboard,
        "action": action,
        "reason": reason,
    }


def main():
    setup_django()
    from django.conf import settings
    from apps.projects.models import Project
    from apps.risk.models import RiskFinding, RiskFindingStatus

    guard = db_guard(settings)
    if not guard["passed"]:
        raise RuntimeError("LOCAL/DEMO database guard blocked risk diagnostic")

    projects = list(Project.objects.order_by("id"))
    existing_project_ids = {project.id for project in projects}
    active_project_ids = {project.id for project in projects if project.is_active}
    findings = list(RiskFinding.objects.select_related("project").order_by("id"))
    rows = []
    for finding in findings:
        result = classify_finding(finding, existing_project_ids)
        rows.append({
            "RiskFinding_ID": finding.id,
            "Status": finding.status,
            "Severity": finding.severity,
            "Title": finding.title,
            "Project_ID": finding.project_id or "",
            "Project_Exists": "YES" if result["project_exists"] else "NO",
            "Project_Code": finding.project.code if result["project_exists"] else "",
            "Project_Name": finding.project.name if result["project_exists"] else "",
            "Object_Type": finding.object_type,
            "Object_ID": finding.object_id,
            "Object_Exists_If_Resolvable": (
                "YES" if result["object_exists"] else "NO" if result["object_exists"] is not None else "-"
            ),
            "Classification": result["classification"],
            "Is_Project_Scoped": "YES" if result["is_project_scoped"] else "NO",
            "Is_Orphan": "YES" if result["is_orphan"] else "NO",
            "Is_Global_System": "YES" if result["is_global_system"] else "NO",
            "Should_Show_On_CEO_Dashboard": "YES" if result["show_on_dashboard"] else "NO",
            "Recommended_Action": result["action"],
            "Reason": result["reason"],
        })

    headers = list(rows[0].keys()) if rows else [
        "RiskFinding_ID", "Status", "Severity", "Title", "Project_ID", "Project_Exists",
        "Project_Code", "Project_Name", "Object_Type", "Object_ID",
        "Object_Exists_If_Resolvable", "Is_Project_Scoped", "Is_Orphan",
        "Is_Global_System", "Should_Show_On_CEO_Dashboard", "Recommended_Action", "Reason",
    ]
    write_csv(ARTIFACT("local_ops_reset_risk_findings_snapshot.csv"), headers, rows)
    open_rows = [row for row in rows if row["Status"] == RiskFindingStatus.OPEN]
    summary = {
        "Project_Count": len(projects),
        "Active_Project_Count": len(active_project_ids),
        "Open_Risk_Count": len(open_rows),
        "Open_Project_Risk_Count": sum(row["Classification"] == "VALID_PROJECT_RISK" for row in open_rows),
        "Open_Orphan_Risk_Count": sum(row["Is_Orphan"] == "YES" for row in open_rows),
        "Open_Global_System_Risk_Count": 0,
        "CEO_Should_Show_Open_Risk_Count": sum(
            row["Should_Show_On_CEO_Dashboard"] == "YES" for row in open_rows
        ),
    }
    write_csv(
        ARTIFACT("local_ops_reset_risk_project_count_snapshot.csv"), list(summary.keys()), [summary]
    )
    print("PROJECT_COUNT=", summary["Project_Count"])
    print("OPEN_RISK_COUNT=", summary["Open_Risk_Count"])
    print("OPEN_ORPHAN_RISK_COUNT=", summary["Open_Orphan_Risk_Count"])
    print("CEO_SHOULD_SHOW_OPEN_RISK_COUNT=", summary["CEO_Should_Show_Open_Risk_Count"])
    print("LOCAL_OPS_RISK_DIAGNOSTIC_PASS")


if __name__ == "__main__":
    main()
