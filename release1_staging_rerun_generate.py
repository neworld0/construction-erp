"""Generate a truthful HOLD evidence pack when staging rerun access is incomplete."""

from __future__ import annotations

import csv
import re
from pathlib import Path


ROOT = Path(__file__).resolve().parent


def write(name: str, text: str) -> None:
    (ROOT / name).write_text(text.strip() + "\n", encoding="utf-8")


def write_csv(name: str, headers: list[str], rows: list[tuple]) -> None:
    with (ROOT / name).open("w", encoding="utf-8", newline="") as stream:
        writer = csv.writer(stream)
        writer.writerow(headers)
        writer.writerows(rows)


def scan() -> bool:
    required = {
        "release1_staging_rerun_report.md": ["종합 결론", "Access Pack", "Linux staging", "Gunicorn", "Nginx", "restore", "healthz", "CEO", "HQ", "FIELD", "LABPAY", "RBAC", "최종 판정"],
        "release1_staging_rerun_access_completeness_check.csv": ["Input_ID", "Provided_Status", "Authority_Status", "Blocks_Rerun", "Result"],
        "release1_staging_rerun_host_identity_check.md": ["host identifier", "OS", "service account", "DB classification", "Result"],
        "release1_staging_rerun_code_commit_verification.md": ["branch", "commit", "LABPAY", "migration", "Result"],
        "release1_staging_rerun_django_environment_check.md": ["settings module", "DEBUG", "SECRET_KEY", "ALLOWED_HOSTS", "CSRF", "WSGI_IMPORT_OK", "Result"],
        "release1_staging_rerun_gunicorn_verification.md": ["GUNICORN_IMPORT_OK", "WSGI_IMPORT_OK", "service", "workers", "timeout", "Result"],
        "release1_staging_rerun_nginx_verification.md": ["nginx -t", "proxy_pass", "static", "media", "X-Forwarded-Proto", "Result"],
        "release1_staging_rerun_restore_safety_check.md": ["restore target", "isolated", "not production", "backup checksum", "Result"],
        "release1_staging_rerun_backup_archive_verification.md": ["backup filename", "checksum", "pg_restore", "Result"],
        "release1_staging_rerun_restore_drill_report.md": ["restore executed", "target DB", "migration", "AuditLog", "raw PII printed", "Result"],
        "release1_staging_rerun_healthcheck_smoke_matrix.csv": ["Check_ID", "Route_or_Command", "Expected", "Actual", "HTTP_Status", "Result"],
        "release1_staging_rerun_rbac_smoke_matrix.csv": ["Role", "Route", "Expected", "Actual_Status", "Result"],
        "release1_staging_rerun_static_media_policy_check.md": ["STATIC_ROOT", "MEDIA_ROOT", "static", "media", "Excel", "Result"],
        "release1_staging_rerun_security_check.md": ["DEBUG", "SECRET_KEY", "ALLOWED_HOSTS", "CSRF", "SESSION_COOKIE_SECURE", "raw PII", "Result"],
        "release1_staging_rerun_labpay_performance_check.md": ["LABPAY", "e-card-imports", "Elapsed", "grouped-count", "Result"],
        "release1_staging_rerun_labpay_performance_matrix.csv": ["Run_ID", "Route", "Elapsed_Seconds", "Result"],
        "release1_staging_rerun_open_issue_register.csv": ["Issue_ID", "Area", "P0_P1_P2", "Required_Before_Staging", "Required_Before_Production"],
        "release1_staging_rerun_release_readiness_matrix.csv": ["Area", "Check_Item", "Current_Status", "Result", "Severity"],
        "release1_staging_rerun_evidence_manifest.csv": ["Evidence_ID", "Step", "Evidence_Type", "File", "Contains_Secret", "Contains_PII"],
    }
    bad = ["\ufffd", "??", "蹂댄", "移대", "源", "誘몃", "諛뺢", "沅뚰", "嫄댁"]
    secret = [re.compile(r"SECRET_KEY\s*=\s*['\"][^'\"]{12,}['\"]"), re.compile(r"(?:PASSWORD|DB_PASSWORD|AWS_SECRET_ACCESS_KEY)\s*=\s*['\"][^'\"]+['\"]", re.I), re.compile(r"AKIA[0-9A-Z]{16}"), re.compile(r"(?:postgres|postgresql)://[^:\s]+:[^@\s]+@", re.I)]
    pii = [re.compile(r"\b\d{6}-[1-4]\d{6}\b"), re.compile(r"\b010-\d{4}-\d{4}\b"), re.compile(r"\b\d{3,6}-\d{2,6}-\d{3,8}\b")]
    lines, overall = [], True
    for name, tokens in required.items():
        text = (ROOT / name).read_text(encoding="utf-8") if (ROOT / name).exists() else ""
        reasons = [f"missing required token: {token}" for token in tokens if token not in text]
        reasons.extend(f"bad token: {token}" for token in bad if token in text)
        for pattern in secret + pii:
            reasons.extend(f"sensitive pattern: {value}" for value in pattern.findall(text))
        passed = not reasons
        overall = overall and passed
        lines.extend([f"FILE: {name}", f"FILE_SCAN_PASS: {passed}", *(f"REASON: {reason}" for reason in reasons)])
    lines.append(f"OVERALL_SOURCE_SCAN_PASS: {overall}")
    write("release1_staging_rerun_source_scan.txt", "\n".join(lines))
    return overall


def main() -> None:
    inputs = [
        ("I-01", "Host", "Linux staging host identifier and SSH method"),
        ("I-02", "Service", "service account, project root, and virtualenv path"),
        ("I-03", "Release", "deployment branch and immutable commit"),
        ("I-04", "Settings", "settings module and secure env-file path"),
        ("I-05", "Database", "staging DB host classification and non-production proof"),
        ("I-06", "Restore", "isolated restore target and CREATEDB/pre-created approval"),
        ("I-07", "Backup", "backup archive location and checksum"),
        ("I-08", "Proxy", "Gunicorn/Nginx service paths and execution authority"),
        ("I-09", "Media", "media access, backup, and retention policy"),
        ("I-10", "RBAC", "staging-safe CEO/HQ/FIELD test users"),
        ("I-11", "Approval", "release owner smoke rerun approval"),
    ]
    write_csv("release1_staging_rerun_access_completeness_check.csv", ["Input_ID", "Area", "Required_Input", "Provided_Status", "Authority_Status", "Blocks_Rerun", "Blocks_Staging_Pilot", "Evidence", "Result", "Notes"], [
        (*item, "MISSING", "MISSING", "YES", "YES", "release1_staging_smoke_rerun_input_manifest.csv", "HOLD", "Access Pack placeholder not completed")
        for item in inputs
    ])
    write("release1_staging_rerun_host_identity_check.md", """
# Staging host identity check

- host identifier: NOT_PROVIDED
- OS: NOT_EXECUTED; no Linux staging session
- service account: NOT_PROVIDED
- project path: NOT_PROVIDED
- venv path: NOT_PROVIDED
- branch/commit on host: NOT_EXECUTED
- DB classification: UNKNOWN
- production DB connected: NOT_VERIFIED
- Result: HOLD. No host command was run because the Access Pack is incomplete.
""")
    write("release1_staging_rerun_code_commit_verification.md", """
# Code and commit verification

- branch: local branch only; deployment branch not provided
- commit: deployment commit not provided
- LABPAY: grouped-count performance patch is committed in 8613d5b
- migration: no migration file is dirty locally
- Result: HOLD. The LABPAY patch is committed; provide the immutable deployment commit through the Access Pack before host verification.
""")
    write("release1_staging_rerun_django_environment_check.md", """
# Django environment check

- settings module: NOT_PROVIDED for staging
- DEBUG: NOT_VERIFIED on staging
- SECRET_KEY: NOT_VERIFIED on staging; value not requested
- ALLOWED_HOSTS: NOT_VERIFIED on staging
- CSRF: NOT_VERIFIED on staging
- DB class: UNKNOWN; no remote DB operation was performed
- WSGI_IMPORT_OK: local evidence only
- Result: HOLD. Run this check only after the secure staging environment path is approved.
""")
    write("release1_staging_rerun_gunicorn_verification.md", """
# Gunicorn verification

- GUNICORN_IMPORT_OK: NOT_EXECUTED; Linux staging service is unavailable
- WSGI_IMPORT_OK: local evidence only
- service: NOT_PROVIDED
- workers: NOT_PROVIDED
- timeout: NOT_PROVIDED
- restart performed: NO
- Result: HOLD. No systemctl command was attempted.
""")
    write("release1_staging_rerun_nginx_verification.md", """
# Nginx verification

- nginx -t: NOT_EXECUTED; no authorized Linux staging host
- proxy_pass: NOT_VERIFIED
- static: NOT_VERIFIED
- media: NOT_VERIFIED
- X-Forwarded-Proto: NOT_VERIFIED
- reload performed: NO
- Result: HOLD. No Nginx command or configuration was changed.
""")
    write("release1_staging_rerun_restore_safety_check.md", """
# Restore safety check

- restore target: NOT_PROVIDED
- isolated: NOT_VERIFIED
- not production: NOT_VERIFIED
- backup checksum: NOT_PROVIDED for staging archive
- CREATEDB/pre-created authority: NOT_PROVIDED
- Result: HOLD. Restore was not attempted; active and production databases remain untouched.
""")
    write("release1_staging_rerun_backup_archive_verification.md", """
# Backup archive verification

- backup filename: NOT_PROVIDED
- checksum: NOT_PROVIDED
- pg_restore: NOT_EXECUTED on staging host
- Result: HOLD. Local demo archive evidence does not substitute for approved staging restore input.
""")
    write("release1_staging_rerun_restore_drill_report.md", """
# Restore drill report

- restore executed: NO
- target DB: NOT_PROVIDED
- migration state: NOT_EXECUTED
- project count: NOT_EXECUTED
- AuditLog count: NOT_EXECUTED
- raw PII printed: NO
- cleanup performed: NO
- Result: HOLD. Safe stop before any restore operation because the Access Pack is incomplete.
""")
    health_rows = [
        ("R-01", "Django", "python manage.py check", "PASS", "PASS (local)", "-", "-", "PASS", "P0", "local preflight"),
        ("R-02", "Migration", "makemigrations --check --dry-run", "No changes", "No changes (local)", "-", "-", "PASS", "P0", "local preflight"),
        ("R-03", "WSGI", "staging WSGI import", "WSGI_IMPORT_OK", "NOT_EXECUTED_ACCESS_GATE", "-", "-", "HOLD", "P1", "host input missing"),
        ("R-04", "Gunicorn", "service status", "active", "NOT_EXECUTED_ACCESS_GATE", "-", "-", "HOLD", "P1", "host input missing"),
        ("R-05", "Nginx", "nginx -t", "successful", "NOT_EXECUTED_ACCESS_GATE", "-", "-", "HOLD", "P1", "host input missing"),
        ("R-06", "Health", "/healthz/", "200 <2s", "NOT_EXECUTED_ACCESS_GATE", "-", "-", "HOLD", "P1", "staging endpoint missing"),
        ("R-07", "Auth", "/login/", "200 <3s", "NOT_EXECUTED_ACCESS_GATE", "-", "-", "HOLD", "P1", "safe account missing"),
        ("R-08", "CEO", "/app/ceo/", "200 <5s", "NOT_EXECUTED_ACCESS_GATE", "-", "-", "HOLD", "P1", "safe account missing"),
        ("R-09", "HQ", "/app/hq/", "200 <5s", "NOT_EXECUTED_ACCESS_GATE", "-", "-", "HOLD", "P1", "safe account missing"),
        ("R-10", "LABPAY", "/app/hq/labor/e-card-imports/", "200 <5s", "NOT_EXECUTED_ACCESS_GATE", "-", "-", "HOLD", "P1", "safe account missing"),
        ("R-11", "FIELD", "assigned progress", "200 <5s", "NOT_EXECUTED_ACCESS_GATE", "-", "-", "HOLD", "P1", "safe account missing"),
        ("R-12", "Static/media", "proxy policy", "approved", "NOT_EXECUTED_ACCESS_GATE", "-", "-", "HOLD", "P1", "host config missing"),
    ]
    write_csv("release1_staging_rerun_healthcheck_smoke_matrix.csv", ["Check_ID", "Area", "Route_or_Command", "Expected", "Actual", "HTTP_Status", "Elapsed_Seconds", "Result", "Severity", "Notes"], health_rows)
    rbac_rows = [
        ("ANONYMOUS", "/app/ceo/", "302/403", "NOT_EXECUTED_ACCESS_GATE", "NO", "HOLD", "staging endpoint missing"),
        ("CEO", "/app/ceo/", "200", "NOT_EXECUTED_ACCESS_GATE", "safe test account", "HOLD", "input missing"),
        ("HQ", "/app/hq/", "200", "NOT_EXECUTED_ACCESS_GATE", "safe test account", "HOLD", "input missing"),
        ("HQ", "/app/hq/labor/e-card-imports/", "200", "NOT_EXECUTED_ACCESS_GATE", "masked LABPAY", "HOLD", "input missing"),
        ("FIELD", "assigned progress", "200", "NOT_EXECUTED_ACCESS_GATE", "assigned project", "HOLD", "input missing"),
        ("FIELD", "/app/ceo/", "403", "NOT_EXECUTED_ACCESS_GATE", "NO", "HOLD", "input missing"),
        ("FIELD", "/app/hq/labor/e-card-imports/", "403", "NOT_EXECUTED_ACCESS_GATE", "NO", "HOLD", "input missing"),
        ("FIELD", "HQ project/budget", "403", "NOT_EXECUTED_ACCESS_GATE", "NO", "HOLD", "input missing"),
    ]
    write_csv("release1_staging_rerun_rbac_smoke_matrix.csv", ["Role", "Route", "Expected", "Actual_Status", "Contains_Protected_Data", "Result", "Notes"], rbac_rows)
    write("release1_staging_rerun_static_media_policy_check.md", """
# Static / media / upload policy

- STATIC_ROOT: local dry-run evidence only
- MEDIA_ROOT: staging path not provided
- static: staging Nginx rule not verified
- media: staging policy not provided
- Excel: generated/uploaded Excel staging storage not verified
- Korean filename: not tested on staging
- Result: HOLD. Do not enable unrestricted upload/download scope before media policy approval.
""")
    write("release1_staging_rerun_security_check.md", """
# Security check

- DEBUG: NOT_VERIFIED on staging
- SECRET_KEY: status NOT_VERIFIED; value not printed
- ALLOWED_HOSTS: NOT_VERIFIED on staging
- CSRF: NOT_VERIFIED on staging
- SESSION_COOKIE_SECURE: NOT_VERIFIED on staging
- raw PII: NO raw PII printed in rerun artifacts
- secret exposure: NO secret values printed
- Result: HOLD until secure environment status is provided and checked on host.
""")
    write("release1_staging_rerun_labpay_performance_check.md", """
# LABPAY performance recheck

LABPAY `/app/hq/labor/e-card-imports/` cannot be measured on staging because no staging endpoint or HQ test account was supplied. Local accepted evidence remains: grouped-count patch committed in `8613d5b`, cold run 0.367431 seconds, warm run about 0.008 seconds. Elapsed staging measurement is NOT_EXECUTED. Result: HOLD.
""")
    write_csv("release1_staging_rerun_labpay_performance_matrix.csv", ["Run_ID", "Route", "Batch_Count", "Raw_Row_Count", "Day_Row_Count", "Reconciliation_Row_Count", "SQL_Query_Count", "Elapsed_Seconds", "Result", "Notes"], [
        ("LR-01", "/app/hq/labor/e-card-imports/", "NOT_EXECUTED", "NOT_EXECUTED", "NOT_EXECUTED", "NOT_EXECUTED", "NOT_EXECUTED", "NOT_EXECUTED", "HOLD", "staging endpoint/HQ account not provided"),
    ])
    write_csv("release1_staging_rerun_open_issue_register.csv", ["Issue_ID", "Area", "P0_P1_P2", "Current_Status", "Required_Before_Staging", "Required_Before_Production", "Next_Action", "Notes"], [
        ("RR-01", "Access Pack", "P1", "INCOMPLETE", "YES", "YES", "complete 11 required inputs", "blocks rerun"),
        ("RR-02", "Host", "P1", "NOT_PROVIDED", "YES", "YES", "provide Linux staging host and authority", ""),
        ("RR-03", "Restore", "P1", "NOT_AUTHORIZED", "YES", "YES", "provide isolated DB and CREATEDB/pre-created approval", ""),
        ("RR-04", "Media", "P1", "PENDING", "YES", "YES", "approve media backup/access policy", ""),
        ("RR-05", "LABPAY", "P2", "SAFE_REAL_FILE_PENDING", "NO", "YES", "sanitized real-file verification", "separate gate"),
        ("RR-06", "Finance", "P1", "REVENUE_POLICY_PENDING", "NO", "YES", "finance policy approval", "separate gate"),
    ])
    write_csv("release1_staging_rerun_release_readiness_matrix.csv", ["Area", "Check_Item", "Current_Status", "Result", "Severity", "Evidence", "Next"], [
        ("Access", "required inputs", "11 MISSING", "HOLD", "P1", "release1_staging_rerun_access_completeness_check.csv", "complete Access Pack"),
        ("Application", "local preflight", "PASS", "PASS", "P0", "release1_staging_rerun_12_local_manage_check.txt", "retain evidence"),
        ("LABPAY", "patch status", "COMMITTED_8613d5b", "PASS", "P0", "release1_staging_rerun_code_commit_verification.md", "include 8613d5b in the staging deployment commit"),
        ("Host", "Linux staging/Gunicorn/Nginx", "NOT_EXECUTED", "HOLD", "P1", "host verification docs", "provide host"),
        ("Restore", "isolated restore", "NOT_EXECUTED", "HOLD", "P1", "restore safety check", "provide authority"),
        ("Security", "host configuration", "NOT_EXECUTED", "HOLD", "P1", "security check", "provide env status"),
    ])
    write_csv("release1_staging_rerun_evidence_manifest.csv", ["Evidence_ID", "Step", "Evidence_Type", "File", "Description", "Contains_Secret", "Contains_PII", "Reviewer", "Notes"], [
        ("RR-E01", "Access gate", "CSV", "release1_staging_rerun_access_completeness_check.csv", "missing-input stop gate", "NO", "NO", "release owner", "no host action"),
        ("RR-E02", "Local preflight", "TXT", "release1_staging_rerun_12_local_manage_check.txt", "Django check", "NO", "NO", "release owner", "pass"),
        ("RR-E03", "Host", "MD", "release1_staging_rerun_host_identity_check.md", "no fabricated host facts", "NO", "NO", "infra", "hold"),
        ("RR-E04", "Restore", "MD", "release1_staging_rerun_restore_drill_report.md", "safe no-op result", "NO", "NO", "DB owner", "hold"),
        ("RR-E05", "Security", "MD", "release1_staging_rerun_security_check.md", "no secret/PII", "NO", "NO", "security", "hold"),
    ])
    write("release1_staging_rerun_report.md", """
# RELEASE-1-STAGING-SMOKE-RERUN

## 종합 결론
- status: HOLD
- Limited staging pilot: NO
- Production release: NO
- P0: 0
- P1: Access Pack inputs, actual Linux staging, isolated restore authority, media policy
- P2: safe real e-card file
- next: complete the Access Pack, deploy commit 8613d5b, then rerun on the actual Linux staging host.

## Access Pack gate
All 11 required inputs remain MISSING. The release owner approval form is still an unsigned placeholder. The rerun therefore stopped before host, database, Gunicorn, Nginx, or restore execution.

## Linux staging / host
No Linux staging host or execution method was supplied. Host identity, code commit, Django environment, Gunicorn, Nginx, healthz, static/media, and HTTPS results are NOT_EXECUTED rather than PASS.

## restore
No staging backup archive, checksum, isolated restore target, or restore authority was provided. No production or active database was accessed or changed.

## CEO / HQ / FIELD / LABPAY / RBAC
Staging route and RBAC checks were not executed because staging-safe test accounts and endpoint were missing. Previous local evidence remains valid only as local evidence.

## Security
No secrets or raw PII were requested, printed, or stored. No authentication, CSRF, RBAC, AuditLog, Closing, or Adjustment policy was changed.

## 최종 판정
HOLD. This is a safe stop, not a failed application smoke. Limited staging pilot cannot be approved until access completeness is PASS and actual host smoke succeeds.
""")
    scan()


if __name__ == "__main__":
    main()
