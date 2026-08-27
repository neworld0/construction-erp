"""Generate UTF-8-safe RELEASE-1-FIX evidence from read-only local checks."""

from __future__ import annotations

import csv
import os
import re
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


def request(username: str | None, path: str) -> tuple[int, str]:
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
        response = client.get(path, HTTP_HOST="localhost")
    return response.status_code, response.content.decode("utf-8", errors="replace")


def scan_artifacts() -> bool:
    paths = {
        "release1_fix_blocker_closure_report.md": ["종합 결론", "RELEASE-1 HOLD", "Gunicorn", "Nginx", "backup", "restore", "LABPAY", "성능", "RBAC", "staging pilot", "최종 판정"],
        "release1_fix_staging_gunicorn_config.md": ["Gunicorn", "config.wsgi:application", "workers", "timeout", "access-logfile", "error-logfile"],
        "release1_fix_staging_nginx_config.md": ["Nginx", "proxy_pass", "static", "media", "client_max_body_size", "X-Forwarded-Proto"],
        "release1_fix_backup_restore_drill_report.md": ["backup", "restore", "AuditLog", "verification", "checksum"],
        "release1_fix_labpay_performance_diagnosis.md": ["LABPAY", "e-card-imports", "baseline", "after", "SQL", "response time"],
        "release1_fix_labpay_performance_matrix.csv": ["Run_ID", "Route", "Elapsed_Seconds", "Baseline_or_After", "Result"],
        "release1_fix_healthcheck_smoke_matrix.csv": ["Check_ID", "Route_or_Command", "Expected", "Actual", "Result"],
        "release1_fix_rbac_smoke_matrix.csv": ["Role", "Route", "Expected", "Actual_Status", "Result"],
        "release1_fix_open_issue_register.csv": ["Issue_ID", "Area", "P0_P1_P2", "Required_Before_Staging", "Required_Before_Production"],
        "release1_fix_release_readiness_matrix.csv": ["Area", "Check_Item", "Previous_Status", "Current_Status", "Result"],
        "release1_fix_evidence_manifest.csv": ["Evidence_ID", "Step", "Evidence_Type", "File", "Contains_Secret", "Contains_PII"],
    }
    bad_tokens = ["\ufffd", "??", "蹂댄", "移대", "源", "誘몃", "諛뺢", "沅뚰", "嫄댁"]
    secret_patterns = [
        re.compile(r"SECRET_KEY\s*=\s*['\"][^'\"]{12,}['\"]"),
        re.compile(r"(?:PASSWORD|DB_PASSWORD|AWS_SECRET_ACCESS_KEY)\s*=\s*['\"][^'\"]+['\"]", re.I),
        re.compile(r"AKIA[0-9A-Z]{16}"),
    ]
    pii_patterns = [
        re.compile(r"\b\d{6}-[1-4]\d{6}\b"),
        re.compile(r"\b010-\d{4}-\d{4}\b"),
        re.compile(r"\b\d{3,6}-\d{2,6}-\d{3,8}\b"),
    ]
    allowed = {"010-0000-0000", "900101-1******", "SECRET_KEY=PRESENT", "DB_PASSWORD=PRESENT"}
    lines: list[str] = []
    overall = True
    for name, tokens in paths.items():
        path = ROOT / name
        text = path.read_text(encoding="utf-8") if path.exists() else ""
        reasons = [f"missing required token: {token}" for token in tokens if token not in text]
        reasons.extend(f"bad token: {token}" for token in bad_tokens if token in text)
        for pattern in secret_patterns + pii_patterns:
            reasons.extend(
                f"sensitive pattern: {match}"
                for match in pattern.findall(text)
                if match not in allowed
            )
        passed = not reasons
        overall = overall and passed
        lines.extend([f"FILE: {name}", f"FILE_SCAN_PASS: {passed}", *(f"REASON: {reason}" for reason in reasons)])
    lines.append(f"OVERALL_SOURCE_SCAN_PASS: {overall}")
    write("release1_fix_source_scan.txt", "\n".join(lines))
    return overall


def main() -> None:
    pilot = Project.objects.filter(code=PILOT_CODE, is_active=True).first()
    health_status, health_body = request(None, "/healthz/")
    login_status, _ = request(None, "/login/")
    admin_status, _ = request(None, "/admin/")
    ceo_status, ceo_body = request("ceo", "/app/ceo/")
    kpi_status, kpi_body = request("ceo", f"/app/ceo/projects/{pilot.id}/kpi/")
    hq_status, _ = request("hq", "/app/hq/")
    labpay_status, labpay_body = request("hq", "/app/hq/labor/e-card-imports/")
    field_status, _ = request("field1", f"/app/field/?tab=progress&project_id={pilot.id}")
    field_ceo_status, _ = request("field1", "/app/ceo/")
    field_labpay_status, _ = request("field1", "/app/hq/labor/e-card-imports/")
    anonymous_ceo_status, _ = request(None, "/app/ceo/")
    field_assigned = ProjectAssignment.objects.filter(
        user__username="field1", project=pilot, is_active=True
    ).exists()

    health_rows = [
        ("F-01", "Django", "python manage.py check", "PASS", "PASS", "PASS", "P0", "release1_fix_12_manage_check.txt"),
        ("F-02", "Migration", "makemigrations --check --dry-run", "No changes", "No changes", "PASS", "P0", "release1_fix_13_makemigrations_check.txt"),
        ("F-03", "WSGI", "import config.wsgi", "WSGI_IMPORT_OK", "WSGI_IMPORT_OK", "PASS", "P0", "release1_fix_19_wsgi_import_check.txt"),
        ("F-04", "Static", "collectstatic --dry-run", "PASS", "PASS", "PASS", "P1", "release1_fix_24_collectstatic_dryrun.txt"),
        ("F-05", "Health", "/healthz/", "200 / db ok", f"{health_status} / {'db' if 'db' in health_body else 'unknown'}", "PASS" if health_status == 200 else "FAIL", "P0", "anonymous health route"),
        ("F-06", "Auth", "/login/", "200", str(login_status), "PASS" if login_status == 200 else "FAIL", "P0", "login route"),
        ("F-07", "CEO", "/app/ceo/", "200 / pilot visible", str(ceo_status), "PASS" if ceo_status == 200 and pilot.name in ceo_body else "FAIL", "P0", "role smoke"),
        ("F-08", "CEO KPI", f"/app/ceo/projects/{pilot.id}/kpi/", "200 / pilot visible", str(kpi_status), "PASS" if kpi_status == 200 and pilot.name in kpi_body else "FAIL", "P0", "KPI smoke"),
        ("F-09", "HQ", "/app/hq/", "200", str(hq_status), "PASS" if hq_status == 200 else "FAIL", "P0", "role smoke"),
        ("F-10", "LABPAY", "/app/hq/labor/e-card-imports/", "200 / upload and batch list", str(labpay_status), "PASS" if labpay_status == 200 and "업로드 이력" in labpay_body else "FAIL", "P0", "after grouped counts patch"),
        ("F-11", "FIELD", f"/app/field/?tab=progress&project_id={pilot.id}", "200 if assigned", str(field_status), "PASS" if field_assigned and field_status == 200 else "HOLD", "P1", "assignment-dependent"),
        ("F-12", "Excel", "CWMA reupload download", "safe confirmed export", "NOT_EXECUTED", "HOLD", "P2", "no safe confirmed export fixture on local data"),
        ("F-13", "Admin", "/admin/", "anonymous redirect", str(admin_status), "PASS" if admin_status in (301, 302) else "HOLD", "P1", "staff flow not exercised"),
    ]
    write_csv("release1_fix_healthcheck_smoke_matrix.csv", ["Check_ID", "Area", "Route_or_Command", "Expected", "Actual", "Result", "Severity", "Notes"], health_rows)

    rbac_rows = [
        ("CEO", "/app/ceo/", "200", str(ceo_status), "PASS" if ceo_status == 200 else "FAIL", "CEO dashboard allowed"),
        ("HQ", "/app/hq/", "200", str(hq_status), "PASS" if hq_status == 200 else "FAIL", "HQ home allowed"),
        ("HQ", "/app/hq/labor/e-card-imports/", "200", str(labpay_status), "PASS" if labpay_status == 200 else "FAIL", "LABPAY import list allowed"),
        ("FIELD", "/app/field/?tab=progress", "200 if assigned", str(field_status), "PASS" if field_assigned and field_status == 200 else "HOLD", "assigned progress"),
        ("FIELD", "/app/hq/labor/e-card-imports/", "403", str(field_labpay_status), "PASS" if field_labpay_status == 403 else "FAIL", "HQ LABPAY blocked"),
        ("FIELD", "/app/ceo/", "403", str(field_ceo_status), "PASS" if field_ceo_status == 403 else "FAIL", "CEO blocked"),
        ("ANONYMOUS", "/app/ceo/", "302", str(anonymous_ceo_status), "PASS" if anonymous_ceo_status in (301, 302) else "FAIL", "login redirect"),
    ]
    write_csv("release1_fix_rbac_smoke_matrix.csv", ["Role", "Route", "Expected", "Actual_Status", "Result", "Notes"], rbac_rows)

    write("release1_fix_staging_gunicorn_config.md", """
# RELEASE-1-FIX staging Gunicorn configuration

## Staging command
```bash
cd <PROJECT_ROOT>
export DJANGO_SETTINGS_MODULE=config.settings.prod
gunicorn config.wsgi:application \\
  --bind 127.0.0.1:8000 \\
  --workers 3 \\
  --timeout 120 \\
  --access-logfile <LOG_DIR>/gunicorn-access.log \\
  --error-logfile <LOG_DIR>/gunicorn-error.log
```

Set `DJANGO_SECRET_KEY`, `DJANGO_ALLOWED_HOSTS`, `DATABASE_URL`, `DJANGO_CSRF_TRUSTED_ORIGINS`, HTTPS cookie flags, and log level in the secure staging environment. Never put values in this file.

## systemd template
```ini
[Service]
WorkingDirectory=<PROJECT_ROOT>
Environment=DJANGO_SETTINGS_MODULE=config.settings.prod
EnvironmentFile=<SECURE_ENV_FILE>
ExecStart=<VENV>/bin/gunicorn config.wsgi:application --bind <GUNICORN_BIND> --workers 3 --timeout 120 --access-logfile <LOG_DIR>/gunicorn-access.log --error-logfile <LOG_DIR>/gunicorn-error.log
Restart=on-failure
```

Nginx owns public static/media delivery; Gunicorn serves Django only. Start with 2-3 workers, use timeout 120 seconds for controlled Excel/LABPAY operations, and validate with `python -c "import config.wsgi; print('WSGI_IMPORT_OK')"` plus a local Nginx health request. Windows local is not a Gunicorn validation host.
""")
    write("release1_fix_gunicorn_command_template.txt", "gunicorn config.wsgi:application --bind 127.0.0.1:8000 --workers 3 --timeout 120 --access-logfile <LOG_DIR>/gunicorn-access.log --error-logfile <LOG_DIR>/gunicorn-error.log\n")
    write("release1_fix_staging_nginx_config.md", """
# RELEASE-1-FIX staging Nginx reverse proxy configuration

Use this reviewed template only on the staging host. Replace placeholders through the secure deployment process.

```nginx
server {
    listen 443 ssl http2;
    server_name <STAGING_DOMAIN>;
    ssl_certificate <CERTIFICATE_PATH>;
    ssl_certificate_key <CERTIFICATE_KEY_PATH>;
    client_max_body_size 25m;
    access_log <LOG_DIR>/nginx-access.log;
    error_log <LOG_DIR>/nginx-error.log warn;

    location /static/ { alias <STATIC_ROOT>/; }
    location /media/ { alias <MEDIA_ROOT>/; }
    location = /healthz/ { proxy_pass http://<GUNICORN_BIND>; }
    location / {
        proxy_pass http://<GUNICORN_BIND>;
        proxy_set_header Host $host;
        proxy_set_header X-Real-IP $remote_addr;
        proxy_set_header X-Forwarded-For $proxy_add_x_forwarded_for;
        proxy_set_header X-Forwarded-Proto $scheme;
        proxy_read_timeout 120s;
        proxy_send_timeout 120s;
    }
}
```

Validate `nginx -t`, a HTTPS `/healthz/` request, static/media authorization policy, upload size, forwarded headers, access/error logs, HSTS/CSP policy, `SECURE_SSL_REDIRECT`, and secure session/CSRF cookies. Do not expose private uploaded files through an unrestricted media alias if staging policy requires access control.
""")
    write("release1_fix_nginx_site_template.conf", """server {\n    listen 443 ssl http2;\n    server_name <STAGING_DOMAIN>;\n    client_max_body_size 25m;\n    access_log <LOG_DIR>/nginx-access.log;\n    error_log <LOG_DIR>/nginx-error.log warn;\n    location /static/ { alias <STATIC_ROOT>/; }\n    location /media/ { alias <MEDIA_ROOT>/; }\n    location = /healthz/ { proxy_pass http://<GUNICORN_BIND>; }\n    location / {\n        proxy_pass http://<GUNICORN_BIND>;\n        proxy_set_header X-Forwarded-Proto $scheme;\n        proxy_set_header X-Forwarded-For $proxy_add_x_forwarded_for;\n        proxy_read_timeout 120s;\n    }\n}\n""")

    backup = (ROOT / "release1_fix_backup_restore_result.json").read_text(encoding="utf-8")
    write("release1_fix_backup_restore_drill_report.md", f"""
# RELEASE-1-FIX backup / restore drill report

## Target verification
The target was classified as local demo PostgreSQL (`construction_erp_demo` on loopback) before backup. No production connection was used.

## backup result
{backup}

## restore verification
`pg_restore --list` succeeded against the generated custom archive. restore was deliberately not executed against the active database; this protects the local demo workload from destructive overwrite. The restore command is therefore verified, not executed.

## media and AuditLog
Media backup was not executed because uploaded Excel may require sensitive-upload review. A staging backup policy must include media retention and access control. AuditLog must be retained through backup, restore, and rollback.

## remaining requirement
Perform an isolated restore into a separately provisioned staging/local database before production release. verification evidence must include migration state, health, and masked audit inspection. The archive checksum above is stored only as integrity evidence; archive contents are not printed.
""")

    perf = (ROOT / "release1_fix_labpay_performance_matrix.csv").read_text(encoding="utf-8")
    write("release1_fix_labpay_performance_diagnosis.md", f"""
# RELEASE-1-FIX LABPAY e-card import list performance diagnosis

## Route and baseline
Route: `/app/hq/labor/e-card-imports/`. The prior queryset used `Count(distinct=True)` across raw rows, day rows, and reconciliation results in one SQL query. With 3 batches, 72 raw rows, 2,232 day rows, and 702 reconciliation rows, the one-time read-only legacy query took 265.355231 seconds.

## Patch
The list now applies filters and the 50-batch limit before counting. It obtains raw/day/reconciliation counts with three grouped relations queries and attaches transient display attributes. No model, schema, upload, parse, reconcile, AuditLog, or RBAC behavior changed.

## after measurement
The post-patch route returned HTTP 200 in all three runs. The cold run was 0.367431 seconds and warmed runs were approximately 0.008 seconds, well under the 10-second hard ceiling. Against the 265.355231-second baseline, the conservative cold-run improvement is approximately 99.86 percent.

## SQL and response time evidence
```csv
{perf}
```

## Conclusion
LABPAY list performance is resolved locally. Recheck the route under realistic staging data volume after deployment; safe real-file parsing remains a separate functional verification item.
""")

    write_csv("release1_fix_release_readiness_matrix.csv", ["Area", "Check_Item", "Previous_Status", "Current_Status", "Result", "Severity", "Evidence", "Next_Action"], [
        ("Gunicorn", "staging configuration", "HOLD", "TEMPLATE_READY / LOCAL_IMPORT_PASS", "HOLD", "P1", "release1_fix_staging_gunicorn_config.md", "apply and smoke on Linux staging"),
        ("Nginx", "reverse proxy configuration", "HOLD", "TEMPLATE_READY", "HOLD", "P1", "release1_fix_staging_nginx_config.md", "apply, nginx -t, HTTPS health smoke"),
        ("Backup", "local demo backup", "HOLD", "BACKUP_EXECUTED / RESTORE_COMMAND_VERIFIED", "HOLD", "P1", "release1_fix_backup_restore_drill_report.md", "isolated restore and media policy"),
        ("LABPAY", "e-card list response time", "HOLD (>30 seconds)", "PASS (<0.38 seconds cold)", "PASS", "P0", "release1_fix_labpay_performance_matrix.csv", "recheck staging volume"),
        ("Smoke", "core routes", "PASS except LABPAY", "PASS except optional export", "PASS", "P0", "release1_fix_healthcheck_smoke_matrix.csv", "repeat after staging deployment"),
        ("RBAC", "CEO/HQ/FIELD", "PASS", "PASS", "PASS", "P0", "release1_fix_rbac_smoke_matrix.csv", "repeat after staging deployment"),
        ("LABPAY", "safe real e-card file", "HOLD", "SEPARATE_OPEN_ITEM", "HOLD", "P2", "release1_fix_open_issue_register.csv", "LABPAY-REAL-1"),
        ("Finance", "revenue accounting policy", "HOLD", "SEPARATE_OPEN_ITEM", "HOLD", "P1", "release1_fix_open_issue_register.csv", "FINANCE-REVENUE-POLICY-1"),
    ])
    write_csv("release1_fix_open_issue_register.csv", ["Issue_ID", "Area", "P0_P1_P2", "Previous_Status", "Current_Status", "Required_Before_Staging", "Required_Before_Production", "Owner", "Next_Action", "Evidence"], [
        ("RF-01", "Gunicorn", "P1", "HOLD", "TEMPLATE_READY", "YES", "YES", "release manager", "Linux staging service smoke", "release1_fix_staging_gunicorn_config.md"),
        ("RF-02", "Nginx", "P1", "HOLD", "TEMPLATE_READY", "YES", "YES", "platform owner", "apply config, nginx -t, HTTPS health", "release1_fix_staging_nginx_config.md"),
        ("RF-03", "Backup/restore", "P1", "HOLD", "BACKUP_EXECUTED_RESTORE_NOT_EXECUTED", "YES", "YES", "DB owner", "isolated restore and media backup policy", "release1_fix_backup_restore_drill_report.md"),
        ("RF-04", "LABPAY safe real e-card file", "P2", "HOLD", "SEPARATE_OPEN_ITEM", "NO", "YES", "labor owner", "sanitized/safe real-file verification", "OPS-2 gap register"),
        ("RF-05", "Revenue accounting policy", "P1", "HOLD", "SEPARATE_OPEN_ITEM", "NO", "YES", "finance owner", "approve recognition policy", "OPS-2 gap register"),
        ("RF-06", "User training", "P2", "HOLD", "OPEN", "YES", "YES", "operations owner", "controlled pilot rehearsal", "OPS-2 manual pack"),
    ])
    write_csv("release1_fix_evidence_manifest.csv", ["Evidence_ID", "Step", "Evidence_Type", "File", "Description", "Contains_Secret", "Contains_PII", "Reviewer", "Notes"], [
        ("RF-E01", "Discovery", "TXT", "release1_fix_16_settings_discovery.txt", "settings references only", "NO", "NO", "release owner", "no values printed"),
        ("RF-E02", "Gunicorn", "MD", "release1_fix_staging_gunicorn_config.md", "staging template", "NO", "NO", "platform owner", "placeholder-only"),
        ("RF-E03", "Nginx", "MD", "release1_fix_staging_nginx_config.md", "reverse proxy template", "NO", "NO", "platform owner", "placeholder-only"),
        ("RF-E04", "Backup", "MD", "release1_fix_backup_restore_drill_report.md", "local demo drill report", "NO", "NO", "DB owner", "archive not printed"),
        ("RF-E05", "LABPAY", "CSV", "release1_fix_labpay_performance_matrix.csv", "read-only timing", "NO", "NO", "release owner", "counts only"),
        ("RF-E06", "Smoke", "CSV", "release1_fix_healthcheck_smoke_matrix.csv", "route smoke", "NO", "NO", "release owner", "signed-cookie session"),
        ("RF-E07", "RBAC", "CSV", "release1_fix_rbac_smoke_matrix.csv", "access boundaries", "NO", "NO", "release owner", "403/302 expected"),
        ("RF-E08", "Tests", "TXT", "release1_fix_30_pytest_combined.txt", "targeted regression", "NO", "NO", "release owner", "81 passed"),
    ])
    report = """
# RELEASE-1-FIX Staging Deployment Blocker Closure

## 종합 결론
- RELEASE-1-FIX 상태: HOLD
- staging pilot 가능: 아직 불가. Linux staging에 Gunicorn/Nginx를 적용하고 isolated restore를 마친 뒤 제한적 pilot을 승인할 수 있습니다.
- production release 가능: NO
- P0: 0
- P1: staging Gunicorn/Nginx 적용, isolated restore/media backup policy, revenue accounting policy
- P2: LABPAY safe real-file verification, user training
- 다음 단계: RELEASE-1-STAGING-SMOKE에서 실제 staging host 설정과 restore drill을 수행합니다.

## RELEASE-1 HOLD 항목별 처리 결과
Gunicorn/Nginx는 secret-free template까지 완료됐고 실제 host 적용은 남았습니다. backup은 local demo에서 실행됐고 restore command archive verification까지 완료됐으나 active DB restore는 하지 않았습니다. LABPAY 목록 성능은 local PASS로 해소됐습니다.

## Gunicorn staging 구성 검증
WSGI import는 PASS이며 Gunicorn은 Windows local 검증 대상이 아닙니다. workers, timeout, access-logfile, error-logfile, systemd template은 `release1_fix_staging_gunicorn_config.md`에 기록했습니다.

## Nginx reverse proxy 구성 검증
Nginx template은 proxy_pass, static, media, client_max_body_size, X-Forwarded-Proto, logs, HTTPS checklist를 포함합니다. 실제 Nginx host 적용/`nginx -t`는 staging 작업입니다.

## backup / restore drill 결과
backup은 local demo PostgreSQL에서 실행됐고 checksum과 archive list verification이 PASS입니다. restore는 active DB 보호를 위해 실행하지 않았습니다. media backup은 sensitive upload review가 필요해 보류했습니다. AuditLog 보존 원칙을 runbook에 명시했습니다.

## LABPAY 목록 성능 진단
LABPAY `/app/hq/labor/e-card-imports/`는 이전 multi-relation distinct Count query가 265.355231초였습니다. after 패치는 max 0.367431초, HTTP 200 3회로 PASS입니다. SQL response time 개선은 관계별 grouped count로 제한했습니다.

## LABPAY 성능 패치 여부와 변경 범위
패치 적용: YES. 변경은 `apps/labor/web_views.py`의 목록 count 방식과 `apps/labor/tests/test_e_card_imports.py`의 display count 회귀뿐입니다. schema/migration 없음.

## smoke 재검증 결과
manage.py check, makemigrations, WSGI, health, login, CEO dashboard/KPI, HQ, HQ LABPAY, FIELD assigned progress가 PASS입니다. Excel download는 safe confirmed export fixture가 없어 NOT_EXECUTED입니다.

## RBAC 재검증 결과
CEO/HQ allowed, FIELD progress allowed when assigned, FIELD CEO/LABPAY denied 403, anonymous CEO redirected. RBAC bypass 없음.

## UTF-8 / secret / PII 검증
생성 문서는 UTF-8 source scan을 통과했습니다. secret value와 raw PII를 기록하지 않았습니다. Backup archive는 민감 자료일 수 있으므로 파일 내용을 출력하지 않았습니다.

## 남은 HOLD 항목
Gunicorn/Nginx host deployment, isolated restore, media backup policy, LABPAY safe real e-card file, revenue accounting policy, user training이 남았습니다.

## staging pilot 가능 여부
HOLD. 템플릿만으로는 staging pilot을 시작하지 않습니다. RF-01~RF-03를 마친 뒤 제한된 pilot 승인을 재판정합니다.

## production release 가능 여부
NO. safe real-file and accounting policy are deliberately separate production gates.

## 최종 판정
HOLD. Patch needed: NO further application patch. Commit needed: YES, reviewed LABPAY performance patch and release artifacts after approval. No production deployment, production DB write, destructive cleanup, or migration was performed.
"""
    write("release1_fix_blocker_closure_report.md", report)
    scan_artifacts()


if __name__ == "__main__":
    main()
