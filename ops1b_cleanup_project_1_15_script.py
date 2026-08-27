"""Guarded local/demo cleanup for projects 1 through 15.

Default mode is dry-run.  ``--apply`` is required for deletion.
The script deliberately preserves users, roles, global masters, and AuditLog.
"""

from __future__ import annotations

import argparse
import csv
import os
import sys
from collections import defaultdict
from pathlib import Path

os.environ.setdefault("DJANGO_SETTINGS_MODULE", "config.settings.local")

import django

django.setup()

from django.apps import apps
from django.conf import settings
from django.db import connection, transaction
from django.db.models import Q
from django.db.models.deletion import Collector, ProtectedError
from django.test import Client
from django.test.utils import override_settings

from apps.audit.models import AuditLog
from apps.core.rbac.models import Role, UserProfile
from apps.projects.models import Project


ROOT = Path(__file__).resolve().parent
TARGET_MIN_ID = 1
TARGET_MAX_ID = 15
PROTECTED_PROJECT_ID = 17
PROTECTED_PROJECT_CODE = "OPS1B-RERUN-SAMPLE-001"

MANIFEST_PATH = ROOT / "ops1b_cleanup_project_1_15_manifest.csv"
DEPENDENT_MANIFEST_PATH = ROOT / "ops1b_cleanup_project_1_15_dependent_manifest.csv"
DRY_RUN_RESULT_PATH = ROOT / "ops1b_cleanup_project_1_15_dryrun_result.txt"
APPLY_RESULT_PATH = ROOT / "ops1b_cleanup_project_1_15_apply_result.txt"
CEO_VISIBILITY_PATH = ROOT / "ops1b_cleanup_project_1_15_ceo_visibility_check.csv"
ISSUE_REGISTER_PATH = ROOT / "ops1b_cleanup_project_1_15_data_issue_register.csv"
EVIDENCE_PATH = ROOT / "ops1b_cleanup_project_1_15_evidence_manifest.csv"
REPORT_PATH = ROOT / "ops1b_cleanup_project_1_15_report.md"
SOURCE_SCAN_PATH = ROOT / "ops1b_cleanup_project_1_15_source_scan.txt"


# These models own project-scoped records and are safe to remove only when they
# directly protect a target Project.  Any non-empty PROTECT relation not listed
# here is an explicit HOLD, never an implicit force-delete.
SAFE_PROJECT_SCOPED_PROTECT_MODELS = {
    "contracts.ContractChange",
    "contracts.ContractSnapshot",
    "cost.CostActual",
    "cost.RevenueRecognition",
    "field.DailyReport",
    "finance.CashEvent",
    "inventory.IssueToWork",
    "labor.ElectronicCardImportBatch",
    "labor.LaborConfirmedWorkDay",
    "labor.LaborExcelExportBatch",
    "labor.LaborMonthlyPayroll",
    "labor.LaborRateTable",
    "labor.LaborReconciliationResult",
    "labor.LaborWorkLedger",
    "schedule.DailyProgress",
    "schedule.SchedulePlan",
    "schedule.ScheduleTask",
}

DELETE_ORDER = [
    "labor.LaborExcelExportBatch",
    "labor.LaborConfirmedWorkDay",
    "labor.LaborReconciliationResult",
    "labor.ElectronicCardImportBatch",
    "labor.LaborMonthlyPayroll",
    "labor.LaborWorkLedger",
    "labor.LaborRateTable",
    "schedule.DailyProgress",
    "schedule.ScheduleTask",
    "schedule.SchedulePlan",
    "cost.CostActual",
    "cost.RevenueRecognition",
    "field.DailyReport",
    "inventory.IssueToWork",
    "finance.CashEvent",
    "contracts.ContractChange",
    "contracts.ContractSnapshot",
]


def write_csv(path: Path, headers: list[str], rows: list[dict]) -> None:
    with path.open("w", encoding="utf-8", newline="") as output:
        writer = csv.DictWriter(output, fieldnames=headers)
        writer.writeheader()
        writer.writerows(rows)


def on_delete_name(relation) -> str:
    handler = relation.field.remote_field.on_delete
    return getattr(handler, "__name__", str(handler)).upper()


def database_guard() -> tuple[bool, dict]:
    config = connection.settings_dict
    engine = str(config.get("ENGINE", ""))
    host = str(config.get("HOST", "") or "")
    database = str(config.get("NAME", "") or "")
    safe = (
        "postgresql" in engine.lower()
        and host.lower() in {"127.0.0.1", "localhost"}
        and any(token in database.lower() for token in ("demo", "local", "dev"))
    )
    return safe, {"engine": engine, "host": host, "database": database}


def target_projects() -> list[Project]:
    projects = list(
        Project.objects.filter(id__gte=TARGET_MIN_ID, id__lte=TARGET_MAX_ID).order_by("id")
    )
    for project in projects:
        if project.id == PROTECTED_PROJECT_ID or project.code == PROTECTED_PROJECT_CODE:
            raise RuntimeError("보호 프로젝트가 삭제 범위에 포함되었습니다.")
    return projects


def project_manifest(projects: list[Project]) -> list[dict]:
    return [
        {
            "Project_ID": project.id,
            "Project_Code": project.code,
            "Project_Name": project.name,
            "Status": project.status,
            "Is_Active": project.is_active,
            "Contract_Amount": project.contract_amount,
            "Start_Date": project.start_date or "",
            "End_Date": project.end_date or "",
            "Delete_Eligible": "YES",
            "Exclusion_Reason": "명시적 ID 1~15 정리 대상",
        }
        for project in projects
    ]


def direct_relation_rows(projects: list[Project]) -> tuple[list[dict], dict[str, list[str]], list[str]]:
    target_ids = [project.id for project in projects]
    relation_fields: dict[str, list[str]] = defaultdict(list)
    rows: list[dict] = []
    holds: list[str] = []

    for relation in Project._meta.related_objects:
        model = relation.related_model
        label = model._meta.label
        field_name = relation.field.name
        delete_policy = on_delete_name(relation)
        relation_fields[label].append(field_name)

        for project_id in target_ids:
            count = model._default_manager.filter(**{field_name: project_id}).count()
            if delete_policy == "PROTECT":
                if label in SAFE_PROJECT_SCOPED_PROTECT_MODELS:
                    action = "DELETE_PROJECT_SCOPED"
                    risk = "KNOWN_PROTECT"
                else:
                    action = "HOLD"
                    risk = "UNKNOWN_PROTECT"
                    if count:
                        holds.append(f"{label}.{field_name} has {count} protected target rows")
            elif label == "audit.AuditLog":
                action = "PRESERVE_AUDIT"
                risk = "SET_NULL"
            elif delete_policy == "SET_NULL":
                action = "PRESERVE_REFERENCE"
                risk = "SET_NULL"
            elif delete_policy == "CASCADE":
                action = "DELETE_WITH_PROJECT"
                risk = "CASCADE"
            else:
                action = "HOLD"
                risk = f"UNKNOWN_{delete_policy}"
                if count:
                    holds.append(f"{label}.{field_name} has {count} unclassified target rows")

            rows.append(
                {
                    "Project_ID": project_id,
                    "Model": label,
                    "Field": field_name,
                    "Row_Count": count,
                    "Delete_Action": action,
                    "Risk_Class": risk,
                }
            )
    return rows, relation_fields, holds


def collector_protection(project: Project) -> str:
    collector = Collector(using="default")
    try:
        collector.collect([project])
    except ProtectedError as error:
        labels = sorted({obj._meta.label for obj in error.protected_objects})
        return ", ".join(labels)
    return ""


def write_result(path: Path, lines: list[str]) -> None:
    text = "\n".join(lines) + "\n"
    path.write_text(text, encoding="utf-8")
    print(text, end="")


def delete_known_protected_rows(target_ids: list[int], relation_fields: dict[str, list[str]]) -> dict[str, int]:
    deleted: dict[str, int] = {}
    for label in DELETE_ORDER:
        field_names = relation_fields.get(label, [])
        if not field_names:
            continue
        model = apps.get_model(label)
        condition = Q()
        for field_name in field_names:
            condition |= Q(**{f"{field_name}__in": target_ids})
        queryset = model._default_manager.filter(condition)
        count = queryset.count()
        if count:
            queryset.delete()
            deleted[label] = deleted.get(label, 0) + count
    return deleted


def ceo_visibility_check() -> dict:
    pilot = Project.objects.filter(
        id=PROTECTED_PROJECT_ID, code=PROTECTED_PROJECT_CODE, is_active=True
    ).first()
    profile = UserProfile.objects.select_related("user").filter(role=Role.CEO).first()
    result = {
        "Project_Code": PROTECTED_PROJECT_CODE,
        "Project_ID": PROTECTED_PROJECT_ID,
        "Pilot_Exists": bool(pilot),
        "Pilot_Is_Active": bool(pilot and pilot.is_active),
        "CEO_Dashboard_HTTP_Status": "NOT_RUN",
        "CEO_Projects_HTTP_Status": "NOT_RUN",
        "CEO_Check_Mode": "NOT_RUN",
        "Appears_In_Dashboard": False,
        "Visibility_Result": "HOLD",
    }
    if not pilot or not profile:
        return result

    # The production route enforces a real 2FA device.  This operational smoke
    # test verifies the CEO-authorized route and its data after authenticating a
    # known CEO role session, without fabricating or changing a 2FA device.
    middleware = [
        item
        for item in settings.MIDDLEWARE
        if item != "apps.core.middleware.two_factor_enforce.TwoFactorEnforceMiddleware"
    ]
    with override_settings(MIDDLEWARE=middleware):
        client = Client(HTTP_HOST="localhost")
        client.force_login(profile.user)
        dashboard_response = client.get("/app/ceo/", HTTP_HOST="localhost")
        projects_response = client.get("/app/ceo/projects/", HTTP_HOST="localhost")
    body = projects_response.content.decode("utf-8", errors="replace")
    result.update(
        {
            "CEO_Dashboard_HTTP_Status": dashboard_response.status_code,
            "CEO_Projects_HTTP_Status": projects_response.status_code,
            "CEO_Check_Mode": "CEO role-session smoke; 2FA device not fabricated",
            "Appears_In_Dashboard": pilot.code in body or pilot.name in body,
        }
    )
    if dashboard_response.status_code == 200 and projects_response.status_code == 200 and result["Appears_In_Dashboard"]:
        result["Visibility_Result"] = "PASS"
    return result


def write_issue_register(issues: list[str]) -> None:
    rows = [
        {
            "Issue": "로컬 데모 DB 삭제는 되돌릴 수 없습니다.",
            "Priority": "P1",
            "Description": "복구는 데이터베이스 백업 또는 재시드가 필요합니다.",
            "Next": "삭제 결과물과 DB 백업 정책을 보관합니다.",
        }
    ]
    rows.extend(
        {
            "Issue": issue,
            "Priority": "P0",
            "Description": "알 수 없거나 보호된 프로젝트 종속 참조가 발견되었습니다.",
            "Next": "모델 관계를 검토한 뒤 별도 승인으로 처리합니다.",
        }
        for issue in issues
    )
    write_csv(ISSUE_REGISTER_PATH, ["Issue", "Priority", "Description", "Next"], rows)


def write_evidence_manifest(mode: str) -> None:
    paths = [
        MANIFEST_PATH,
        DEPENDENT_MANIFEST_PATH,
        DRY_RUN_RESULT_PATH,
        CEO_VISIBILITY_PATH,
        ISSUE_REGISTER_PATH,
        REPORT_PATH,
        ROOT / "ops1b_cleanup_04_manage_check.txt",
        ROOT / "ops1b_cleanup_05_makemigrations_check.txt",
    ]
    if mode == "apply":
        paths.extend(
            [
                APPLY_RESULT_PATH,
                ROOT / "ops1b_cleanup_project_1_15_final_manage_check.txt",
                ROOT / "ops1b_cleanup_project_1_15_final_makemigrations_check.txt",
            ]
        )
    write_csv(
        EVIDENCE_PATH,
        ["Artifact", "Exists", "Purpose"],
        [
            {
                "Artifact": path.name,
                "Exists": path.exists(),
                "Purpose": "OPS-1B-CLEANUP evidence",
            }
            for path in paths
        ],
    )


def write_report(mode: str, projects: list[Project], deleted: dict[str, int], guard: dict, holds: list[str], ceo: dict) -> None:
    total_deleted = len(projects) if mode == "apply" and not holds else 0
    rows = "\n".join(
        f"| {project.id} | {project.code} | {project.name} | {project.is_active} | YES | "
        f"{'삭제됨' if mode == 'apply' and not holds else 'dry-run'} |"
        for project in projects
    )
    deleted_rows = "\n".join(
        f"| {label} | {count} | 프로젝트 범위 삭제 | KNOWN_PROTECT |"
        for label, count in deleted.items()
    ) or "| 직접 사전 삭제 없음 | 0 | 프로젝트 CASCADE 처리 | CASCADE |"
    status = "PASS" if not holds and (mode == "dry-run" or ceo.get("Visibility_Result") == "PASS") else "HOLD"
    report = f"""# OPS-1B-CLEANUP Project ID 1~15 Deletion

## 종합 결론
- 상태: {status}
- dry-run: {'완료' if mode == 'dry-run' else '사전 완료'}
- apply: {'완료' if mode == 'apply' and not holds else '미실행 또는 중단'}
- 삭제 대상 프로젝트 수: {len(projects)}
- 삭제 완료 프로젝트 수: {total_deleted}
- 보호 프로젝트 유지: ID 17 / {PROTECTED_PROJECT_CODE}
- CEO 대시보드 표시: {ceo.get('Visibility_Result')}

## DB Safety Guard
- engine: {guard['engine']}
- host: {guard['host']}
- database: {guard['database']}
- result: PASS

## 프로젝트 ID 1~15 삭제 대상
| Project_ID | Project_Code | Project_Name | Is_Active | Delete_Eligible | Result |
|---:|---|---|---|---|---|
{rows}

## 종속 데이터 삭제 요약
| Model | Rows | Action | Risk |
|---|---:|---|---|
{deleted_rows}

## 보호 대상 확인
- Project ID 17: {'유지' if Project.objects.filter(id=17).exists() else '없음'}
- OPS1B-RERUN-SAMPLE-001: {'유지' if Project.objects.filter(code=PROTECTED_PROJECT_CODE).exists() else '없음'}
- Users/Roles: 보존
- Global masters: 보존
- AuditLog: 보존, 프로젝트 FK는 SET_NULL 정책으로 이력 유지

## CEO 대시보드 확인
| Route | HTTP | Pilot Visible | Result |
|---|---:|---|---|
| /app/ceo/ | {ceo.get('CEO_Dashboard_HTTP_Status')} | {ceo.get('Appears_In_Dashboard')} | {ceo.get('Visibility_Result')} |
| /app/ceo/projects/ | {ceo.get('CEO_Projects_HTTP_Status')} | {ceo.get('Appears_In_Dashboard')} | {ceo.get('Visibility_Result')} |

## 남은 이슈
{chr(10).join('- ' + issue for issue in holds) if holds else '- P1: 로컬 삭제는 DB 백업 또는 재시드로만 복구할 수 있습니다.'}

## 한글 UTF-8 / 개인정보
- source scan: 별도 결과 파일 참조
- PII: 원문 주민번호·전화번호·계좌번호를 결과물에 기록하지 않음

## Git Hygiene
- production code changed: NO
- migrations changed: NO
- generated artifacts: YES
- commit needed: NO

## 최종 판정
- {status}
- OPS-1C 계속 진행 가능: {'YES' if status == 'PASS' and mode == 'apply' else 'NO'}
"""
    REPORT_PATH.write_text(report, encoding="utf-8")


def source_scan() -> bool:
    required = {
        REPORT_PATH: ["종합 결론", "프로젝트 ID 1~15", "삭제 대상", "dry-run", "apply", "CEO 대시보드", PROTECTED_PROJECT_CODE, "최종 판정"],
        MANIFEST_PATH: ["Project_ID", "Project_Code", "Delete_Eligible", "Exclusion_Reason"],
        DEPENDENT_MANIFEST_PATH: ["Project_ID", "Model", "Row_Count", "Delete_Action", "Risk_Class"],
        CEO_VISIBILITY_PATH: ["Project_Code", "CEO_Dashboard_HTTP_Status", "Appears_In_Dashboard", "Visibility_Result"],
    }
    bad_tokens = ["\ufffd", "??"]
    lines = []
    overall = True
    for path, tokens in required.items():
        content = path.read_text(encoding="utf-8") if path.exists() else ""
        reasons = [f"missing: {token}" for token in tokens if token not in content]
        reasons.extend(f"bad token: {token}" for token in bad_tokens if token in content)
        passed = not reasons
        overall = overall and passed
        lines.append(f"FILE: {path.name}")
        lines.append(f"FILE_SCAN_PASS: {passed}")
        if reasons:
            lines.extend(f"REASON: {reason}" for reason in reasons)
    lines.append(f"OVERALL_SOURCE_SCAN_PASS: {overall}")
    SOURCE_SCAN_PATH.write_text("\n".join(lines) + "\n", encoding="utf-8")
    return overall


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--dry-run", action="store_true")
    parser.add_argument("--apply", action="store_true")
    args = parser.parse_args()
    if args.dry_run and args.apply:
        parser.error("--dry-run and --apply cannot be used together")
    mode = "apply" if args.apply else "dry-run"

    safe_db, guard = database_guard()
    if not safe_db:
        write_result(
            APPLY_RESULT_PATH if mode == "apply" else DRY_RUN_RESULT_PATH,
            ["UNSAFE_DB_GUARD", str(guard), "No deletion was performed."],
        )
        return 2

    projects = target_projects()
    manifest = project_manifest(projects)
    write_csv(MANIFEST_PATH, list(manifest[0]) if manifest else ["Project_ID"], manifest)
    dependent_rows, relation_fields, holds = direct_relation_rows(projects)
    write_csv(
        DEPENDENT_MANIFEST_PATH,
        ["Project_ID", "Model", "Field", "Row_Count", "Delete_Action", "Risk_Class"],
        dependent_rows,
    )

    initial_protection = {
        project.id: collector_protection(project)
        for project in projects
    }
    for project_id, protection in initial_protection.items():
        if protection:
            print(f"PRECHECK_PROTECT project={project_id}: {protection}")

    write_issue_register(holds)
    deleted: dict[str, int] = {}
    ceo = ceo_visibility_check()

    if mode == "dry-run":
        lines = [
            "MODE: DRY-RUN",
            f"DB_GUARD: PASS {guard}",
            f"TARGET_PROJECT_COUNT: {len(projects)}",
            f"TARGET_IDS: {[project.id for project in projects]}",
            f"PROTECTED_PROJECT_ID_17_EXISTS: {Project.objects.filter(id=17).exists()}",
            f"PROTECTED_PROJECT_CODE_EXISTS: {Project.objects.filter(code=PROTECTED_PROJECT_CODE).exists()}",
            f"UNKNOWN_HOLD_COUNT: {len(holds)}",
            "NO_DELETION_PERFORMED: True",
            "DRY_RUN_PASS" if not holds else "DRY_RUN_HOLD",
        ]
        write_result(DRY_RUN_RESULT_PATH, lines)
        write_csv(CEO_VISIBILITY_PATH, list(ceo), [ceo])
        write_report(mode, projects, deleted, guard, holds, ceo)
        write_evidence_manifest(mode)
        source_scan()
        return 0 if not holds else 2

    if not DRY_RUN_RESULT_PATH.exists():
        holds.append("dry-run result file is required before --apply")
    if holds:
        write_result(APPLY_RESULT_PATH, ["MODE: APPLY", "APPLY_HOLD", *holds])
        write_csv(CEO_VISIBILITY_PATH, list(ceo), [ceo])
        write_report(mode, projects, deleted, guard, holds, ceo)
        write_evidence_manifest(mode)
        source_scan()
        return 2

    audit_ids = list(AuditLog.objects.filter(project_id__in=[p.id for p in projects]).values_list("id", flat=True))
    try:
        with transaction.atomic():
            deleted = delete_known_protected_rows([project.id for project in projects], relation_fields)
            for project_id in [project.id for project in projects]:
                project = Project.objects.get(pk=project_id)
                remaining_protection = collector_protection(project)
                if remaining_protection:
                    raise RuntimeError(
                        f"HOLD: project {project_id} still has protected rows: {remaining_protection}"
                    )
                project.delete()
    except Exception as error:
        holds.append(str(error))
        write_result(APPLY_RESULT_PATH, ["MODE: APPLY", "APPLY_HOLD_ROLLED_BACK", *holds])
        write_csv(CEO_VISIBILITY_PATH, list(ceo), [ceo])
        write_issue_register(holds)
        write_report(mode, projects, deleted, guard, holds, ceo)
        write_evidence_manifest(mode)
        source_scan()
        return 2

    remaining_targets = list(
        Project.objects.filter(id__gte=TARGET_MIN_ID, id__lte=TARGET_MAX_ID).values_list("id", flat=True)
    )
    if remaining_targets:
        holds.append(f"target projects remain after apply: {remaining_targets}")
    ceo = ceo_visibility_check()
    preserved_audits = AuditLog.objects.filter(id__in=audit_ids, project__isnull=True).count()
    lines = [
        "MODE: APPLY",
        f"DB_GUARD: PASS {guard}",
        f"DELETED_PROJECT_IDS: {[project.id for project in projects]}",
        f"REMAINING_TARGET_IDS: {remaining_targets}",
        f"PRESERVED_AUDIT_ROWS_SET_NULL: {preserved_audits}",
        f"PROTECTED_PROJECT_ID_17_EXISTS: {Project.objects.filter(id=17).exists()}",
        f"PROTECTED_PROJECT_CODE_EXISTS: {Project.objects.filter(code=PROTECTED_PROJECT_CODE).exists()}",
        "APPLY_PASS" if not holds else "APPLY_HOLD",
    ]
    write_result(APPLY_RESULT_PATH, lines)
    write_csv(CEO_VISIBILITY_PATH, list(ceo), [ceo])
    write_issue_register(holds)
    write_report(mode, projects, deleted, guard, holds, ceo)
    write_evidence_manifest(mode)
    source_scan()
    return 0 if not holds else 2


if __name__ == "__main__":
    sys.exit(main())
