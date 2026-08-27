from pathlib import Path
import re

paths = [
    Path("ops1b_input_rehearsal_report.md"),
    Path("ops1b_execution_log.csv"),
    Path("ops1b_input_result_matrix.csv"),
    Path("ops1b_data_issue_register.csv"),
    Path("ops1b_kpi_reconciliation_seed.csv"),
    Path("ops1b_manual_capture_notes.md"),
    Path("ops1b_evidence_manifest.csv"),
]

required = {
    "ops1b_input_rehearsal_report.md": ["종합 결론", "리허설 모드", "사용 데이터", "단계별 실행 결과", "CEO dashboard", "Closing", "AuditLog", "개인정보", "OPS-1C", "최종 판정"],
    "ops1b_execution_log.csv": ["Step", "Workflow", "Expected_Result", "Actual_Result", "PASS_FAIL_HOLD"],
    "ops1b_input_result_matrix.csv": ["Area", "Input_Item", "ERP_Target", "Entered", "Verified", "Result"],
    "ops1b_data_issue_register.csv": ["Issue_ID", "Severity", "P0_P1_P2", "Description", "Workaround", "Followup_Prompt"],
    "ops1b_kpi_reconciliation_seed.csv": ["Project_Code", "Contract_Amount", "Budget_Total", "Progress_Percent", "Cost_Total", "Recognized_Revenue", "Expected_Profit"],
}
pii_patterns = [
    ("raw_rrn", re.compile(r"\b\d{6}-[1-4]\d{6}\b")),
    ("raw_phone", re.compile(r"\b010-\d{4}-\d{4}\b")),
    ("raw_account_like", re.compile(r"\b\d{3,6}-\d{2,6}-\d{3,8}\b")),
]
bad_tokens = ["蹂댄", "移대", "源", "誘몃", "諛뺢", "沅뚰", "嫄댁", "癤"]

overall = True
for path in paths:
    reasons = []
    if not path.exists():
        reasons.append("file does not exist")
        text = ""
    else:
        text = path.read_text(encoding="utf-8-sig")
        if "\ufffd" in text:
            reasons.append("replacement character remains")
        if "??" in text:
            reasons.append("double question marks remain")
        if any(token in text for token in bad_tokens):
            reasons.append("mojibake token remains")
        for label, pattern in pii_patterns:
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
