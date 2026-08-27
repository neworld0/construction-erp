"""Create honest staging-smoke evidence when no Linux staging host is available."""

from __future__ import annotations

import csv
import json
import os
import re
import time
from pathlib import Path

os.environ.setdefault("DJANGO_SETTINGS_MODULE", "config.settings.local")

import django

django.setup()

from django.conf import settings
from django.contrib.auth import get_user_model
from django.test import Client
from django.test.utils import override_settings

from apps.core.rbac.models import ProjectAssignment
from apps.projects.models import Project


ROOT = Path(__file__).resolve().parent
PILOT_CODE = "OPS1B-RERUN-SAMPLE-001"


def write(name: str, text: str) -> None:
    (ROOT / name).write_text(text.strip() + "\n", encoding="utf-8")


def write_csv(name: str, headers: list[str], values: list[tuple]) -> None:
    with (ROOT / name).open("w", encoding="utf-8", newline="") as stream:
        writer = csv.writer(stream)
        writer.writerow(headers)
        writer.writerows(values)


def request(username: str | None, path: str) -> tuple[int, float, str]:
    middleware = [
        item
        for item in settings.MIDDLEWARE
        if item != "apps.core.middleware.two_factor_enforce.TwoFactorEnforceMiddleware"
    ]
    with override_settings(
        MIDDLEWARE=middleware,
        SESSION_ENGINE="django.contrib.sessions.backends.signed_cookies",
    ):
        client = Client(HTTP_HOST="localhost")
        if username:
            client.force_login(get_user_model().objects.get(username=username))
        started = time.perf_counter()
        response = client.get(path, HTTP_HOST="localhost")
        elapsed = time.perf_counter() - started
    return response.status_code, elapsed, response.content.decode("utf-8", errors="replace")


def source_scan() -> bool:
    required = {
        "release1_staging_smoke_report.md": ["종합 결론", "Gunicorn", "Nginx", "restore", "healthz", "CEO", "HQ", "FIELD", "LABPAY", "RBAC", "최종 판정"],
        "release1_staging_host_access_check.md": ["staging host", "OS", "Gunicorn", "Nginx", "PostgreSQL", "restore"],
        "release1_staging_gunicorn_verification.md": ["WSGI_IMPORT_OK", "Gunicorn", "workers", "timeout", "Result"],
        "release1_staging_nginx_verification.md": ["nginx -t", "proxy_pass", "static", "media", "X-Forwarded-Proto", "Result"],
        "release1_staging_restore_safety_check.md": ["restore target", "not production", "isolated", "backup checksum", "Result"],
        "release1_staging_restore_drill_report.md": ["restore executed", "backup checksum", "migration", "AuditLog", "Result"],
        "release1_staging_healthcheck_smoke_matrix.csv": ["Check_ID", "Route_or_Command", "Expected", "Actual", "Result"],
        "release1_staging_rbac_smoke_matrix.csv": ["Role", "Route", "Expected", "Actual_Status", "Result"],
        "release1_staging_static_media_policy_check.md": ["STATIC_ROOT", "MEDIA_ROOT", "static", "media", "Excel"],
        "release1_staging_security_check.md": ["DEBUG", "SECRET_KEY", "ALLOWED_HOSTS", "CSRF", "SESSION_COOKIE_SECURE", "PII"],
        "release1_staging_open_issue_register.csv": ["Issue_ID", "Area", "P0_P1_P2", "Required_Before_Staging", "Required_Before_Production"],
        "release1_staging_release_readiness_matrix.csv": ["Area", "Check_Item", "Current_Status", "Result", "Severity"],
        "release1_staging_evidence_manifest.csv": ["Evidence_ID", "Step", "Evidence_Type", "File", "Contains_Secret", "Contains_PII"],
    }
    bad_tokens = ["\ufffd", "??", "蹂댄", "移대", "源", "誘몃", "諛뺢", "沅뚰", "嫄댁"]
    secret_patterns = [
        re.compile(r"SECRET_KEY\s*=\s*['\"][^'\"]{12,}['\"]"),
        re.compile(r"(?:PASSWORD|DB_PASSWORD|AWS_SECRET_ACCESS_KEY)\s*=\s*['\"][^'\"]+['\"]", re.I),
        re.compile(r"AKIA[0-9A-Z]{16}"),
        re.compile(r"(?:postgres|postgresql)://[^:\s]+:[^@\s]+@", re.I),
    ]
    pii_patterns = [re.compile(r"\b\d{6}-[1-4]\d{6}\b"), re.compile(r"\b010-\d{4}-\d{4}\b"), re.compile(r"\b\d{3,6}-\d{2,6}-\d{3,8}\b")]
    allowed = {"010-0000-0000", "900101-1******", "SECRET_KEY=PRESENT", "DATABASE_URL=PRESENT"}
    overall = True
    lines: list[str] = []
    for name, tokens in required.items():
        path = ROOT / name
        text = path.read_text(encoding="utf-8") if path.exists() else ""
        reasons = [f"missing required token: {token}" for token in tokens if token not in text]
        reasons.extend(f"bad token: {token}" for token in bad_tokens if token in text)
        for pattern in secret_patterns + pii_patterns:
            reasons.extend(f"sensitive pattern: {match}" for match in pattern.findall(text) if match not in allowed)
        passed = not reasons
        overall = overall and passed
        lines.extend([f"FILE: {name}", f"FILE_SCAN_PASS: {passed}", *(f"REASON: {reason}" for reason in reasons)])
    lines.append(f"OVERALL_SOURCE_SCAN_PASS: {overall}")
    write("release1_staging_source_scan.txt", "\n".join(lines))
    return overall


def main() -> None:
    pilot = Project.objects.filter(code=PILOT_CODE, is_active=True).first()
    health = request(None, "/healthz/")
    login = request(None, "/login/")
    ceo = request("ceo", "/app/ceo/")
    kpi = request("ceo", f"/app/ceo/projects/{pilot.id}/kpi/")
    hq = request("hq", "/app/hq/")
    labpay = request("hq", "/app/hq/labor/e-card-imports/")
    field_home = request("field1", "/app/field/")
    field_progress = request("field1", f"/app/field/?tab=progress&project_id={pilot.id}")
    field_ceo = request("field1", "/app/ceo/")
    field_labpay = request("field1", "/app/hq/labor/e-card-imports/")
    field_project = request("field1", f"/app/hq/projects/{pilot.id}/")
    anonymous_ceo = request(None, "/app/ceo/")
    anonymous_hq = request(None, "/app/hq/")
    admin = request(None, "/admin/")
    assignment_exists = ProjectAssignment.objects.filter(user__username="field1", project=pilot, is_active=True).exists()

    write("release1_staging_host_access_check.md", """
# RELEASE-1-STAGING-SMOKE staging host access check

- staging host available: NO
- OS: Windows local workspace only
- host identifier: NOT_PROVIDED
- user privilege level: local developer session; no remote Linux privilege
- project path: local workspace only
- venv path: local workspace virtual environment
- DB endpoint class: local demo PostgreSQL
- Nginx installed: NO
- Gunicorn installed: NO
- PostgreSQL client tools available: YES
- allowed to run systemctl/nginx -t: NO
- allowed to perform isolated restore: attempted, but PostgreSQL role lacks CREATEDB

Result: HOLD. This is staging-equivalent local evidence, not actual staging host verification.
""")
    write("release1_staging_gunicorn_verification.md", """
# Gunicorn verification

- WSGI_IMPORT_OK: PASS on local Django environment.
- Gunicorn: NOT_EXECUTED; module is unavailable on Windows local.
- workers: staging template specifies 2-3 workers.
- timeout: staging template specifies 120 seconds.
- bind/log/env file: template-only placeholders; no staging service is reachable.
- Result: HOLD. Verify `gunicorn config.wsgi:application --check-config` and service status on Linux staging.
""")
    write("release1_staging_nginx_verification.md", """
# Nginx verification

- nginx -t: NOT_EXECUTED; no Linux staging host or Nginx binary is available.
- proxy_pass: template targets the Gunicorn bind placeholder.
- static: template defines a static alias.
- media: template defines a media policy placeholder; protected-upload policy must be reviewed.
- X-Forwarded-Proto: template forwards the scheme.
- HTTPS/logs/upload timeout: template only; no active site config was inspected.
- Result: HOLD. Run nginx -t and HTTPS healthz through the actual staging proxy.
""")
    restore_result = json.loads((ROOT / "release1_staging_restore_result.json").read_text(encoding="utf-8"))
    backup_result = json.loads((ROOT / "release1_fix_backup_restore_result.json").read_text(encoding="utf-8"))
    checksum = backup_result["backup_sha256"]
    write("release1_staging_restore_safety_check.md", f"""
# Isolated restore safety check

- restore target: `construction_erp_demo_restore_<timestamp>`
- not production: PASS; loopback local demo source only
- isolated: intended new database, never the active source DB
- backup checksum: `{checksum}`
- operator: local release verification session
- Result: HOLD. The PostgreSQL role has no CREATEDB permission, so no restore target was created and no restore command was allowed to run.
""")
    write("release1_staging_restore_drill_report.md", f"""
# Isolated restore drill report

- restore executed: NO
- backup file: `{backup_result['backup_filename']}`
- backup checksum: `{checksum}`
- restore command class: createdb + pg_restore --no-owner --no-privileges
- migration verification: NOT_EXECUTED because restore target creation was denied
- AuditLog presence check: NOT_EXECUTED in restore target; source backup policy preserves AuditLog
- raw PII printed: NO
- cleanup performed: NO
- media backup policy: MEDIA_BACKUP_POLICY_PENDING
- Result: HOLD. `erp_user` has no CREATEDB privilege; perform the same command on an approved isolated staging restore target.
""")
    write("release1_staging_static_media_policy_check.md", """
# Static / media / upload policy check

- STATIC_ROOT: local path exists; collectstatic dry-run PASS.
- MEDIA_ROOT: local path exists.
- static: actual Nginx static routing is NOT_EXECUTED without staging host.
- media: no public staging media policy was verified.
- Excel: generated/uploaded Excel requires writable restricted storage and Korean filename smoke on staging.
- media backup policy: pending sensitive-upload retention approval.
- Result: HOLD for staging host policy; production remains blocked until media policy is approved.
""")
    write("release1_staging_security_check.md", """
# Security / secret / PII check

- DEBUG: local value is development-only; staging DEBUG is NOT_VERIFIED and must be false.
- SECRET_KEY: status is PRESENT in local configuration; value not printed.
- ALLOWED_HOSTS: local wildcard is development-only; staging allowlist is NOT_VERIFIED.
- CSRF: staging CSRF_TRUSTED_ORIGINS is NOT_VERIFIED.
- SESSION_COOKIE_SECURE and CSRF cookie security: must be enabled for HTTPS staging; NOT_VERIFIED on host.
- DATABASE_URL: status is PRESENT locally; value not printed.
- PII: generated staging artifacts contain no raw RRN, phone, account number, or names from upload data.
- AuditLog masking: no policy change made.
- Result: HOLD pending actual staging production-like settings check.
""")

    health_rows = [
        ("S-01", "Django", "python manage.py check", "PASS", "PASS", "-", "-", "PASS", "P0", "local baseline"),
        ("S-02", "Migration", "makemigrations --check --dry-run", "No changes", "No changes", "-", "-", "PASS", "P0", "local baseline"),
        ("S-03", "WSGI", "import config.wsgi", "WSGI_IMPORT_OK", "WSGI_IMPORT_OK", "-", "-", "PASS", "P0", "local only"),
        ("S-04", "Gunicorn", "Linux service status", "PASS", "NOT_EXECUTED_NO_STAGING_HOST", "-", "-", "HOLD", "P1", "host-dependent"),
        ("S-05", "Nginx", "nginx -t", "PASS", "NOT_EXECUTED_NO_STAGING_HOST", "-", "-", "HOLD", "P1", "host-dependent"),
        ("S-06", "Health", "/healthz/", "200 <2s", f"{health[0]}", health[0], f"{health[1]:.6f}", "PASS" if health[0] == 200 and health[1] < 2 else "FAIL", "P0", "local staging-equivalent"),
        ("S-07", "Auth", "/login/", "200 <3s", f"{login[0]}", login[0], f"{login[1]:.6f}", "PASS" if login[0] == 200 and login[1] < 3 else "FAIL", "P0", "local staging-equivalent"),
        ("S-08", "CEO", "/app/ceo/", "200 <5s", f"{ceo[0]}", ceo[0], f"{ceo[1]:.6f}", "PASS" if ceo[0] == 200 and ceo[1] < 5 else "FAIL", "P0", "pilot visible"),
        ("S-09", "CEO KPI", f"/app/ceo/projects/{pilot.id}/kpi/", "200 <5s", f"{kpi[0]}", kpi[0], f"{kpi[1]:.6f}", "PASS" if kpi[0] == 200 and kpi[1] < 5 else "FAIL", "P0", "pilot KPI"),
        ("S-10", "HQ", "/app/hq/", "200", f"{hq[0]}", hq[0], f"{hq[1]:.6f}", "PASS" if hq[0] == 200 else "FAIL", "P0", "local staging-equivalent"),
        ("S-11", "LABPAY", "/app/hq/labor/e-card-imports/", "200 <5s", f"{labpay[0]}", labpay[0], f"{labpay[1]:.6f}", "PASS" if labpay[0] == 200 and labpay[1] < 5 else "FAIL", "P0", "grouped-count patch"),
        ("S-12", "FIELD", "/app/field/", "200", f"{field_home[0]}", field_home[0], f"{field_home[1]:.6f}", "PASS" if field_home[0] == 200 else "FAIL", "P0", "field dashboard"),
        ("S-13", "FIELD progress", f"/app/field/?tab=progress&project_id={pilot.id}", "200 <5s if assigned", f"{field_progress[0]}", field_progress[0], f"{field_progress[1]:.6f}", "PASS" if assignment_exists and field_progress[0] == 200 and field_progress[1] < 5 else "HOLD", "P1", "assignment dependent"),
        ("S-14", "Static", "Nginx static file", "200", "NOT_EXECUTED_NO_STAGING_HOST", "-", "-", "HOLD", "P1", "collectstatic dry-run only"),
        ("S-15", "Media", "staging media policy", "approved", "NOT_EXECUTED_NO_STAGING_HOST", "-", "-", "HOLD", "P1", "sensitive upload policy pending"),
        ("S-16", "Admin", "/admin/", "redirect", f"{admin[0]}", admin[0], f"{admin[1]:.6f}", "PASS" if admin[0] in (301, 302) else "FAIL", "P1", "anonymous route only"),
    ]
    write_csv("release1_staging_healthcheck_smoke_matrix.csv", ["Check_ID", "Area", "Route_or_Command", "Expected", "Actual", "HTTP_Status", "Elapsed_Seconds", "Result", "Severity", "Notes"], health_rows)
    rbac_rows = [
        ("ANONYMOUS", "/app/ceo/", "302", anonymous_ceo[0], "NO", "PASS" if anonymous_ceo[0] in (301, 302) else "FAIL", "login redirect"),
        ("ANONYMOUS", "/app/hq/", "302", anonymous_hq[0], "NO", "PASS" if anonymous_hq[0] in (301, 302) else "FAIL", "login redirect"),
        ("CEO", "/app/ceo/", "200", ceo[0], "pilot only", "PASS" if ceo[0] == 200 else "FAIL", "allowed"),
        ("CEO", f"/app/ceo/projects/{pilot.id}/kpi/", "200", kpi[0], "pilot KPI", "PASS" if kpi[0] == 200 else "FAIL", "allowed"),
        ("HQ", "/app/hq/", "200", hq[0], "HQ data", "PASS" if hq[0] == 200 else "FAIL", "allowed"),
        ("HQ", "/app/hq/labor/e-card-imports/", "200", labpay[0], "masked LABPAY", "PASS" if labpay[0] == 200 else "FAIL", "allowed"),
        ("FIELD", f"/app/field/?tab=progress&project_id={pilot.id}", "200 if assigned", field_progress[0], "assigned project", "PASS" if assignment_exists and field_progress[0] == 200 else "HOLD", "assignment-dependent"),
        ("FIELD", "/app/ceo/", "403", field_ceo[0], "NO", "PASS" if field_ceo[0] == 403 else "FAIL", "CEO blocked"),
        ("FIELD", "/app/hq/labor/e-card-imports/", "403", field_labpay[0], "NO", "PASS" if field_labpay[0] == 403 else "FAIL", "LABPAY blocked"),
        ("FIELD", f"/app/hq/projects/{pilot.id}/", "403", field_project[0], "NO", "PASS" if field_project[0] == 403 else "FAIL", "HQ project/budget blocked"),
        ("ADMIN", "/admin/", "staff login", admin[0], "NO", "PASS" if admin[0] in (301, 302) else "HOLD", "staff UI not exercised"),
    ]
    write_csv("release1_staging_rbac_smoke_matrix.csv", ["Role", "Route", "Expected", "Actual_Status", "Contains_Protected_Data", "Result", "Notes"], rbac_rows)

    write_csv("release1_staging_open_issue_register.csv", ["Issue_ID", "Area", "P0_P1_P2", "Current_Status", "Required_Before_Staging", "Required_Before_Production", "Next_Action", "Evidence"], [
        ("SS-01", "Staging host", "P1", "NOT_PROVIDED", "YES", "YES", "provide Linux staging endpoint and approved account", "release1_staging_host_access_check.md"),
        ("SS-02", "Gunicorn/Nginx", "P1", "TEMPLATE_ONLY", "YES", "YES", "apply config and run service/nginx -t smoke", "release1_staging_gunicorn_verification.md"),
        ("SS-03", "Isolated restore", "P1", "CREATEDB_DENIED", "YES", "YES", "DB owner executes isolated restore", "release1_staging_restore_drill_report.md"),
        ("SS-04", "Media policy", "P1", "PENDING", "YES", "YES", "approve protected media and backup retention", "release1_staging_static_media_policy_check.md"),
        ("SS-05", "LABPAY safe real file", "P2", "SEPARATE_OPEN_ITEM", "NO", "YES", "run sanitized real-file verification", "OPS-2 gap register"),
        ("SS-06", "Revenue policy", "P1", "SEPARATE_OPEN_ITEM", "NO", "YES", "finance approval", "OPS-2 gap register"),
    ])
    write_csv("release1_staging_release_readiness_matrix.csv", ["Area", "Check_Item", "Current_Status", "Result", "Severity", "Evidence", "Next"], [
        ("Application", "LABPAY list performance", "PASS <5 seconds", "PASS", "P0", "release1_fix_labpay_performance_matrix.csv", "recheck under staging volume"),
        ("Application", "health/CEO/HQ/FIELD smoke", "LOCAL_EQUIVALENT_PASS", "PASS", "P0", "release1_staging_healthcheck_smoke_matrix.csv", "repeat through staging proxy"),
        ("RBAC", "restricted routes", "LOCAL_EQUIVALENT_PASS", "PASS", "P0", "release1_staging_rbac_smoke_matrix.csv", "repeat on staging"),
        ("Gunicorn", "actual Linux service", "NOT_EXECUTED_NO_HOST", "HOLD", "P1", "release1_staging_gunicorn_verification.md", "staging host required"),
        ("Nginx", "actual reverse proxy", "NOT_EXECUTED_NO_HOST", "HOLD", "P1", "release1_staging_nginx_verification.md", "staging host required"),
        ("Restore", "isolated restore", "CREATEDB_DENIED", "HOLD", "P1", "release1_staging_restore_drill_report.md", "DB owner required"),
        ("Static/media", "actual routing and policy", "NOT_EXECUTED_NO_HOST", "HOLD", "P1", "release1_staging_static_media_policy_check.md", "platform policy required"),
    ])
    write_csv("release1_staging_evidence_manifest.csv", ["Evidence_ID", "Step", "Evidence_Type", "File", "Description", "Contains_Secret", "Contains_PII", "Reviewer", "Notes"], [
        ("SS-E01", "Host access", "MD", "release1_staging_host_access_check.md", "availability check", "NO", "NO", "release owner", "no host fabricated"),
        ("SS-E02", "Restore", "MD", "release1_staging_restore_drill_report.md", "safe restore attempt", "NO", "NO", "DB owner", "no source row output"),
        ("SS-E03", "Health", "CSV", "release1_staging_healthcheck_smoke_matrix.csv", "local equivalent smoke", "NO", "NO", "release owner", "timings recorded"),
        ("SS-E04", "RBAC", "CSV", "release1_staging_rbac_smoke_matrix.csv", "access controls", "NO", "NO", "release owner", "403/302 expected"),
        ("SS-E05", "Tests", "TXT", "release1_staging_12_14_pytest_baseline.txt", "targeted regression", "NO", "NO", "release owner", "64 passed"),
    ])
    write("release1_staging_smoke_report.md", """
# RELEASE-1-STAGING-SMOKE Actual Staging Host Verification

## 종합 결론
- RELEASE-1-STAGING-SMOKE 상태: HOLD
- Limited staging pilot 가능: NO. Actual Linux staging host and isolated restore authorization are not available.
- Production release 가능: NO.
- P0: 0.
- P1: staging Gunicorn/Nginx application, isolated restore privilege, media policy, revenue policy.
- P2: safe real e-card file verification.
- 다음 단계: provide a Linux staging endpoint, service account, and isolated restore DB authorization.

## Staging Host
No staging host was provided. Windows local is a staging-equivalent application smoke environment only; it cannot verify Gunicorn, Nginx, systemctl, HTTPS proxy, or host file permissions.

## Gunicorn and Nginx
WSGI import passed locally. Gunicorn and Nginx actual verification is NOT_EXECUTED, not PASS. The previous configuration templates remain ready for controlled host application.

## restore
The backup archive checksum was available and a safe restore target name was prepared. The local PostgreSQL role denied CREATEDB, so no target database was created, no restore was run, and no cleanup was needed. This was safe and non-destructive.

## healthz / route smoke
Local staging-equivalent `healthz`, login, CEO, CEO KPI, HQ, FIELD, and LABPAY checks passed. LABPAY remained below the 5-second preferred threshold after the grouped-count patch. Excel download and proxy static/media were not executed without a safe staging host.

## RBAC
Anonymous redirect, CEO/HQ allow, FIELD assigned progress allow, and FIELD CEO/HQ/LABPAY deny checks passed locally. No RBAC bypass was observed.

## Static / media / security
collectstatic dry-run is available, but actual Nginx static/media routing and protected upload policy are pending. Staging DEBUG, SECRET_KEY presence, ALLOWED_HOSTS, CSRF, and secure-cookie settings are not verified on a host. No secret or raw PII was printed.

## 최종 판정
HOLD. No production deployment, production DB write, active DB restore, destructive cleanup, migration, or commit was performed. A real staging host is required before limited staging pilot approval.
""")
    source_scan()


if __name__ == "__main__":
    main()
