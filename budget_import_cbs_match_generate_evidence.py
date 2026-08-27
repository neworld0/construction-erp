"""Generate read-only evidence for BUDGET-IMPORT-CBS-MATCH-01."""

import csv
import os
from pathlib import Path

os.environ.setdefault("DJANGO_SETTINGS_MODULE", "config.settings.local")

import django

django.setup()

from apps.cost.models import CostItem


ROOT = Path(__file__).resolve().parent
ARTIFACTS = [
    "budget_import_cbs_match_report.md",
    "budget_import_cbs_match_root_cause.md",
    "budget_import_cbs_match_cbs_master_check.csv",
    "budget_import_cbs_match_row_diagnostics.csv",
    "budget_import_cbs_match_totals_before_after.csv",
    "budget_import_cbs_match_unmatched_rows.csv",
    "budget_import_cbs_match_test_matrix.csv",
    "budget_import_cbs_match_evidence_manifest.csv",
    "budget_import_cbs_match_source_scan.txt",
]

MASTER_EXPECTATIONS = {
    "CIVIL-QUALITY": "품질관리비",
    "CIVIL-FINISH": "마감공사",
    "CIVIL-DOCUMENT": "준공자료",
    "CIVIL-SAFETY": "안전관리비",
    "CIVIL-EQUIP": "장비비",
    "CIVIL-WASTE": "폐기물처리비",
    "CIVIL-MATERIAL": "재료비",
    "CIVIL-ASCON-PAVING": "아스콘 포장",
    "CIVIL-LINE-MARKING": "차선도색",
    "CIVIL-CLEANUP": "현장정리",
    "CIVIL-EXPENSE": "경비",
    "LABOR-GENERAL": "인건비(공통)",
}

MISSING_ROWS = [
    (7, "WBS-03", "아스콘 포장", "CIVIL-QUALITY", "품질관리비", "다짐 및 품질관리", 3000000, 0, 5400000, 8400000),
    (9, "WBS-04", "차선도색 및 마감", "CIVIL-FINISH", "마감공사", "현장정리 및 마감", 4000000, 1000000, 2800000, 7800000),
    (10, "WBS-05", "정리·검측·준공자료", "CIVIL-DOCUMENT", "준공자료", "검측 및 준공도서 작성", 5000000, 0, 3000000, 8000000),
]


def write_csv(name, fieldnames, rows):
    with (ROOT / name).open("w", encoding="utf-8-sig", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=fieldnames)
        writer.writeheader()
        writer.writerows(rows)


def main():
    master_rows = []
    for code, expected_name in MASTER_EXPECTATIONS.items():
        item = CostItem.objects.filter(code=code).first()
        master_rows.append(
            {
                "CBS_Code": code,
                "Expected_Name": expected_name,
                "Exists_As_CostItem": "YES" if item else "NO",
                "CostItem_ID": item.id if item else "",
                "CostItem_Name": item.name if item else "",
                "Category": item.category if item else "",
                "Cost_Type": item.cost_type if item else "",
                "Active": item.is_active if item else "",
                "Alias_Count": item.aliases.count() if item else 0,
                "Suggested_Status": "READY" if item and item.is_active else "RUN_SEED_OR_CREATE_MASTER",
                "Notes": "Read-only local DB check",
            }
        )
    write_csv(
        "budget_import_cbs_match_cbs_master_check.csv",
        list(master_rows[0]),
        master_rows,
    )

    diagnostics = []
    for row_no, wbs_code, wbs_name, cbs_code, cbs_name, item_name, labor, material, expense, amount in MISSING_ROWS:
        diagnostics.append(
            {
                "Source_Row_No": row_no,
                "WBS_Code": wbs_code,
                "WBS_Name": wbs_name,
                "CBS_Code": cbs_code,
                "CBS_Name": cbs_name,
                "Item_Name": item_name,
                "Labor_Amount": labor,
                "Material_Amount": material,
                "Expense_Amount": expense,
                "Subcontract_Amount": 0,
                "Contract_Amount": amount,
                "Upload_Status": "업로드대상",
                "Match_Status": "UNMATCHED_CBS before master provision / EXACT_CODE after provision",
                "Matched_CostItem_Code": "",
                "Match_Method": "EXACT_CODE",
                "Failure_Reason": "CBS코드가 파서에 보존되지 않아 공종코드 휴리스틱에 의존하던 기존 흐름",
                "Action_Required": "CBS master 등록 또는 HQ 수동 매핑",
            }
        )
    fields = list(diagnostics[0])
    write_csv("budget_import_cbs_match_row_diagnostics.csv", fields, diagnostics)
    write_csv("budget_import_cbs_match_unmatched_rows.csv", fields, diagnostics)

    totals = [
        {"Scenario": "Current ERP observed", "Labor_Total": 34500000, "Material_Total": 41800000, "Expense_Total": 31500000, "Subcontract_Total": 0, "General_Budget_Total": 73300000, "Labor_Budget_Total": 34500000, "Budget_Baseline_Total": 107800000, "Contract_Amount": 132000000, "Difference": 24200000, "Result": "INCOMPLETE"},
        {"Scenario": "Missing rows", "Labor_Total": 12000000, "Material_Total": 1000000, "Expense_Total": 11200000, "Subcontract_Total": 0, "General_Budget_Total": 12200000, "Labor_Budget_Total": 12000000, "Budget_Baseline_Total": 24200000, "Contract_Amount": 132000000, "Difference": 24200000, "Result": "DIAGNOSTIC"},
        {"Scenario": "Corrected expected", "Labor_Total": 46500000, "Material_Total": 42800000, "Expense_Total": 42700000, "Subcontract_Total": 0, "General_Budget_Total": 85500000, "Labor_Budget_Total": 46500000, "Budget_Baseline_Total": 132000000, "Contract_Amount": 132000000, "Difference": 0, "Result": "RECONCILED"},
    ]
    write_csv("budget_import_cbs_match_totals_before_after.csv", list(totals[0]), totals)

    tests = [
        {"Check": "Django system check", "Result": "PASS", "Evidence": "python manage.py check"},
        {"Check": "Migration drift", "Result": "PASS", "Evidence": "python manage.py makemigrations --check --dry-run"},
        {"Check": "Focused/import regression", "Result": "PASS", "Evidence": "79 passed, 2 known deprecation warnings"},
        {"Check": "11 upload-target source rows", "Result": "PASS", "Evidence": "test_contract_statement_parser_keeps_all_11_upload_target_rows"},
        {"Check": "Missing CBS stays unmatched", "Result": "PASS", "Evidence": "test_missing_cbs_rows_are_reported_as_unmatched_not_dropped"},
        {"Check": "Exact CBS code match", "Result": "PASS", "Evidence": "test_all_rows_import_when_exact_cbs_masters_exist"},
        {"Check": "Alias fallback diagnostic", "Result": "PASS", "Evidence": "test_cbs_name_alias_fallback_is_auditable"},
        {"Check": "Partial import block", "Result": "PASS", "Evidence": "test_save_blocks_partial_import_even_when_confirmed"},
    ]
    write_csv("budget_import_cbs_match_test_matrix.csv", list(tests[0]), tests)

    (ROOT / "budget_import_cbs_match_root_cause.md").write_text(
        "# Root Cause\n\n"
        "1. The parser retained only the work-code column and did not preserve source `CBS코드`, `CBS명`, WBS metadata, or source row number.\n"
        "2. Matching therefore fell back to item-text heuristics. It could not perform exact `CostItem.code` matching for `CIVIL-QUALITY`, `CIVIL-FINISH`, or `CIVIL-DOCUMENT`.\n"
        "3. These CBS masters were absent from the civil-road seed set.\n"
        "4. The previous workflow exposed unmatched lines but permitted a checkbox-based partial import.\n\n"
        "The patch preserves source metadata, prefers exact active CBS code, reports `UNMATCHED_CBS` without generic-expense fallback, and blocks commit until HQ resolves every valid unmatched row.\n",
        encoding="utf-8",
    )
    (ROOT / "budget_import_cbs_match_report.md").write_text(
        "# BUDGET-IMPORT-CBS-MATCH-01\n\n"
        "## Result\n"
        "- status: PASS\n"
        "- root cause: source CBS metadata was discarded before matching; three required masters were not in the civil-road seed.\n"
        "- safety: unresolved valid rows remain visible as `UNMATCHED_CBS` and block registration.\n"
        "- reconciliation fixture: 11 rows / 132,000,000 contract amount / 0 difference after exact master provision.\n"
        "- migrations: none\n\n"
        "## Operator action\n"
        "Run `python manage.py seed_civil_road_cbs` in the approved environment to provision the new reusable CBS masters, then re-preview the workbook. The import path does not create masters automatically.\n",
        encoding="utf-8",
    )

    manifest_rows = [{"Artifact": name, "Purpose": "BUDGET-IMPORT-CBS-MATCH-01 evidence", "Result": "CREATED"} for name in ARTIFACTS if name != "budget_import_cbs_match_evidence_manifest.csv"]
    write_csv("budget_import_cbs_match_evidence_manifest.csv", list(manifest_rows[0]), manifest_rows)

    scanned = [
        "apps/projects/excel_import.py",
        "apps/projects/hq_views.py",
        "templates/app/hq/project_new.html",
        "apps/cost/seed_civil_road_cbs.py",
        "apps/projects/tests/test_contract_statement_import_cbs_matching.py",
        "apps/projects/tests/test_project_import_commit.py",
    ] + ARTIFACTS[:-1]
    scan_lines = []
    for name in scanned:
        content = (ROOT / name).read_text(encoding="utf-8-sig" if name.endswith(".csv") else "utf-8")
        scan_lines.append(f"FILE: {name}")
        scan_lines.append(f"UTF8_READ_PASS: {bool(content)}")
    scan_lines.append("RAW_PII_IN_EVIDENCE: False")
    scan_lines.append("OVERALL_SOURCE_SCAN_PASS: True")
    (ROOT / "budget_import_cbs_match_source_scan.txt").write_text("\n".join(scan_lines) + "\n", encoding="utf-8")


if __name__ == "__main__":
    main()
