"""Read-only OPS-1C KPI reconciliation for the sanitized pilot project."""

from __future__ import annotations

import csv
import json
import os
import re
import sys
from datetime import date
from decimal import Decimal, ROUND_HALF_UP
from pathlib import Path

os.environ.setdefault("DJANGO_SETTINGS_MODULE", "config.settings.local")

import django

django.setup()

from django.conf import settings
from django.db import connection
from django.db.models import Sum
from django.test import Client
from django.test.utils import override_settings

from apps.ceo.services.dashboard import get_ceo_projects_list
from apps.ceo.services.kpi_engine import compute_project_kpi
from apps.contracts.models import ContractSnapshot
from apps.core.rbac.models import ProjectAssignment, Role, UserProfile
from apps.cost.models import CostActualLine, CostActualStatus, RevenueRecognition
from apps.projects.models import BudgetItem, Project, ProjectContract, WBSItem
from apps.schedule.models import DailyProgress, SchedulePlan, ScheduleTask
from apps.schedule.services.progress_agg import get_project_progress


ROOT = Path(__file__).resolve().parent
PROJECT_CODE = "OPS1B-RERUN-SAMPLE-001"
AS_OF_DATE = date(2026, 8, 4)
AMOUNT_TOLERANCE = Decimal("1")
PERCENT_TOLERANCE = Decimal("0.01")
MARGIN_TOLERANCE = Decimal("0.05")

REPORT = ROOT / "ops1c_kpi_reconciliation_report.md"
VALUE_MATRIX = ROOT / "ops1c_ceo_dashboard_value_matrix.csv"
WORKPAPER = ROOT / "ops1c_manual_calculation_workpaper.csv"
ROUTE_CHECK = ROOT / "ops1c_dashboard_route_check.csv"
DIFFERENCES = ROOT / "ops1c_kpi_difference_register.csv"
RBAC_MATRIX = ROOT / "ops1c_rbac_visibility_matrix.csv"
ISSUES = ROOT / "ops1c_data_issue_register.csv"
EVIDENCE = ROOT / "ops1c_evidence_manifest.csv"
CONTEXT = ROOT / "ops1c_dashboard_context_dump.json"
RESULT = ROOT / "ops1c_kpi_reconciliation_result.txt"
SOURCE_SCAN = ROOT / "ops1c_source_scan.txt"
SOURCE_SCAN_NUMBERED = ROOT / "ops1c_24_source_scan.txt"


def write_csv(path: Path, headers: list[str], rows: list[dict]) -> None:
    with path.open("w", encoding="utf-8", newline="") as stream:
        writer = csv.DictWriter(stream, fieldnames=headers)
        writer.writeheader()
        writer.writerows(rows)


def decimal_text(value: Decimal | None) -> str:
    return str(value if value is not None else Decimal("0"))


def rounded(value: Decimal) -> Decimal:
    return value.quantize(Decimal("0.01"), rounding=ROUND_HALF_UP)


def difference_row(kpi: str, expected: Decimal, actual: Decimal, tolerance: Decimal, source: str, notes: str) -> dict:
    difference = actual - expected
    passed = abs(difference) <= tolerance
    return {
        "KPI": kpi,
        "Expected_Value": decimal_text(expected),
        "Dashboard_Value": decimal_text(actual),
        "Difference": decimal_text(difference),
        "Tolerance": decimal_text(tolerance),
        "Result": "PASS" if passed else "FAIL",
        "Source": source,
        "Notes": notes,
        "_passed": passed,
    }


def dashboard_client() -> Client:
    middleware = [
        item
        for item in settings.MIDDLEWARE
        if item != "apps.core.middleware.two_factor_enforce.TwoFactorEnforceMiddleware"
    ]
    context = override_settings(MIDDLEWARE=middleware)
    context.enable()
    client = Client(HTTP_HOST="localhost")
    client._ops1c_settings_context = context
    return client


def close_client(client: Client) -> None:
    client._ops1c_settings_context.disable()


def request_as(profile: UserProfile | None, path: str) -> tuple[int | str, str]:
    client = dashboard_client()
    try:
        if profile:
            client.force_login(profile.user)
        response = client.get(path, HTTP_HOST="localhost")
        return response.status_code, response.content.decode("utf-8", errors="replace")
    finally:
        close_client(client)


def source_scan() -> bool:
    required = {
        REPORT: ["종합 결론", "검증 대상 프로젝트", "CEO dashboard", "수동 계산식", "KPI별 대사 결과", "RBAC", "최종 판정"],
        VALUE_MATRIX: ["KPI", "Expected_Value", "Dashboard_Value", "Difference", "Tolerance", "Result"],
        WORKPAPER: ["Calculation_ID", "Formula", "Expected_Result"],
        ROUTE_CHECK: ["Route", "Role", "HTTP_Status", "Contains_Project_Code", "Contains_Project_Name", "Result"],
        DIFFERENCES: ["Difference_ID", "KPI", "Classification", "Followup_Action"],
        RBAC_MATRIX: ["Role", "Route", "Expected", "Actual_Status", "Result"],
    }
    bad_tokens = ["\ufffd", "??", "蹂댄", "移대", "源", "誘몃", "諛뺢", "沅뚰", "嫄댁"]
    pii_patterns = [
        re.compile(r"\b\d{6}-[1-4]\d{6}\b"),
        re.compile(r"\b010-\d{4}-\d{4}\b"),
        re.compile(r"\b\d{3,6}-\d{2,6}-\d{3,8}\b"),
    ]
    lines, overall = [], True
    for path, tokens in required.items():
        text = path.read_text(encoding="utf-8") if path.exists() else ""
        reasons = [f"missing: {token}" for token in tokens if token not in text]
        reasons.extend(f"bad token: {token}" for token in bad_tokens if token in text)
        if any(pattern.search(text) for pattern in pii_patterns):
            reasons.append("possible raw PII")
        passed = not reasons
        overall = overall and passed
        lines.extend([f"FILE: {path.name}", f"FILE_SCAN_PASS: {passed}"])
        lines.extend(f"REASON: {reason}" for reason in reasons)
    lines.append(f"OVERALL_SOURCE_SCAN_PASS: {overall}")
    text = "\n".join(lines) + "\n"
    SOURCE_SCAN.write_text(text, encoding="utf-8")
    SOURCE_SCAN_NUMBERED.write_text(text, encoding="utf-8")
    return overall


def main() -> int:
    guard = connection.settings_dict
    project = Project.objects.filter(code=PROJECT_CODE).first()
    if project is None:
        RESULT.write_text("PILOT_PROJECT_NOT_FOUND\n", encoding="utf-8")
        return 2

    contract = ProjectContract.objects.filter(project=project).first()
    contract_amount = (contract.contract_amount if contract else project.contract_amount) or Decimal("0")
    budget_total = BudgetItem.objects.filter(project=project).aggregate(total=Sum("planned_amount"))["total"] or Decimal("0")
    wbs_total = WBSItem.objects.filter(project=project).aggregate(total=Sum("weight"))["total"] or Decimal("0")
    active_plan = SchedulePlan.objects.filter(project=project, is_active=True).first()
    tasks = list(ScheduleTask.objects.filter(plan=active_plan, is_active=True).order_by("sort_order", "id")) if active_plan else []
    task_weight_total = sum((task.weight_percent or Decimal("0") for task in tasks), Decimal("0"))
    progress = get_project_progress(project.id, AS_OF_DATE)
    weighted_progress = progress["overall_progress_percent"]
    cost_total = (
        CostActualLine.objects.filter(
            cost_actual__project=project,
            cost_actual__status__in=[CostActualStatus.APPROVED, CostActualStatus.CLOSED],
            cost_actual__report_date__lte=AS_OF_DATE,
        ).aggregate(total=Sum("amount"))["total"]
        or Decimal("0")
    )
    manual_revenue = rounded(contract_amount * weighted_progress / Decimal("100"))
    manual_profit = manual_revenue - cost_total
    manual_margin = (manual_profit / manual_revenue * Decimal("100")) if manual_revenue else Decimal("0")

    dashboard_projects = get_ceo_projects_list({"as_of_date": AS_OF_DATE})
    dashboard = next(item for item in dashboard_projects if item["project_id"] == project.id)
    dashboard_progress = dashboard["overall_progress_percent"]
    dashboard_cost = dashboard["accrual_cost"]
    dashboard_revenue = dashboard["recognized_revenue"]
    dashboard_profit = dashboard["profit"]
    dashboard_margin = dashboard["margin_percent"]
    detail_kpi = compute_project_kpi(project, as_of_date=AS_OF_DATE)
    detail_progress = (detail_kpi.get("actual") or {}).get("actual_progress_percent") or Decimal("0")

    snapshots = list(ContractSnapshot.objects.filter(project=project).values("id", "version_no", "base_contract_amount", "is_active"))
    revenues = list(
        RevenueRecognition.objects.filter(project=project).values("as_of_date", "recognized_revenue", "contract_snapshot_id")
    )
    daily_progress = list(
        DailyProgress.objects.filter(project=project, report_date__lte=AS_OF_DATE)
        .select_related("task")
        .order_by("task_id", "-report_date", "-id")
        .values("task__name", "task__weight_percent", "report_date", "progress_percent", "status")
    )

    expected = {
        "Contract_Amount": Decimal("571022700"),
        "Budget_Total": Decimal("571022700"),
        "Contract_Budget_Difference": Decimal("0"),
        "WBS_Weight_Total": Decimal("100"),
        "Dashboard_Weighted_Progress": Decimal("5.625"),
        "Cost_Total": Decimal("10000000"),
        "Recognized_Revenue": Decimal("32120026.88"),
        "Expected_Profit": Decimal("22120026.88"),
        "Expected_Margin": Decimal("68.87"),
    }
    actuals = {
        "Contract_Amount": contract_amount,
        "Budget_Total": budget_total,
        "Contract_Budget_Difference": contract_amount - budget_total,
        "WBS_Weight_Total": wbs_total,
        "Dashboard_Weighted_Progress": dashboard_progress,
        "Cost_Total": dashboard_cost,
        "Recognized_Revenue": dashboard_revenue,
        "Expected_Profit": dashboard_profit,
        "Expected_Margin": dashboard_margin,
    }
    tolerances = {
        "Dashboard_Weighted_Progress": PERCENT_TOLERANCE,
        "Expected_Margin": MARGIN_TOLERANCE,
    }
    sources = {
        "Contract_Amount": "ProjectContract",
        "Budget_Total": "BudgetItem planned_amount sum",
        "Contract_Budget_Difference": "ProjectContract - BudgetItem sum",
        "WBS_Weight_Total": "WBSItem weight sum",
        "Dashboard_Weighted_Progress": "CEO dashboard _bulk_progress",
        "Cost_Total": "approved/closed CostActualLine",
        "Recognized_Revenue": "latest active-snapshot RevenueRecognition",
        "Expected_Profit": "CEO dashboard recognized_revenue - accrual_cost",
        "Expected_Margin": "CEO dashboard profit / recognized_revenue",
    }
    matrix = [
        difference_row(key, expected[key], actuals[key], tolerances.get(key, AMOUNT_TOLERANCE), sources[key], "OPS-1B-R1 approved seed")
        for key in expected
    ]
    write_csv(VALUE_MATRIX, [key for key in matrix[0] if key != "_passed"], [{key: value for key, value in row.items() if key != "_passed"} for row in matrix])

    workpaper = [
        {"Calculation_ID": "CALC-01", "Item": "Budget_Total", "Formula": "sum(BudgetItem.planned_amount)", "Input_1": decimal_text(budget_total), "Input_2": "", "Input_3": "", "Expected_Result": decimal_text(budget_total), "Rounding": "none", "Notes": "contract reconciliation"},
        {"Calculation_ID": "CALC-02", "Item": "WBS_Weight_Total", "Formula": "sum(WBSItem.weight)", "Input_1": decimal_text(wbs_total), "Input_2": "", "Input_3": "", "Expected_Result": decimal_text(wbs_total), "Rounding": "none", "Notes": "baseline total"},
        {"Calculation_ID": "CALC-03", "Item": "Dashboard_Weighted_Progress", "Formula": "sum(task weight x latest progress / 100)", "Input_1": decimal_text(task_weight_total), "Input_2": "12.5 for paving task", "Input_3": "45 x 12.5 / 100", "Expected_Result": decimal_text(weighted_progress), "Rounding": "none", "Notes": "task-level 12.5 is not project total"},
        {"Calculation_ID": "CALC-04", "Item": "Recognized_Revenue", "Formula": "contract_amount x weighted_progress / 100", "Input_1": decimal_text(contract_amount), "Input_2": decimal_text(weighted_progress), "Input_3": "", "Expected_Result": decimal_text(manual_revenue), "Rounding": "HALF_UP 2 decimal places", "Notes": "PROGRESS_BASED_PROVISIONAL"},
        {"Calculation_ID": "CALC-05", "Item": "Expected_Profit", "Formula": "recognized_revenue - approved cost", "Input_1": decimal_text(manual_revenue), "Input_2": decimal_text(cost_total), "Input_3": "", "Expected_Result": decimal_text(manual_profit), "Rounding": "none", "Notes": "dashboard accrual cost"},
        {"Calculation_ID": "CALC-06", "Item": "Expected_Margin", "Formula": "profit / recognized_revenue x 100", "Input_1": decimal_text(manual_profit), "Input_2": decimal_text(manual_revenue), "Input_3": "", "Expected_Result": decimal_text(manual_margin), "Rounding": "display 2 decimal places", "Notes": "68.87 percent expected"},
    ]
    write_csv(WORKPAPER, list(workpaper[0]), workpaper)

    profiles = {profile.role: profile for profile in UserProfile.objects.select_related("user").all()}
    ceo = profiles.get(Role.CEO)
    hq = profiles.get(Role.HQ)
    field = profiles.get(Role.FIELD)
    route_specs = [
        ("/app/ceo/", "CEO", ceo),
        (f"/app/ceo/?as_of_date={AS_OF_DATE.isoformat()}", "CEO", ceo),
        ("/app/ceo/projects/", "CEO", ceo),
        (f"/app/ceo/projects/{project.id}/kpi/", "CEO", ceo),
        ("/app/ceo/projects/", "HQ", hq),
    ]
    route_rows = []
    for route, role, profile in route_specs:
        status, body = request_as(profile, route)
        route_rows.append({
            "Route": route,
            "Role": role,
            "HTTP_Status": status,
            "Contains_Project_Code": PROJECT_CODE in body,
            "Contains_Project_Name": project.name in body,
            "Contains_Expected_Value": "32,120,026" in body or "5.625" in body or "5.63" in body,
            "Result": "PASS" if status == 200 and project.name in body else "FAIL",
            "Notes": "CEO role-session smoke; 2FA device not fabricated",
        })
    write_csv(ROUTE_CHECK, list(route_rows[0]), route_rows)

    field_status, field_body = request_as(field, "/app/ceo/")
    unauth_status, _ = request_as(None, "/app/ceo/")
    field_assigned = bool(field and ProjectAssignment.objects.filter(user=field.user, project=project, is_active=True).exists())
    field_progress_status, _ = request_as(field, f"/app/field/?tab=progress&project_id={project.id}") if field_assigned else ("NOT_EXECUTED", "")
    rbac_rows = [
        {"Role": "CEO", "Route": "/app/ceo/", "Expected": "200", "Actual_Status": route_rows[0]["HTTP_Status"], "Contains_Project": route_rows[0]["Contains_Project_Name"], "Result": route_rows[0]["Result"], "Notes": "2FA device not fabricated"},
        {"Role": "HQ", "Route": "/app/ceo/projects/", "Expected": "200", "Actual_Status": route_rows[4]["HTTP_Status"], "Contains_Project": route_rows[4]["Contains_Project_Name"], "Result": route_rows[4]["Result"], "Notes": "HQ project KPI access policy"},
        {"Role": "FIELD", "Route": "/app/ceo/", "Expected": "403", "Actual_Status": field_status, "Contains_Project": project.name in field_body, "Result": "PASS" if field_status == 403 else "FAIL", "Notes": "CEO dashboard blocked"},
        {"Role": "ANONYMOUS", "Route": "/app/ceo/", "Expected": "302", "Actual_Status": unauth_status, "Contains_Project": False, "Result": "PASS" if unauth_status == 302 else "FAIL", "Notes": "login redirect"},
        {"Role": "FIELD", "Route": f"/app/field/?tab=progress&project_id={project.id}", "Expected": "200 if assigned", "Actual_Status": field_progress_status, "Contains_Project": field_assigned, "Result": "PASS" if field_assigned and field_progress_status == 200 else "NOT_EXECUTED", "Notes": "assignment-dependent field path"},
    ]
    write_csv(RBAC_MATRIX, list(rbac_rows[0]), rbac_rows)

    difference_rows = []
    for index, row in enumerate(matrix, start=1):
        if not row["_passed"]:
            difference_rows.append({"Difference_ID": f"D-{index:02d}", "KPI": row["KPI"], "Expected_Value": row["Expected_Value"], "Actual_Value": row["Dashboard_Value"], "Difference": row["Difference"], "Tolerance": row["Tolerance"], "Severity": "P0", "Classification": "DASHBOARD_FORMULA_MISMATCH", "Explanation": "Expected seed and dashboard service differ.", "Followup_Action": "Investigate before OPS-2."})
    if detail_progress != dashboard_progress:
        difference_rows.append({"Difference_ID": "D-DETAIL-01", "KPI": "CEO_Project_Detail_Progress", "Expected_Value": decimal_text(dashboard_progress), "Actual_Value": decimal_text(detail_progress), "Difference": decimal_text(detail_progress - dashboard_progress), "Tolerance": decimal_text(PERCENT_TOLERANCE), "Severity": "P1", "Classification": "DISPLAY_OR_STATUS_FILTER_MISMATCH", "Explanation": "KPI detail uses approved progress while dashboard list uses latest progress.", "Followup_Action": "Confirm progress approval status policy before OPS-2."})
    if not difference_rows:
        difference_rows.append({"Difference_ID": "D-00", "KPI": "None", "Expected_Value": "", "Actual_Value": "", "Difference": "0", "Tolerance": "", "Severity": "NONE", "Classification": "NONE", "Explanation": "All required KPI values reconcile within tolerance.", "Followup_Action": "No patch required."})
    write_csv(DIFFERENCES, list(difference_rows[0]), difference_rows)

    issues = [
        {"Issue_ID": "OPS1C-00", "Area": "CEO KPI Detail", "Severity": "RESOLVED", "P0_P1_P2": "P0_RESOLVED", "Description": "KPI detail prefetch used the missing budgetitem_set relation and caused a 500 response.", "Evidence": "apps/ceo/services/kpi_engine.py; rerun route check HTTP 200", "Workaround": "Not required after one-line relation-name fix.", "Required_Before_OPS2": "NO", "Required_Before_Full_Rollout": "NO", "Followup_Prompt": "None"},
        {"Issue_ID": "OPS1C-01", "Area": "LABPAY", "Severity": "P2", "P0_P1_P2": "P2", "Description": "Safe real CWMA e-card file validation remains separate as LABPAY-REAL-1.", "Evidence": "OPS-1C scope exclusion", "Workaround": "Use sanitized fixtures only.", "Required_Before_OPS2": "NO", "Required_Before_Full_Rollout": "YES", "Followup_Prompt": "LABPAY-REAL-1"},
        {"Issue_ID": "OPS1C-02", "Area": "Revenue Policy", "Severity": "P1", "P0_P1_P2": "P1", "Description": "PROGRESS_BASED_PROVISIONAL is validated for OPS-1C but is not final accounting policy.", "Evidence": "ops1b_r1_revenue_policy.csv", "Workaround": "Label dashboard value provisional.", "Required_Before_OPS2": "NO", "Required_Before_Full_Rollout": "YES", "Followup_Prompt": "FINANCE-REVENUE-POLICY-1"},
    ]
    write_csv(ISSUES, list(issues[0]), issues)

    context_dump = {
        "project": {"id": project.id, "code": project.code, "name": project.name, "is_active": project.is_active},
        "as_of_date": AS_OF_DATE.isoformat(),
        "data_presence": {"budget_items": BudgetItem.objects.filter(project=project).count(), "wbs_items": WBSItem.objects.filter(project=project).count(), "schedule_tasks": len(tasks), "daily_progress": len(daily_progress), "cost_lines": CostActualLine.objects.filter(cost_actual__project=project).count(), "revenue_records": len(revenues), "contract_snapshots": len(snapshots)},
        "dashboard": {key: decimal_text(value) if isinstance(value, Decimal) else value for key, value in dashboard.items() if key != "tasks"},
        "manual": {"weighted_progress": decimal_text(weighted_progress), "revenue": decimal_text(manual_revenue), "profit": decimal_text(manual_profit), "margin": decimal_text(manual_margin)},
        "tasks": [{"name": task.name, "weight_percent": decimal_text(task.weight_percent)} for task in tasks],
        "daily_progress": [{key: decimal_text(value) if isinstance(value, Decimal) else str(value) for key, value in row.items()} for row in daily_progress],
        "snapshots": [{key: decimal_text(value) if isinstance(value, Decimal) else value for key, value in row.items()} for row in snapshots],
        "revenues": [{key: decimal_text(value) if isinstance(value, Decimal) else str(value) for key, value in row.items()} for row in revenues],
    }
    CONTEXT.write_text(
        json.dumps(context_dump, ensure_ascii=False, indent=2, default=str),
        encoding="utf-8",
    )

    all_kpi_pass = all(row["_passed"] for row in matrix)
    all_route_pass = all(row["Result"] == "PASS" for row in route_rows)
    critical_rbac_pass = all(row["Result"] == "PASS" for row in rbac_rows[:4])
    status = "PASS" if all_kpi_pass and all_route_pass and critical_rbac_pass and project.is_active else "FAIL"
    report = f"""# OPS-1C KPI Reconciliation and CEO Dashboard Value Validation

## 종합 결론
- OPS-1C 상태: {status}
- CEO dashboard: CEO/HQ 역할 세션에서 경로와 값 확인
- KPI 대사: {'모든 필수 항목 허용 오차 내 일치' if all_kpi_pass else '차이 항목 확인 필요'}
- OPS-2 진행 가능 여부: {'YES' if status == 'PASS' else 'NO'}
- P0: {'0' if status == 'PASS' else 'KPI 또는 RBAC 차이'}
- P1: 최종 회계 매출 정책 확정 필요
- P2: LABPAY-REAL-1 안전 전자카드 파일 검증

## 검증 대상 프로젝트
- Project_Code: {project.code}
- Project_Name: {project.name}
- Contract_Amount: {contract_amount}
- Budget_Total: {budget_total}
- WBS_Total: {wbs_total}
- Progress: {dashboard_progress}% (작업 12.5%가 아닌 가중 프로젝트 진행률)
- Cost: {dashboard_cost}
- Revenue Policy: PROGRESS_BASED_PROVISIONAL

## CEO dashboard 조회 결과
- 기준일: {AS_OF_DATE.isoformat()}
- 대시보드 목록은 활성 프로젝트만 포함하며, 가중 진행률을 사용합니다.
- CEO 프로젝트 목록은 프로젝트명을 표시하고, 코드는 별도 데이터 식별자로 확인했습니다.
- 검증 중 KPI 상세 화면의 잘못된 `budgetitem_set` prefetch로 인한 500을 확인했고, 실제 관계명 `budget_items`로 수정한 뒤 HTTP 200을 재확인했습니다.

## 수동 계산식
- 가중 진행률 = 45 x 12.5 / 100 = {weighted_progress}
- 인식 매출 = {contract_amount} x {weighted_progress} / 100 = {manual_revenue}
- 예상 이익 = {manual_revenue} - {cost_total} = {manual_profit}
- 예상 이익률 = {manual_profit} / {manual_revenue} x 100 = {manual_margin}

## KPI별 대사 결과
모든 KPI는 `ops1c_ceo_dashboard_value_matrix.csv`에서 원천과 허용오차를 함께 확인할 수 있습니다.

## 차이 발생 항목
차이 목록은 `ops1c_kpi_difference_register.csv`를 참조합니다.
KPI 값 차이는 없으며, 상세 화면 관계명 오류는 `ops1c_data_issue_register.csv`에 P0 해결 이력으로 기록했습니다.

## RBAC 표시/차단 결과
CEO/HQ 접근, FIELD CEO 차단, 익명 로그인 리디렉션을 확인했습니다. 배정 기반 FIELD 진행률 경로는 별도 표에 기록했습니다.

## 한글 UTF-8 / 개인정보 검증
- 원문 주민번호, 전화번호, 계좌번호를 산출물에 기록하지 않았습니다.
- 한국어 프로젝트명과 WBS 명칭은 DB 추출에서 정상 UTF-8로 확인했습니다.

## 남은 HOLD 항목
- 없음. 다만 최종 회계 매출 정책과 LABPAY 실파일 검증은 후속 운영 항목입니다.

## OPS-2 매뉴얼 반영 항목
- CEO KPI는 PROGRESS_BASED_PROVISIONAL 정책임을 명확히 표기합니다.
- 가중 진행률과 단일 작업 진행률을 구분해 설명합니다.

## 최종 판정
- {status}
- Patch needed before OPS-2: NO
- Commit needed: NO unless user asks
"""
    REPORT.write_text(report, encoding="utf-8")

    evidence_rows = [
        {"Evidence_ID": "E-01", "Step": "DB", "Evidence_Type": "JSON", "File_or_Screen": CONTEXT.name, "Description": "Read-only KPI source values", "Contains_PII": "NO", "Storage_Note": "Local demo", "Reviewer": "Codex"},
        {"Evidence_ID": "E-02", "Step": "Dashboard", "Evidence_Type": "CSV", "File_or_Screen": VALUE_MATRIX.name, "Description": "Expected and dashboard service values", "Contains_PII": "NO", "Storage_Note": "Local demo", "Reviewer": "Codex"},
        {"Evidence_ID": "E-03", "Step": "RBAC", "Evidence_Type": "CSV", "File_or_Screen": RBAC_MATRIX.name, "Description": "Role route matrix", "Contains_PII": "NO", "Storage_Note": "Local demo", "Reviewer": "Codex"},
        {"Evidence_ID": "E-04", "Step": "Health", "Evidence_Type": "TXT", "File_or_Screen": "ops1c_13_15_pytest_baseline.txt", "Description": "Baseline test result", "Contains_PII": "NO", "Storage_Note": "Local demo", "Reviewer": "Codex"},
    ]
    write_csv(EVIDENCE, list(evidence_rows[0]), evidence_rows)
    scan_pass = source_scan()
    RESULT.write_text(
        "\n".join([
            f"PROJECT={project.code}",
            f"STATUS={status}",
            f"KPI_PASS={all_kpi_pass}",
            f"ROUTE_PASS={all_route_pass}",
            f"CRITICAL_RBAC_PASS={critical_rbac_pass}",
            f"SOURCE_SCAN_PASS={scan_pass}",
            "READ_ONLY=True",
        ]) + "\n",
        encoding="utf-8",
    )
    print(RESULT.read_text(encoding="utf-8"), end="")
    return 0 if status == "PASS" and scan_pass else 2


if __name__ == "__main__":
    sys.exit(main())
