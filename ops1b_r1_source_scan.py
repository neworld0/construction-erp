from pathlib import Path
import re

paths = [
    Path("ops1b_r1_wbs_revenue_alignment_report.md"),
    Path("ops1b_r1_wbs_baseline_policy.csv"),
    Path("ops1b_r1_revenue_policy.csv"),
    Path("ops1b_r1_kpi_reconciliation_seed.csv"),
    Path("ops1b_r1_data_issue_register.csv"),
    Path("ops1b_r1_evidence_manifest.csv"),
]
required = {
    "ops1b_r1_wbs_revenue_alignment_report.md": ["종합 결론", "WBS", "기타공정", "수익 인식 정책", "KPI 재계산", "OPS-1C", "최종 판정"],
    "ops1b_r1_wbs_baseline_policy.csv": ["Project_Code", "WBS_Code", "WBS_Name", "Weight_Before", "Weight_After", "Budget_Before", "Budget_After"],
    "ops1b_r1_revenue_policy.csv": ["Policy_ID", "PROGRESS_BASED_PROVISIONAL", "recognized_revenue = contract_amount", "weighted dashboard progress"],
    "ops1b_r1_kpi_reconciliation_seed.csv": ["Project_Code", "Contract_Amount", "Budget_Total_Before", "Budget_Total_After", "Dashboard_Weighted_Progress_Percent", "Recognized_Revenue_After", "Expected_Profit_After"],
    "ops1b_r1_data_issue_register.csv": ["Issue_ID", "OPS1BR-001", "OPS1BR-002", "OPS1BR-003", "P0_P1_P2"],
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
