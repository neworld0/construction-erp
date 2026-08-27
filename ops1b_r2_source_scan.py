from pathlib import Path
import re

paths = [
    Path("ops1b_r2_inactive_purge_ceo_visibility_report.md"),
    Path("ops1b_r2_inactive_project_manifest.csv"),
    Path("ops1b_r2_dependent_data_manifest.csv"),
    Path("ops1b_r2_ceo_visibility_result.csv"),
    Path("ops1b_r2_kpi_dashboard_seed.csv"),
    Path("ops1b_r2_data_issue_register.csv"),
    Path("ops1b_r2_evidence_manifest.csv"),
]
required = {
    "ops1b_r2_inactive_purge_ceo_visibility_report.md": ["종합 결론", "inactive 프로젝트", "삭제 manifest", "CEO 대시보드", "OPS1B-RERUN-SAMPLE-001", "최종 판정"],
    "ops1b_r2_inactive_project_manifest.csv": ["Project_ID", "Project_Code", "Delete_Eligible", "Dependent_Row_Total"],
    "ops1b_r2_dependent_data_manifest.csv": ["Project_ID", "Model", "Row_Count", "Delete_Action", "Risk_Class"],
    "ops1b_r2_ceo_visibility_result.csv": ["Project_Code", "CEO_Dashboard_HTTP_Status", "Appears_In_Dashboard", "Visibility_Result"],
    "ops1b_r2_kpi_dashboard_seed.csv": ["Project_Code", "Contract_Amount", "Budget_Total", "Dashboard_Weighted_Progress_Percent", "Recognized_Revenue", "Expected_Profit"],
}
patterns = [
    ("raw_rrn", re.compile(r"\b\d{6}-[1-4]\d{6}\b")),
    ("raw_phone", re.compile(r"\b010-\d{4}-\d{4}\b")),
    ("raw_account", re.compile(r"\b\d{3,6}-\d{2,6}-\d{3,8}\b")),
]
bad_tokens = ["蹂댄", "移대", "源", "誘몃", "諛뺢", "沅뚰", "嫄댁", "癤"]

overall = True
for path in paths:
    text = path.read_text(encoding="utf-8-sig") if path.exists() else ""
    reasons = []
    if not path.exists():
        reasons.append("file does not exist")
    if chr(0xFFFD) in text or "??" in text:
        reasons.append("replacement or question mark corruption remains")
    if any(token in text for token in bad_tokens):
        reasons.append("mojibake token remains")
    for label, pattern in patterns:
        if pattern.search(text):
            reasons.append(f"possible {label}")
    missing = [value for value in required.get(path.name, []) if value not in text]
    if missing:
        reasons.append("missing required: " + ", ".join(missing))
    print("FILE:", path)
    print("BAD_REASONS:", reasons)
    print("MISSING_REQUIRED:", missing)
    print("FILE_SCAN_PASS:", not reasons)
    overall = overall and not reasons
print("OVERALL_SOURCE_SCAN_PASS:", overall)
