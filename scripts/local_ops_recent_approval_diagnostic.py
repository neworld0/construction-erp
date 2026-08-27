"""Read-only local/demo diagnostic for stale CEO and HQ approval dashboard rows."""

from __future__ import annotations

import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from local_ops_reset_project_data import (
    ARTIFACT,
    DASHBOARD_RECENT_APPROVAL_ACTIONS,
    db_guard,
    setup_django,
    write_csv,
)


def classify_audit_log(entry, active_project_ids):
    if entry.action not in DASHBOARD_RECENT_APPROVAL_ACTIONS:
        return "NON_APPROVAL_LOG", False, "PRESERVE", "Not a dashboard approval action."
    if entry.project_id in active_project_ids:
        return "VALID_ACTIVE_PROJECT_APPROVAL", True, "PRESERVE", "Linked to an active project."
    if entry.project_id:
        return "STALE_DELETED_PROJECT_APPROVAL", False, "PRESERVE_AUDITLOG_EXCLUDE_FROM_DASHBOARD", "Project is inactive."
    return "PROJECTLESS_APPROVAL_LOG", False, "PRESERVE_AUDITLOG_EXCLUDE_FROM_DASHBOARD", "No active project link."


def resolve_approval_project(approval, Project):
    if (approval.object_type or "").upper() == "PROJECT_BASELINE":
        return Project.objects.filter(id=approval.object_id).first()
    from apps.core.services.approvals import _resolve_approval_project

    return _resolve_approval_project(approval)


def main():
    setup_django()
    from django.conf import settings
    from apps.audit.models import AuditLog
    from apps.core.models import ApprovalRequest, ApprovalStatus
    from apps.projects.models import Project

    guard = db_guard(settings)
    if not guard["passed"]:
        raise RuntimeError("LOCAL/DEMO database guard blocked approval diagnostic")

    projects = list(Project.objects.order_by("id"))
    existing_project_ids = {project.id for project in projects}
    active_project_ids = {project.id for project in projects if project.is_active}
    rows = []
    audit_logs = AuditLog.objects.filter(action__in=DASHBOARD_RECENT_APPROVAL_ACTIONS).select_related("project")
    for entry in audit_logs.order_by("-created_at"):
        classification, visible, action, reason = classify_audit_log(entry, active_project_ids)
        object_exists = ApprovalRequest.objects.filter(id=entry.object_id).exists() if entry.object_type == "APPROVAL_REQUEST" else None
        rows.append({
            "Source_Model": "AuditLog", "Source_ID": entry.id, "Action": entry.action,
            "Object_Type": entry.object_type, "Object_ID": entry.object_id,
            "Project_ID": entry.project_id or "", "Project_Exists": "YES" if entry.project_id in existing_project_ids else "NO",
            "Project_Code": entry.project.code if entry.project_id in existing_project_ids else "",
            "Project_Name": entry.project.name if entry.project_id in existing_project_ids else "",
            "Project_Is_Active": "YES" if entry.project_id in active_project_ids else "NO",
            "Object_Exists_If_Resolvable": "YES" if object_exists else "NO" if object_exists is not None else "-",
            "Is_Approval_Action": "YES", "Dashboard_Currently_Visible": "YES" if visible else "NO",
            "Should_Be_Dashboard_Visible": "YES" if visible else "NO", "Classification": classification,
            "Recommended_Action": action, "Reason": reason,
        })
    for approval in ApprovalRequest.objects.filter(status=ApprovalStatus.APPROVED).order_by("-approved_at", "-id"):
        project = resolve_approval_project(approval, Project)
        is_active_project = project is not None and project.is_active
        rows.append({
            "Source_Model": "ApprovalRequest", "Source_ID": approval.id, "Action": "APPROVED",
            "Object_Type": approval.object_type, "Object_ID": approval.object_id,
            "Project_ID": project.id if project else "", "Project_Exists": "YES" if project else "NO",
            "Project_Code": project.code if project else "", "Project_Name": project.name if project else "",
            "Project_Is_Active": "YES" if is_active_project else "NO", "Object_Exists_If_Resolvable": "YES" if project else "NO", "Is_Approval_Action": "YES",
            "Dashboard_Currently_Visible": "YES" if is_active_project else "NO", "Should_Be_Dashboard_Visible": "YES" if is_active_project else "NO",
            "Classification": "VALID_ACTIVE_PROJECT_APPROVAL" if is_active_project else "ORPHAN_OBJECT_APPROVAL",
            "Recommended_Action": "PRESERVE" if is_active_project else "EXCLUDE_FROM_DASHBOARD_PRESERVE_APPROVAL",
            "Reason": "Linked to an active project." if is_active_project else "Target project-scoped object cannot be resolved to an active project.",
        })
    headers = list(rows[0].keys()) if rows else [
        "Source_Model", "Source_ID", "Action", "Object_Type", "Object_ID", "Project_ID",
        "Project_Exists", "Project_Code", "Project_Name", "Project_Is_Active",
        "Object_Exists_If_Resolvable", "Is_Approval_Action", "Dashboard_Currently_Visible",
        "Should_Be_Dashboard_Visible", "Classification", "Recommended_Action", "Reason",
    ]
    write_csv(ARTIFACT("local_ops_reset_ceo_recent_actions_snapshot.csv"), headers, rows)
    audit_rows = [row for row in rows if row["Source_Model"] == "AuditLog"]
    summary = {
        "Project_Count": len(projects), "Active_Project_Count": len(active_project_ids),
        "AuditLog_Approval_Action_Count": len(audit_rows),
        "Valid_Current_Approval_Count": sum(row["Classification"] == "VALID_ACTIVE_PROJECT_APPROVAL" for row in rows),
        "Stale_Deleted_Project_Approval_Count": sum(row["Classification"] == "STALE_DELETED_PROJECT_APPROVAL" for row in rows),
        "Orphan_Approval_Count": sum("ORPHAN" in row["Classification"] or "PROJECTLESS" in row["Classification"] for row in rows),
        "Dashboard_Should_Show_Count": sum(row["Should_Be_Dashboard_Visible"] == "YES" for row in rows),
    }
    write_csv(ARTIFACT("local_ops_reset_ceo_recent_dashboard_count_snapshot.csv"), list(summary.keys()), [summary])
    print("PROJECT_COUNT=", summary["Project_Count"])
    print("AUDITLOG_APPROVAL_ACTION_COUNT=", summary["AuditLog_Approval_Action_Count"])
    print("DASHBOARD_SHOULD_SHOW_COUNT=", summary["Dashboard_Should_Show_Count"])
    print("LOCAL_OPS_RECENT_APPROVAL_DIAGNOSTIC_PASS")


if __name__ == "__main__":
    main()
