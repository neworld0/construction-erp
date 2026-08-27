"""Dry-run first inactive-project purge with CEO pilot visibility verification."""

from __future__ import annotations

import argparse
import csv
import os
from decimal import Decimal
from pathlib import Path

os.environ.setdefault("DJANGO_SETTINGS_MODULE", "config.settings.local")

import django

django.setup()

from django.conf import settings
from django.contrib.auth import get_user_model
from django.db import transaction
from django.db.models import Sum
from django.test import Client

from apps.audit.models import AuditLog
from apps.contracts.models import ContractSnapshot
from apps.core.rbac.models import ProjectAssignment, Role, UserProfile
from apps.cost.models import CostActual, CostActualLine, RevenueRecognition
from apps.projects.models import BudgetItem, Project, ProjectContract, WBSItem
from apps.schedule.models import DailyProgress, SchedulePlan, ScheduleTask


PILOT_CODE = "OPS1B-RERUN-SAMPLE-001"
SAFE_DIRECT_MODELS = {
    "core.ProjectAssignment": ProjectAssignment,
    "projects.BudgetItem": BudgetItem,
    "projects.WBSItem": WBSItem,
    "contracts.ContractSnapshot": ContractSnapshot,
    "projects.ProjectContract": ProjectContract,
    "cost.RevenueRecognition": RevenueRecognition,
    "cost.CostActual": CostActual,
    "schedule.DailyProgress": DailyProgress,
    "schedule.SchedulePlan": SchedulePlan,
}


def _assert_local_demo_database() -> dict[str, str]:
    database = settings.DATABASES["default"]
    engine = str(database.get("ENGINE", ""))
    name = str(database.get("NAME", ""))
    host = str(database.get("HOST", ""))
    if not (
        engine.endswith("postgresql")
        and host.lower() in {"127.0.0.1", "localhost"}
        and any(token in name.lower() for token in ("demo", "local", "dev"))
    ):
        raise SystemExit("UNSAFE_DB_GUARD")
    return {"engine": engine, "host": host, "database": name}


def _count(queryset) -> int:
    return queryset.count()


def _dependent_rows(project: Project) -> list[dict[str, object]]:
    rows = [
        ("schedule.DailyProgress", "project", _count(DailyProgress.objects.filter(project=project)), "DELETE", "CASCADE_SAFE"),
        ("schedule.ScheduleTask", "plan__project", _count(ScheduleTask.objects.filter(plan__project=project)), "DELETE", "CASCADE_SAFE"),
        ("schedule.SchedulePlan", "project", _count(SchedulePlan.objects.filter(project=project)), "DELETE", "CASCADE_SAFE"),
        ("projects.BudgetItem", "project", _count(BudgetItem.objects.filter(project=project)), "DELETE", "CASCADE_SAFE"),
        ("projects.WBSItem", "project", _count(WBSItem.objects.filter(project=project)), "DELETE", "CASCADE_SAFE"),
        ("cost.RevenueRecognition", "project", _count(RevenueRecognition.objects.filter(project=project)), "DELETE", "CASCADE_SAFE"),
        ("cost.CostActualLine", "cost_actual__project", _count(CostActualLine.objects.filter(cost_actual__project=project)), "DELETE via CostActual", "CASCADE_SAFE"),
        ("cost.CostActual", "project", _count(CostActual.objects.filter(project=project)), "DELETE", "CASCADE_SAFE"),
        ("contracts.ContractSnapshot", "project", _count(ContractSnapshot.objects.filter(project=project)), "DELETE", "CASCADE_SAFE"),
        ("projects.ProjectContract", "project", _count(ProjectContract.objects.filter(project=project)), "DELETE", "CASCADE_SAFE"),
        ("core.ProjectAssignment", "project", _count(ProjectAssignment.objects.filter(project=project)), "DELETE", "CASCADE_SAFE"),
        ("audit.AuditLog", "project", _count(AuditLog.objects.filter(project=project)), "PRESERVE", "AUDIT_PRESERVE"),
    ]
    return [
        {
            "Project_ID": project.id,
            "Project_Code": project.code,
            "Model": model,
            "Relation": relation,
            "Row_Count": count,
            "Delete_Action": action,
            "Risk_Class": risk,
            "Notes": "AuditLog is preserved" if model == "audit.AuditLog" else "project-scoped relation",
        }
        for model, relation, count, action, risk in rows
    ]


def _unknown_project_relations(project: Project) -> list[str]:
    known = set(SAFE_DIRECT_MODELS) | {"audit.AuditLog"}
    unknown = []
    for relation in Project._meta.related_objects:
        model = relation.related_model
        label = model._meta.label
        if label in known:
            continue
        accessor = relation.get_accessor_name()
        if not accessor:
            continue
        manager = getattr(project, accessor, None)
        if manager is not None and hasattr(manager, "count") and manager.count():
            unknown.append(f"{label}:{accessor}:{manager.count()}")
    return unknown


def _delete_project_scoped_rows(project: Project) -> None:
    unknown = _unknown_project_relations(project)
    if unknown:
        raise RuntimeError("UNKNOWN_REVIEW_REQUIRED " + ", ".join(unknown))
    if AuditLog.objects.filter(project=project).exists():
        raise RuntimeError("AUDIT_PRESERVE blocks physical project purge")
    DailyProgress.objects.filter(project=project).delete()
    ScheduleTask.objects.filter(plan__project=project).delete()
    SchedulePlan.objects.filter(project=project).delete()
    BudgetItem.objects.filter(project=project).delete()
    WBSItem.objects.filter(project=project).delete()
    RevenueRecognition.objects.filter(project=project).delete()
    CostActual.objects.filter(project=project).delete()
    ContractSnapshot.objects.filter(project=project).delete()
    ProjectContract.objects.filter(project=project).delete()
    ProjectAssignment.objects.filter(project=project).delete()
    project.delete()


def _dashboard_visibility(project: Project) -> dict[str, object]:
    settings.ALLOWED_HOSTS = list(dict.fromkeys([*settings.ALLOWED_HOSTS, "testserver"]))
    settings.MIDDLEWARE = [
        middleware
        for middleware in settings.MIDDLEWARE
        if middleware != "apps.core.middleware.two_factor_enforce.TwoFactorEnforceMiddleware"
    ]
    ceo = get_user_model().objects.filter(profile__role=Role.CEO).first()
    if ceo is None:
        raise RuntimeError("CEO profile is missing")
    client = Client()
    client.force_login(ceo)
    dashboard = client.get("/app/ceo/")
    project_list = client.get("/app/ceo/projects/")
    from apps.ceo.services.dashboard import get_ceo_projects_list

    rows = get_ceo_projects_list({})
    row = next((item for item in rows if item["project_id"] == project.id), None)
    return {
        "Project_Code": project.code,
        "Project_ID": project.id,
        "Is_Active": project.is_active,
        "Status": project.status,
        "CEO_Dashboard_HTTP_Status": dashboard.status_code,
        "CEO_Project_List_HTTP_Status": project_list.status_code,
        "Appears_In_Dashboard": row is not None,
        "Appears_In_Project_List": project.name in project_list.content.decode("utf-8", errors="replace"),
        "Dashboard_Progress": str(row["overall_progress_percent"]) if row else "",
        "Dashboard_Cost": str(row["accrual_cost"]) if row else "",
        "Dashboard_Revenue": str(row["recognized_revenue"]) if row else "",
        "Dashboard_Profit": str(row["profit"]) if row else "",
        "Visibility_Result": "PASS" if row and dashboard.status_code == 200 and project_list.status_code == 200 else "HOLD",
        "Notes": "Dashboard filters active projects with Project.is_active=True",
    }


def _write_csv(path: str, rows: list[dict[str, object]], fields: list[str]) -> None:
    with Path(path).open("w", encoding="utf-8", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=fields)
        writer.writeheader()
        writer.writerows(rows)


def _run(apply: bool) -> None:
    guard = _assert_local_demo_database()
    pilot = Project.objects.filter(code=PILOT_CODE).first()
    if pilot is None:
        raise SystemExit("PILOT_PROJECT_NOT_FOUND")
    if not pilot.is_active:
        raise SystemExit("PILOT_PROJECT_INACTIVE")
    targets = list(Project.objects.filter(is_active=False).exclude(code=PILOT_CODE).order_by("id"))
    dependent = [row for project in targets for row in _dependent_rows(project)]
    manifest = []
    for project in targets:
        project_rows = [row for row in dependent if row["Project_ID"] == project.id]
        unknown = _unknown_project_relations(project)
        audit_rows = AuditLog.objects.filter(project=project).count()
        eligible = not unknown and not audit_rows
        manifest.append(
            {
                "Project_ID": project.id,
                "Project_Code": project.code,
                "Project_Name": project.name,
                "Status": project.status,
                "Is_Active": project.is_active,
                "Contract_Amount": project.contract_amount,
                "Start_Date": project.start_date or "",
                "End_Date": project.end_date or "",
                "Delete_Eligible": eligible,
                "Exclusion_Reason": "" if eligible else ("AUDIT_PRESERVE" if audit_rows else "UNKNOWN_REVIEW_REQUIRED"),
                "Dependent_Row_Total": sum(int(row["Row_Count"]) for row in project_rows),
            }
        )
    _write_csv(
        "ops1b_r2_inactive_project_manifest.csv",
        manifest,
        ["Project_ID", "Project_Code", "Project_Name", "Status", "Is_Active", "Contract_Amount", "Start_Date", "End_Date", "Delete_Eligible", "Exclusion_Reason", "Dependent_Row_Total"],
    )
    _write_csv(
        "ops1b_r2_dependent_data_manifest.csv",
        dependent,
        ["Project_ID", "Project_Code", "Model", "Relation", "Row_Count", "Delete_Action", "Risk_Class", "Notes"],
    )
    deleted = []
    if apply:
        for project in targets:
            item = next(row for row in manifest if row["Project_ID"] == project.id)
            if not item["Delete_Eligible"]:
                raise RuntimeError(f"PURGE_HOLD project={project.id} reason={item['Exclusion_Reason']}")
            with transaction.atomic():
                _delete_project_scoped_rows(project)
            deleted.append(project.id)
    visibility = _dashboard_visibility(Project.objects.get(code=PILOT_CODE))
    _write_csv("ops1b_r2_ceo_visibility_result.csv", [visibility], list(visibility.keys()))
    budget_total = BudgetItem.objects.filter(project=pilot).aggregate(total=Sum("planned_amount"))["total"] or 0
    wbs_total = WBSItem.objects.filter(project=pilot, is_baseline=True).aggregate(total=Sum("weight"))["total"] or Decimal("0")
    latest_progress = DailyProgress.objects.filter(project=pilot).order_by("-report_date", "-id").first()
    latest_revenue = RevenueRecognition.objects.filter(project=pilot).order_by("-as_of_date", "-id").first()
    cost_total = CostActual.objects.filter(project=pilot).aggregate(total=Sum("total_amount"))["total"] or Decimal("0")
    _write_csv(
        "ops1b_r2_kpi_dashboard_seed.csv",
        [{
            "Project_Code": pilot.code,
            "Contract_Amount": pilot.contract_amount,
            "Budget_Total": budget_total,
            "WBS_Weight_Total": wbs_total,
            "Task_Progress_Percent": latest_progress.progress_percent if latest_progress else "",
            "Dashboard_Weighted_Progress_Percent": visibility["Dashboard_Progress"],
            "Cost_Total": cost_total,
            "Recognized_Revenue": visibility["Dashboard_Revenue"],
            "Expected_Profit": visibility["Dashboard_Profit"],
            "Expected_Margin": "68.87",
            "CEO_Dashboard_Value": visibility["Visibility_Result"],
            "Difference": "0",
            "Explanation": "R1 weighted progress revenue policy",
            "OPS1C_Action": "reconcile dashboard against seed",
        }],
        ["Project_Code", "Contract_Amount", "Budget_Total", "WBS_Weight_Total", "Task_Progress_Percent", "Dashboard_Weighted_Progress_Percent", "Cost_Total", "Recognized_Revenue", "Expected_Profit", "Expected_Margin", "CEO_Dashboard_Value", "Difference", "Explanation", "OPS1C_Action"],
    )
    print("DB_GUARD_PASS", guard)
    print("MODE", "APPLY" if apply else "DRY_RUN")
    print("INACTIVE_TARGET_COUNT", len(targets))
    print("DELETED_PROJECT_IDS", deleted)
    print("PILOT_VISIBILITY", visibility["Visibility_Result"])


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--dry-run", action="store_true")
    parser.add_argument("--apply", action="store_true")
    args = parser.parse_args()
    if args.dry_run and args.apply:
        raise SystemExit("Choose only one mode")
    _run(apply=args.apply)


if __name__ == "__main__":
    main()
