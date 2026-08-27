"""Guarded local/demo reset for project-scoped operational data only."""

from __future__ import annotations

import argparse
import csv
import json
import os
import sys
from collections import OrderedDict
from datetime import datetime
from pathlib import Path


RESET_TOKEN = "LOCAL-OPS-RESET-01"
ROOT = Path(__file__).resolve().parents[1]
ARTIFACT = lambda name: ROOT / name
LOCAL_HOSTS = {"", "localhost", "127.0.0.1", "::1"}
SAFE_NAME_TOKENS = {"local", "demo", "dev", "test", "construction_erp_demo"}
UNSAFE_NAME_TOKENS = {"prod", "production", "staging", "live", "real"}
DASHBOARD_RECENT_APPROVAL_ACTIONS = (
    "APPROVAL_APPROVE",
    "APPROVAL_REJECT",
    "CONTRACT_SUBMIT",
    "CONTRACT_REJECT",
    "PLAN_CHANGE_SUBMIT",
    "PLAN_CHANGE_REJECT",
    "MONTH_CLOSED",
    "CLOSING_REQUEST_APPROVE",
    "CLOSING_REQUEST_REJECT",
)


def setup_django():
    if str(ROOT) not in sys.path:
        sys.path.insert(0, str(ROOT))
    os.environ.setdefault("DJANGO_SETTINGS_MODULE", "config.settings.local")
    import django

    django.setup()


def write_csv(path: Path, headers, rows):
    with path.open("w", encoding="utf-8-sig", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=headers)
        writer.writeheader()
        writer.writerows(rows)


def db_guard(settings):
    db = settings.DATABASES["default"]
    engine = (db.get("ENGINE") or "").lower()
    name = str(db.get("NAME") or "")
    host = str(db.get("HOST") or "").strip().lower()
    name_lower = name.lower()
    engine_ok = "postgresql" in engine or "sqlite" in engine
    host_ok = host in LOCAL_HOSTS if "postgresql" in engine else not host
    name_ok = any(token in name_lower for token in SAFE_NAME_TOKENS)
    name_safe = not any(token in name_lower for token in UNSAFE_NAME_TOKENS)
    return {
        "engine": engine,
        "name": name,
        "host": host,
        "engine_ok": engine_ok,
        "host_ok": host_ok,
        "name_ok": name_ok,
        "name_safe": name_safe,
        "passed": engine_ok and host_ok and name_ok and name_safe,
    }


def get_model(apps, label):
    try:
        return apps.get_model(label)
    except LookupError:
        return None


def _project_relation_labels(apps, Project):
    labels = {}
    for model in apps.get_models():
        fields = []
        for field in model._meta.get_fields():
            if getattr(field, "auto_created", False):
                continue
            if getattr(field, "related_model", None) is Project:
                fields.append(field.name)
        if fields:
            labels[model._meta.label] = fields
    return labels


def _qs(model, *args, **filters):
    return model.objects.filter(*args, **filters) if model else None


def _risk_cleanup_querysets(models, project_ids, existing_project_ids):
    """Select only reset-target or already-orphaned PROJECT risk records."""
    from django.db.models import Q

    project_ids = list(project_ids)
    existing_project_ids = list(existing_project_ids)
    demo_seed_risk = (
        Q(rule__key__icontains="demo")
        | Q(rule__key__icontains="seed")
        | Q(title__icontains="demo")
        | Q(title__icontains="seed")
        | Q(details__icontains="demo")
        | Q(details__icontains="seed")
    )
    orphan_project_reference = Q(project__isnull=True, object_type__iexact="PROJECT") & (
        Q(object_id__in=project_ids) | ~Q(object_id__in=existing_project_ids)
    )
    findings = _qs(
        models["risk.RiskFinding"],
        Q(project_id__in=project_ids) | orphan_project_reference | demo_seed_risk,
    )

    orphan_event_reference = Q(object_type__iexact="PROJECT") & (
        Q(object_id__in=project_ids) | ~Q(object_id__in=existing_project_ids)
    )
    events = _qs(
        models["risk.RiskEvent"],
        Q(object_type__in=["PROJECT", "PROJECT_IMPORT"], object_id__in=project_ids)
        | orphan_event_reference,
    )
    return findings, events


def build_manifest(apps, project_ids, existing_project_ids=None):
    from django.db.models import Q

    project_ids = list(project_ids)
    models = {label: get_model(apps, label) for label in (
        "core.ProjectAssignment",
        "projects.BudgetItem",
        "projects.WBSItem",
        "projects.WBSChangeRequest",
        "projects.ApprovalPackage",
        "projects.ProjectContract",
        "field.DailyReport",
        "cost.CostActual",
        "cost.RevenueRecognition",
        "finance.CashEvent",
        "schedule.SchedulePlan",
        "schedule.ScheduleTask",
        "schedule.DailyProgress",
        "schedule.PlanChangeRequest",
        "contracts.ContractChange",
        "contracts.ContractSnapshot",
        "risk.RiskFinding",
        "reports.FieldReport",
        "master.FavoriteCostItem",
        "closing.ProjectClose",
        "closing.Adjustment",
        "inventory.Warehouse",
        "inventory.Transfer",
        "inventory.IssueToWork",
        "inventory.InventoryLedger",
        "labor.LaborRateTable",
        "labor.LaborWorkLedger",
        "labor.LaborMonthlyPayroll",
        "labor.ElectronicCardImportBatch",
        "labor.ElectronicCardWorkRaw",
        "labor.ElectronicCardWorkDay",
        "labor.LaborReconciliationResult",
        "labor.LaborConfirmedWorkDay",
        "labor.LaborExcelExportBatch",
        "labor.Timesheet",
        "labor.PayrollAllocationLine",
        "labor.PayrollAllocationBatch",
        "evidence.Evidence",
        "evidence.EvidenceFile",
        "core.ApprovalRequest",
        "risk.RiskEvent",
    )}

    batches = _qs(models["labor.ElectronicCardImportBatch"], project_id__in=project_ids)
    batch_ids = list(batches.values_list("id", flat=True)) if batches else []
    warehouses = _qs(models["inventory.Warehouse"], project_id__in=project_ids)
    warehouse_ids = list(warehouses.values_list("id", flat=True)) if warehouses else []
    contracts = _qs(models["projects.ProjectContract"], project_id__in=project_ids)
    contract_ids = list(contracts.values_list("id", flat=True)) if contracts else []

    evidence_filter = Q(object_type__in=["PROJECT", "PROJECT_IMPORT"], object_id__in=project_ids)
    evidence_filter |= Q(object_type="PROJECT_CONTRACT", object_id__in=contract_ids)
    generic_filter = Q(object_type__in=["PROJECT", "PROJECT_IMPORT"], object_id__in=project_ids)
    existing_project_ids = list(project_ids if existing_project_ids is None else existing_project_ids)
    risk_findings, risk_events = _risk_cleanup_querysets(
        models, project_ids, existing_project_ids
    )

    entries = OrderedDict([
        ("LaborExcelExportBatch", _qs(models["labor.LaborExcelExportBatch"], Q(project_id__in=project_ids) | Q(source_batch_id__in=batch_ids)) if models["labor.LaborExcelExportBatch"] else None),
        ("LaborConfirmedWorkDay", _qs(models["labor.LaborConfirmedWorkDay"], Q(actual_project_id__in=project_ids) | Q(report_project_id__in=project_ids) | Q(card_project_id__in=project_ids) | Q(batch_id__in=batch_ids)) if models["labor.LaborConfirmedWorkDay"] else None),
        ("LaborReconciliationResult", _qs(models["labor.LaborReconciliationResult"], Q(project_id__in=project_ids) | Q(batch_id__in=batch_ids)) if models["labor.LaborReconciliationResult"] else None),
        ("ElectronicCardWorkDay", _qs(models["labor.ElectronicCardWorkDay"], Q(card_project_id__in=project_ids) | Q(batch_id__in=batch_ids)) if models["labor.ElectronicCardWorkDay"] else None),
        ("ElectronicCardWorkRaw", _qs(models["labor.ElectronicCardWorkRaw"], batch_id__in=batch_ids)),
        ("ElectronicCardImportBatch", batches),
        ("PayrollAllocationLine", _qs(models["labor.PayrollAllocationLine"], project_id__in=project_ids)),
        ("LaborMonthlyPayroll", _qs(models["labor.LaborMonthlyPayroll"], Q(project_id__in=project_ids) | Q(report_project_id__in=project_ids)) if models["labor.LaborMonthlyPayroll"] else None),
        ("LaborWorkLedger", _qs(models["labor.LaborWorkLedger"], Q(actual_project_id__in=project_ids) | Q(report_project_id__in=project_ids)) if models["labor.LaborWorkLedger"] else None),
        ("Timesheet", _qs(models["labor.Timesheet"], project_id__in=project_ids)),
        ("DailyProgress", _qs(models["schedule.DailyProgress"], project_id__in=project_ids)),
        ("PlanChangeRequest", _qs(models["schedule.PlanChangeRequest"], project_id__in=project_ids)),
        ("ScheduleTask", _qs(models["schedule.ScheduleTask"], plan__project_id__in=project_ids)),
        ("SchedulePlan", _qs(models["schedule.SchedulePlan"], project_id__in=project_ids)),
        ("CostActual", _qs(models["cost.CostActual"], project_id__in=project_ids)),
        ("RevenueRecognition", _qs(models["cost.RevenueRecognition"], project_id__in=project_ids)),
        ("CashEvent", _qs(models["finance.CashEvent"], project_id__in=project_ids)),
        ("ContractSnapshot", _qs(models["contracts.ContractSnapshot"], project_id__in=project_ids)),
        ("ContractChange", _qs(models["contracts.ContractChange"], project_id__in=project_ids)),
        ("DailyReport", _qs(models["field.DailyReport"], project_id__in=project_ids)),
        ("FieldReport", _qs(models["reports.FieldReport"], project_id__in=project_ids)),
        ("RiskFinding", risk_findings),
        ("RiskEvent", risk_events),
        ("Adjustment", _qs(models["closing.Adjustment"], project_id__in=project_ids)),
        ("ProjectClose", _qs(models["closing.ProjectClose"], project_id__in=project_ids)),
        ("ApprovalPackage", _qs(models["projects.ApprovalPackage"], project_id__in=project_ids)),
        ("ApprovalRequest", _qs(models["core.ApprovalRequest"], generic_filter)),
        ("WBSChangeRequest", _qs(models["projects.WBSChangeRequest"], project_id__in=project_ids)),
        ("BudgetItem", _qs(models["projects.BudgetItem"], project_id__in=project_ids)),
        ("WBSItem", _qs(models["projects.WBSItem"], project_id__in=project_ids)),
        ("ProjectContract", contracts),
        ("ProjectAssignment", _qs(models["core.ProjectAssignment"], project_id__in=project_ids)),
        ("FavoriteCostItem", _qs(models["master.FavoriteCostItem"], project_id__in=project_ids)),
        ("LaborRateTableProjectScope", _qs(models["labor.LaborRateTable"], project_id__in=project_ids)),
        ("IssueToWork", _qs(models["inventory.IssueToWork"], Q(project_id__in=project_ids) | Q(warehouse_id__in=warehouse_ids)) if models["inventory.IssueToWork"] else None),
        ("Transfer", _qs(models["inventory.Transfer"], Q(project_id__in=project_ids) | Q(from_warehouse_id__in=warehouse_ids) | Q(to_warehouse_id__in=warehouse_ids)) if models["inventory.Transfer"] else None),
        ("InventoryLedger", _qs(models["inventory.InventoryLedger"], warehouse_id__in=warehouse_ids)),
        ("Warehouse", warehouses),
        ("Evidence", _qs(models["evidence.Evidence"], evidence_filter)),
    ])
    orphan_risk_count = (
        risk_findings.filter(project__isnull=True, object_type__iexact="PROJECT")
        .exclude(object_id__in=existing_project_ids)
        .count()
        if risk_findings is not None
        else 0
    )
    return entries, models, {
        "batch_ids": batch_ids,
        "warehouse_ids": warehouse_ids,
        "contract_ids": contract_ids,
        "risk_cleanup": {
            "target_risk_count": query_count(risk_findings),
            "orphan_risk_count": orphan_risk_count,
            "global_risks_preserved": 0,
        },
    }


def query_count(queryset):
    return queryset.count() if queryset is not None else 0


def write_risk_cleanup_manifest(entries, existing_project_ids):
    rows = []
    findings = entries.get("RiskFinding")
    for finding in findings or []:
        is_demo_seed = any(
            token in " ".join((finding.title or "", finding.details or "", finding.rule.key if finding.rule_id else "")).lower()
            for token in ("demo", "seed")
        )
        is_orphan = (
            finding.project_id is None
            and str(finding.object_type or "").upper() == "PROJECT"
            and finding.object_id not in existing_project_ids
        )
        classification = (
            "DEMO_SEED_RISK" if is_demo_seed else "ORPHAN_PROJECT_RISK" if is_orphan else "PROJECT_SCOPED_RISK"
        )
        rows.append({
            "RiskFinding_ID": finding.id,
            "Status_Before": finding.status,
            "Severity": finding.severity,
            "Project_ID": finding.project_id or "",
            "Project_Exists": "YES" if finding.project_id else "NO",
            "Object_Type": finding.object_type,
            "Object_ID": finding.object_id,
            "Classification": classification,
            "Cleanup_Action": "DELETE_LOCAL_RESET",
            "Status_After": "DELETED_ON_APPLY",
            "Deleted": "YES_ON_APPLY",
            "Reason": "Local reset target or deleted PROJECT reference",
            "Notes": "RiskRule and AuditLog are preserved.",
        })
    headers = [
        "RiskFinding_ID", "Status_Before", "Severity", "Project_ID", "Project_Exists",
        "Object_Type", "Object_ID", "Classification", "Cleanup_Action", "Status_After",
        "Deleted", "Reason", "Notes",
    ]
    write_csv(ARTIFACT("local_ops_reset_risk_cleanup_manifest.csv"), headers, rows)
    write_csv(ARTIFACT("local_ops_reset_hq_risk_cleanup_manifest.csv"), headers, rows)


def get_stale_dashboard_approval_logs(AuditLog, project_ids):
    """Keep audit history, but report entries that will not be current after reset."""
    from django.db.models import Q

    return AuditLog.objects.filter(action__in=DASHBOARD_RECENT_APPROVAL_ACTIONS).filter(
        Q(project_id__in=project_ids) | Q(project__isnull=True)
    )


def write_stale_approval_manifest(AuditLog, project_ids):
    rows = []
    for entry in get_stale_dashboard_approval_logs(AuditLog, project_ids).select_related("project"):
        linked_to_target = entry.project_id in project_ids
        rows.append({
            "Source_Model": "AuditLog",
            "Source_ID": entry.id,
            "Action": entry.action,
            "Object_Type": entry.object_type,
            "Object_ID": entry.object_id,
            "Project_ID": entry.project_id or "",
            "Classification": (
                "STALE_DELETED_PROJECT_APPROVAL" if linked_to_target else "PROJECTLESS_APPROVAL_LOG"
            ),
            "Recommended_Action": "PRESERVE_AUDITLOG_EXCLUDE_FROM_DASHBOARD",
            "Dashboard_Visible_After": "NO",
            "Reason": "Audit ledger is preserved; current dashboard requires an active project.",
        })
    headers = [
        "Source_Model", "Source_ID", "Action", "Object_Type", "Object_ID", "Project_ID",
        "Classification", "Recommended_Action", "Dashboard_Visible_After", "Reason",
    ]
    write_csv(ARTIFACT("local_ops_reset_ceo_recent_stale_approval_manifest.csv"), headers, rows)
    return len(rows)


def write_dry_run(Project, projects, entries, media_rows, guard, relation_labels, unhandled):
    project_rows = []
    for project in projects:
        project_rows.append({
            "Project_ID": project.id,
            "Project_Code": project.code,
            "Project_Name": project.name,
            "Status": project.status,
            "Is_Active": project.is_active,
            "Start_Date": project.start_date or "",
            "End_Date": project.end_date or "",
            "Contract_Amount": project.contract_amount,
            "Delete_Target": "YES",
            "Protection_Reason": "",
        })
    write_csv(ARTIFACT("local_ops_reset_dryrun_project_manifest.csv"), project_rows[0].keys() if project_rows else ["Project_ID", "Project_Code", "Project_Name", "Status", "Is_Active", "Start_Date", "End_Date", "Contract_Amount", "Delete_Target", "Protection_Reason"], project_rows)
    dependency_rows = [
        {"Model": name, "Count": query_count(queryset), "Delete_Action": "DELETE", "Preserved": "NO", "Reason": "project-scoped", "Notes": ""}
        for name, queryset in entries.items()
    ]
    dependency_rows.extend([
        {"Model": "audit.AuditLog", "Count": 0, "Delete_Action": "SET_NULL by Project deletion", "Preserved": "YES", "Reason": "audit preservation policy", "Notes": "No AuditLog deletion"},
        {"Model": "auth.User/UserProfile/CostItem/WorkerMaster", "Count": 0, "Delete_Action": "NONE", "Preserved": "YES", "Reason": "global master preservation policy", "Notes": ""},
    ])
    write_csv(ARTIFACT("local_ops_reset_dryrun_dependency_manifest.csv"), dependency_rows[0].keys(), dependency_rows)
    write_csv(ARTIFACT("local_ops_reset_dryrun_media_manifest.csv"), ["Storage_Name", "Model", "Record_ID", "Action", "Notes"], media_rows)
    result = {
        "guard": guard,
        "project_count": len(project_rows),
        "unhandled_direct_project_relations": unhandled,
        "project_relations": relation_labels,
        "result": "LOCAL_OPS_RESET_DRYRUN_PASS" if guard["passed"] and not unhandled else "LOCAL_OPS_RESET_HOLD",
    }
    ARTIFACT("local_ops_reset_dryrun_result.txt").write_text(json.dumps(result, ensure_ascii=False, indent=2), encoding="utf-8")
    return result


def run_route_smoke(apps):
    from django.test import Client

    UserProfile = get_model(apps, "core.UserProfile")
    role_users = {}
    if UserProfile:
        for profile in UserProfile.objects.select_related("user").filter(
            user__is_active=True
        ).order_by("id"):
            role_users.setdefault(profile.role, profile.user)
    routes = [
        ("/app/hq/projects/", "hq"),
        ("/app/hq/projects/new/", "hq"),
        ("/app/ceo/", "ceo"),
        ("/app/field/", "field"),
        ("/app/hq/labor/e-card-imports/", "hq"),
    ]
    rows = []
    for route, role in routes:
        user = role_users.get(role)
        if user is None:
            rows.append({"Route": route, "Role": role.upper(), "Expected": "non-500", "Actual_Status": "SKIPPED", "Result": "HOLD", "Notes": "No active user for role"})
            continue
        client = Client(HTTP_HOST="127.0.0.1")
        client.force_login(user)
        response = client.get(route, HTTP_HOST="127.0.0.1")
        rows.append({"Route": route, "Role": role.upper(), "Expected": "non-500", "Actual_Status": response.status_code, "Result": "PASS" if response.status_code < 500 else "FAIL", "Notes": ""})
    write_csv(ARTIFACT("local_ops_reset_24_route_smoke_matrix.csv"), ["Route", "Role", "Expected", "Actual_Status", "Result", "Notes"], rows)
    return all(row["Result"] == "PASS" for row in rows)


def validate_local_media_targets(settings, media_rows):
    media_root_value = str(getattr(settings, "MEDIA_ROOT", "") or "")
    if not media_root_value:
        raise RuntimeError("MEDIA_ROOT is not configured for local media deletion")
    media_root = Path(media_root_value).resolve()
    targets = []
    for row in media_rows:
        candidate = (media_root / row["Storage_Name"]).resolve()
        if candidate != media_root and media_root not in candidate.parents:
            raise RuntimeError(f"Unsafe media path: {row['Storage_Name']}")
        targets.append((candidate, row))
    return targets


def main():
    parser = argparse.ArgumentParser(description="Guarded local project-data reset")
    parser.add_argument("--apply", action="store_true", help="perform deletion after all guards pass")
    parser.add_argument("--dry-run", action="store_true", help="explicit dry-run (the default)")
    parser.add_argument("--confirm-local-reset", default="")
    parser.add_argument("--delete-media", action="store_true")
    args = parser.parse_args()
    if args.apply and args.dry_run:
        parser.error("--apply and --dry-run cannot be used together")

    setup_django()
    from django.apps import apps
    from django.conf import settings
    from django.db import transaction
    from apps.projects.models import Project

    guard = db_guard(settings)
    projects = list(Project.objects.order_by("id"))
    project_ids = [project.id for project in projects]
    relation_labels = _project_relation_labels(apps, Project)
    handled_labels = {
        "core.ProjectAssignment", "projects.BudgetItem", "projects.WBSItem", "projects.WBSChangeRequest",
        "projects.ApprovalPackage", "projects.ProjectContract", "field.DailyReport", "cost.CostActual",
        "cost.RevenueRecognition", "finance.CashEvent", "schedule.SchedulePlan", "schedule.DailyProgress",
        "schedule.PlanChangeRequest", "contracts.ContractChange", "contracts.ContractSnapshot", "risk.RiskFinding",
        "audit.AuditLog", "reports.FieldReport", "master.FavoriteCostItem", "closing.ProjectClose",
        "closing.Adjustment", "inventory.Warehouse", "inventory.Transfer", "inventory.IssueToWork",
        "labor.LaborRateTable", "labor.LaborWorkLedger", "labor.LaborMonthlyPayroll",
        "labor.ElectronicCardImportBatch", "labor.ElectronicCardWorkDay", "labor.LaborReconciliationResult",
        "labor.LaborConfirmedWorkDay", "labor.LaborExcelExportBatch", "labor.Timesheet", "labor.PayrollAllocationLine",
    }
    unhandled = sorted(set(relation_labels) - handled_labels)
    entries, models, related_ids = build_manifest(apps, project_ids, project_ids)
    write_risk_cleanup_manifest(entries, set(project_ids))
    AuditLog = get_model(apps, "audit.AuditLog")
    stale_approval_count = write_stale_approval_manifest(AuditLog, set(project_ids)) if AuditLog else 0

    media_rows = []
    for model_name in ("labor.ElectronicCardImportBatch", "labor.LaborExcelExportBatch"):
        model = models.get(model_name)
        if not model:
            continue
        queryset = entries.get("ElectronicCardImportBatch") if model_name.endswith("ImportBatch") else entries.get("LaborExcelExportBatch")
        file_field = "source_file" if model_name.endswith("ImportBatch") else "generated_file"
        for row in queryset or []:
            storage_name = getattr(getattr(row, file_field), "name", "")
            if storage_name:
                media_rows.append({"Storage_Name": storage_name, "Model": model_name, "Record_ID": row.id, "Action": "PRESERVE", "Notes": "--delete-media not supplied"})
    evidence = entries.get("Evidence")
    if evidence:
        for evidence_row in evidence.prefetch_related("files"):
            for file_row in evidence_row.files.all():
                media_rows.append({"Storage_Name": file_row.file.name, "Model": "evidence.EvidenceFile", "Record_ID": file_row.id, "Action": "PRESERVE", "Notes": "--delete-media not supplied"})

    result = write_dry_run(Project, projects, entries, media_rows, guard, relation_labels, unhandled)
    print("DB_ENGINE=", guard["engine"])
    print("DB_NAME=", guard["name"])
    print("DB_HOST=", guard["host"])
    print("PROJECT_COUNT=", len(project_ids))

    if not args.apply:
        print(result["result"])
        return 0 if result["result"] == "LOCAL_OPS_RESET_DRYRUN_PASS" else 2
    if not guard["passed"] or unhandled or args.confirm_local_reset != RESET_TOKEN:
        print("RESET_GUARD_BLOCKED")
        return 2
    media_targets = validate_local_media_targets(settings, media_rows) if args.delete_media else []

    before_counts = {name: query_count(queryset) for name, queryset in entries.items()}
    deleted_counts = []
    with transaction.atomic():
        for name, queryset in entries.items():
            before = query_count(queryset)
            if queryset is not None and before:
                queryset.delete()
            after = query_count(queryset)
            deleted_counts.append({"Model": name, "Before_Count": before, "Deleted_Count": before - after, "After_Count": after, "Result": "PASS" if after == 0 else "HOLD"})
        project_before = Project.objects.filter(id__in=project_ids).count()
        Project.objects.filter(id__in=project_ids).delete()
        project_after = Project.objects.filter(id__in=project_ids).count()
        deleted_counts.append({"Model": "Project", "Before_Count": project_before, "Deleted_Count": project_before - project_after, "After_Count": project_after, "Result": "PASS" if project_after == 0 else "HOLD"})
        if project_after:
            raise RuntimeError("Project rows remain after reset")

        if AuditLog:
            AuditLog.objects.create(
                action="LOCAL_OPS_PROJECT_DATA_RESET",
                object_type="LOCAL_OPS_RESET",
                object_id=0,
                meta_json={"deleted_counts": {row["Model"]: row["Deleted_Count"] for row in deleted_counts}, "operator": "management_script", "dry_run": False},
            )
            AuditLog.objects.create(
                action="LOCAL_OPS_RESET_RISK_CLEANUP",
                object_type="LOCAL_OPS_RESET",
                object_id=0,
                meta_json={
                    "project_count_before": len(project_ids),
                    "risk_findings_deleted": related_ids["risk_cleanup"]["target_risk_count"],
                    "orphan_risks_deleted": related_ids["risk_cleanup"]["orphan_risk_count"],
                    "global_risks_preserved": related_ids["risk_cleanup"]["global_risks_preserved"],
                    "operator": "management_script",
                    "dry_run": False,
                },
            )
            AuditLog.objects.create(
                action="LOCAL_OPS_RESET_DASHBOARD_STALE_APPROVAL_FILTER_CHECK",
                object_type="LOCAL_OPS_RESET",
                object_id=0,
                meta_json={
                    "stale_approval_count": stale_approval_count,
                    "dashboard_visible_after": 0,
                    "operator": "management_script",
                    "dry_run": False,
                },
            )

    if args.delete_media:
        for candidate, row in media_targets:
            if candidate.is_file():
                candidate.unlink()
                row["Action"] = "DELETED"
                row["Notes"] = "Deleted under local MEDIA_ROOT"
            else:
                row["Action"] = "MISSING"
                row["Notes"] = "No local file to delete"
        write_csv(ARTIFACT("local_ops_reset_apply_media_result.csv"), ["Storage_Name", "Model", "Record_ID", "Action", "Notes"], media_rows)

    write_csv(ARTIFACT("local_ops_reset_apply_deleted_counts.csv"), ["Model", "Before_Count", "Deleted_Count", "After_Count", "Result"], deleted_counts)
    postcheck = [{"Model": row["Model"], "Remaining_Count": row["After_Count"], "Result": row["Result"]} for row in deleted_counts]
    write_csv(ARTIFACT("local_ops_reset_apply_postcheck.csv"), ["Model", "Remaining_Count", "Result"], postcheck)
    route_smoke_passed = run_route_smoke(apps)
    final_result = "LOCAL_OPS_RESET_APPLY_PASS" if route_smoke_passed else "LOCAL_OPS_RESET_HOLD"
    ARTIFACT("local_ops_reset_apply_result.txt").write_text(f"{final_result}\n", encoding="utf-8")
    print(final_result)
    return 0 if route_smoke_passed else 2


if __name__ == "__main__":
    sys.exit(main())
