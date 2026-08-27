"""Read-only local/demo diagnostic for HQ and CEO operational risk visibility."""

from __future__ import annotations

import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from local_ops_reset_project_data import ARTIFACT, db_guard, setup_django, write_csv


def main():
    setup_django()
    from django.conf import settings
    from apps.projects.models import Project
    from apps.risk.dashboard_visibility import classify_operational_dashboard_risk, get_operational_dashboard_risk_queryset, is_demo_seed_risk
    from apps.risk.models import RiskFinding, RiskFindingStatus, RiskSeverity

    guard = db_guard(settings)
    if not guard["passed"]:
        raise RuntimeError("LOCAL/DEMO database guard blocked HQ risk diagnostic")
    projects = list(Project.objects.order_by("id"))
    project_ids = {project.id for project in projects}
    active_project_ids = {project.id for project in projects if project.is_active}
    visible_ids = set(get_operational_dashboard_risk_queryset().values_list("id", flat=True))
    rows = []
    for finding in RiskFinding.objects.select_related("project", "rule").order_by("id"):
        classification = classify_operational_dashboard_risk(finding)
        is_open = finding.status == RiskFindingStatus.OPEN
        is_orphan = classification == "ORPHAN_PROJECT_RISK"
        visible = finding.id in visible_ids
        rows.append({
            "RiskFinding_ID": finding.id, "Title": finding.title, "Status": finding.status,
            "Severity": finding.severity, "Project_ID": finding.project_id or "",
            "Project_Exists": "YES" if finding.project_id in project_ids else "NO",
            "Project_Code": finding.project.code if finding.project_id in project_ids else "",
            "Project_Name": finding.project.name if finding.project_id in project_ids else "",
            "Project_Is_Active": "YES" if finding.project_id in active_project_ids else "NO",
            "Object_Type": finding.object_type, "Object_ID": finding.object_id,
            "Object_Exists_If_Resolvable": "YES" if (finding.object_type or "").upper() == "PROJECT" and finding.object_id in project_ids else "NO" if (finding.object_type or "").upper() == "PROJECT" else "-",
            "Source": finding.rule.key if finding.rule_id else "", "Category": "",
            "Meta_Flags": "", "Created_At": finding.created_at.isoformat(),
            "Is_Demo_Seed": "YES" if is_demo_seed_risk(finding) else "NO",
            "Is_Project_Scoped": "YES" if finding.project_id or (finding.object_type or "").upper() == "PROJECT" else "NO",
            "Is_Orphan": "YES" if is_orphan else "NO",
            "Is_Projectless_Non_System": "YES" if classification == "PROJECTLESS_NON_SYSTEM_RISK" else "NO",
            "Is_Valid_Global_System": "NO", "HQ_Currently_Visible": "YES" if visible else "NO",
            "CEO_Currently_Visible": "YES" if visible else "NO", "Should_Be_HQ_Visible": "YES" if visible else "NO",
            "Should_Be_CEO_Visible": "YES" if visible else "NO", "Classification": classification,
            "Recommended_Action": "DELETE_LOCAL_DEMO_RESET" if classification == "DEMO_SEED_RISK" else "DELETE_LOCAL_RESET" if is_orphan else "PRESERVE" if visible else "EXCLUDE_FROM_DASHBOARD",
            "Reason": "Operational dashboards require an active project and exclude demo/seed risks.",
        })
    headers = list(rows[0].keys()) if rows else ["RiskFinding_ID", "Title", "Status", "Severity", "Project_ID", "Project_Exists", "Project_Code", "Project_Name", "Project_Is_Active", "Object_Type", "Object_ID", "Object_Exists_If_Resolvable", "Source", "Category", "Meta_Flags", "Created_At", "Is_Demo_Seed", "Is_Project_Scoped", "Is_Orphan", "Is_Projectless_Non_System", "Is_Valid_Global_System", "HQ_Currently_Visible", "CEO_Currently_Visible", "Should_Be_HQ_Visible", "Should_Be_CEO_Visible", "Classification", "Recommended_Action", "Reason"]
    write_csv(ARTIFACT("local_ops_reset_hq_risk_findings_snapshot.csv"), headers, rows)
    high_rows = [row for row in rows if row["Status"] == RiskFindingStatus.OPEN and row["Severity"] in {RiskSeverity.CRITICAL, RiskSeverity.HIGH}]
    summary = {
        "Project_Count": len(projects), "Active_Project_Count": len(active_project_ids),
        "Open_Risk_Count_DB": sum(row["Status"] == RiskFindingStatus.OPEN for row in rows),
        "Open_CRITICAL_HIGH_DB": len(high_rows),
        "Valid_Project_Open_Risk_Count": sum(row["Classification"] == "VALID_ACTIVE_PROJECT_RISK" for row in rows),
        "Valid_Project_CRITICAL_HIGH_Count": sum(row["Classification"] == "VALID_ACTIVE_PROJECT_RISK" for row in high_rows),
        "Demo_Seed_Open_Risk_Count": sum(row["Classification"] == "DEMO_SEED_RISK" for row in rows if row["Status"] == RiskFindingStatus.OPEN),
        "Orphan_Open_Risk_Count": sum(row["Is_Orphan"] == "YES" for row in rows if row["Status"] == RiskFindingStatus.OPEN),
        "Projectless_Non_System_Open_Risk_Count": sum(row["Is_Projectless_Non_System"] == "YES" for row in rows if row["Status"] == RiskFindingStatus.OPEN),
        "HQ_Displayed_CRITICAL_HIGH_Count_Before": len(high_rows),
        "HQ_Displayed_CRITICAL_HIGH_Count_After_Expected": sum(row["Should_Be_HQ_Visible"] == "YES" for row in high_rows),
        "CEO_Displayed_CRITICAL_HIGH_Count_After_Expected": sum(row["Should_Be_CEO_Visible"] == "YES" for row in high_rows),
    }
    write_csv(ARTIFACT("local_ops_reset_hq_risk_dashboard_count_snapshot.csv"), list(summary.keys()), [summary])
    print("PROJECT_COUNT=", summary["Project_Count"])
    print("OPEN_CRITICAL_HIGH_DB=", summary["Open_CRITICAL_HIGH_DB"])
    print("HQ_DISPLAYED_CRITICAL_HIGH_AFTER_EXPECTED=", summary["HQ_Displayed_CRITICAL_HIGH_Count_After_Expected"])
    print("LOCAL_OPS_HQ_RISK_DIAGNOSTIC_PASS")


if __name__ == "__main__":
    main()
