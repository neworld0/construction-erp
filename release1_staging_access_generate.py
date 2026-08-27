"""Generate the documentation-only staging access and authority preparation pack."""

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
        "release1_staging_access_pack.md": ["문서 목적", "현재 RELEASE 상태", "왜 현재 HOLD인지", "Linux staging host", "Service account", "PostgreSQL", "Isolated restore", "Nginx", "Gunicorn", "Production release", "RELEASE-1-STAGING-SMOKE-RERUN"],
        "release1_staging_access_questionnaire.csv": ["Question_ID", "staging host", "service account", "settings module", "restore target DB", "nginx -t", "staging pilot approver"],
        "release1_staging_authority_matrix.csv": ["Authority_ID", "SSH login", "restart Gunicorn", "reload Nginx", "create isolated restore DB", "approve limited staging pilot"],
        "release1_staging_env_var_request_template.csv": ["Env_Key", "SECRET_KEY", "DEBUG", "ALLOWED_HOSTS", "DATABASE", "CSRF_TRUSTED_ORIGINS", "Allowed_To_Print_Value"],
        "release1_staging_db_restore_authority_checklist.csv": ["Check_ID", "not production", "isolated", "CREATEDB", "backup checksum", "AuditLog"],
        "release1_staging_nginx_gunicorn_execution_checklist.csv": ["Check_ID", "WSGI", "Gunicorn", "Nginx", "nginx -t", "proxy_pass", "static", "media"],
        "release1_staging_media_backup_policy_template.csv": ["Area", "media", "sensitive Excel", "encrypted at rest", "retention", "Korean filename"],
        "release1_staging_smoke_rerun_input_manifest.csv": ["Input_ID", "Required_Input", "Used_By", "Blocker_If_Missing"],
        "release1_staging_owner_approval_form.md": ["승인 목적", "허용 작업", "금지 작업", "Restore 권한 승인", "Production release 제외 확인"],
        "release1_staging_access_gap_register.csv": ["Gap_ID", "Linux staging host missing", "isolated restore DB privilege missing", "media backup policy pending", "production release remains excluded"],
    }
    bad = ["\ufffd", "??", "蹂댄", "移대", "源", "誘몃", "諛뺢", "沅뚰", "嫄댁"]
    secret = [re.compile(r"SECRET_KEY\s*=\s*['\"][^'\"]{12,}['\"]"), re.compile(r"(?:PASSWORD|DB_PASSWORD|AWS_SECRET_ACCESS_KEY)\s*=\s*['\"][^'\"]+['\"]", re.I), re.compile(r"AKIA[0-9A-Z]{16}"), re.compile(r"(?:postgres|postgresql)://[^:\s]+:[^@\s]+@", re.I)]
    pii = [re.compile(r"\b\d{6}-[1-4]\d{6}\b"), re.compile(r"\b010-\d{4}-\d{4}\b"), re.compile(r"\b\d{3,6}-\d{2,6}-\d{3,8}\b")]
    allowed = {"SECRET_KEY=PRESENT", "DATABASE_URL=PRESENT", "010-0000-0000", "900101-1******"}
    lines, overall = [], True
    for name, tokens in required.items():
        text = (ROOT / name).read_text(encoding="utf-8") if (ROOT / name).exists() else ""
        reasons = [f"missing required token: {token}" for token in tokens if token not in text]
        reasons.extend(f"bad token: {token}" for token in bad if token in text)
        for pattern in secret + pii:
            reasons.extend(f"sensitive pattern: {value}" for value in pattern.findall(text) if value not in allowed)
        passed = not reasons
        overall = overall and passed
        lines.extend([f"FILE: {name}", f"FILE_SCAN_PASS: {passed}", *(f"REASON: {reason}" for reason in reasons)])
    lines.append(f"OVERALL_SOURCE_SCAN_PASS: {overall}")
    write("release1_staging_access_source_scan.txt", "\n".join(lines))
    return overall


def main() -> None:
    write("release1_staging_access_pack.md", """
# RELEASE-1-STAGING-ACCESS-PACK

## 1. 문서 목적
`RELEASE-1-STAGING-SMOKE-RERUN`을 실제 Linux staging host에서 안전하게 재실행하기 위한 접근·권한·입력 준비 팩입니다. 현재 staging pilot은 승인되지 않았습니다.

## 2. 현재 RELEASE 상태
RELEASE-1 local dry run과 RELEASE-1-FIX LABPAY 성능 패치는 PASS입니다. 실제 host smoke는 Linux staging host와 isolated restore 권한이 없어 HOLD입니다. LABPAY patch는 승인 시 staging 배포 전에 commit해야 합니다.

## 3. 왜 현재 HOLD인지
actual Linux staging host, Service account, Gunicorn/Nginx 실행 권한, isolated restore DB 생성 권한, media backup policy가 제공되지 않았습니다.

## 4. 다음 재실행에 필요한 필수 입력
host identifier, SSH method, service account, project/venv path, branch/commit, settings module, secure env-file path, staging domain, database classification, isolated restore target, backup location, Nginx/Gunicorn service names, and approvers.

## 5. Linux staging host 요구사항
Linux host with controlled SSH access, Nginx, systemctl, PostgreSQL client tools, non-production network/DB endpoint, and sufficient disk for static/media and archive verification are required.

## 6. Service account 요구사항
Service account must read the secure environment file, application code, static/media paths, and Gunicorn logs. It must not be a production administrative account.

## 7. Git/branch/commit 요구사항
Release owner must provide the deployment branch and immutable commit SHA. The accepted LABPAY performance patch is currently pending commit; no unrelated uncommitted file may be deployed.

## 8. Python/venv 요구사항
Provide Python version, virtualenv path, dependency installation owner, and a read-only command for `python -c "import config.wsgi"`.

## 9. Django settings/env 요구사항
Use `config.settings.prod` or an approved staging-equivalent settings module. SECRET_KEY and DATABASE_URL status may be reported as PRESENT only; values must never be printed. DEBUG must be false, ALLOWED_HOSTS and CSRF_TRUSTED_ORIGINS must match the staging domain.

## 10. PostgreSQL staging DB 요구사항
State host class, database name, role privilege, and proof that it is not production. Production DB must not be used.

## 11. Isolated restore DB 요구사항
Isolated restore target must contain `restore`, `drill`, `test`, or `demo`, must not overwrite active DB, and requires CREATEDB or a pre-created empty DB approved by DB owner.

## 12. Backup/archive 요구사항
Provide archive location, checksum, pg_restore path, retention owner, and evidence storage path. Archive contents and raw PII are never printed.

## 13. Nginx 요구사항
Provide active site config path, nginx -t/reload authority, proxy_pass bind, HTTPS policy, static/media policy, upload size, timeout, forwarded headers, and log paths.

## 14. Gunicorn/systemd 요구사항
Provide service unit path/name, bind address, worker/timeout settings, restart/journalctl authority, and secure environment file path.

## 15. Static/media/upload 정책 요구사항
Confirm STATIC_ROOT/MEDIA_ROOT ownership, generated Excel storage, Korean filename smoke, protected download policy, media backup, encryption/retention, and Nginx direct-serving decision.

## 16. Smoke/RBAC test user 요구사항
Provide staging-safe CEO/HQ/FIELD test accounts with no real personal data. FIELD must be assigned only to the sanitized pilot project.

## 17. 금지 작업
No production deployment, production DB connection/write, active DB restore, real e-card upload, migration, destructive cleanup, secret printing, or RBAC/security relaxation.

## 18. 실행 권한 범위
The release operator may run only approved read-only smoke commands, controlled service checks, and isolated restore commands. Restart/reload/restore require the authority matrix approval.

## 19. 산출 Evidence 목록
Return service/nginx checks, HTTPS health, route/RBAC matrix, restore verification, settings status, static/media policy, logs with secrets removed, and source scan.

## 20. Staging pilot 승인 기준
Actual Gunicorn/Nginx/HTTPS smoke, isolated restore, core route/RBAC PASS, no P0, and release-owner approval are required. Limited staging pilot is distinct from production release.

## 21. Production release와의 차이
Production remains excluded. Real e-card file verification and final revenue policy remain separate production gates.

## 22. 다음 프롬프트 연결
Use `RELEASE-1-STAGING-SMOKE-RERUN` only after every required input is marked PROVIDED and authority is approved.
""")

    write_csv("release1_staging_access_questionnaire.csv", ["Question_ID", "Area", "Required_Input", "Why_Required", "Example_Answer_No_Secret", "Required_Before_Rerun", "Required_Before_Production", "Owner", "Status", "Notes"], [
        ("Q-01", "staging host", "masked host identifier", "actual host smoke", "stg-app-01 or staging.example.com", "YES", "YES", "infra", "MISSING", "no production host"),
        ("Q-02", "OS", "Linux distribution/version", "systemctl package paths", "Ubuntu LTS", "YES", "YES", "infra", "MISSING", ""),
        ("Q-03", "SSH", "SSH access method", "controlled operator access", "approved bastion + key reference", "YES", "YES", "infra", "MISSING", "no key value"),
        ("Q-04", "service account", "service account name", "Gunicorn ownership", "erp-staging", "YES", "YES", "infra", "MISSING", "least privilege"),
        ("Q-05", "paths", "project root and venv path", "commands/service unit", "/srv/construction-erp and /srv/venv", "YES", "YES", "infra", "MISSING", ""),
        ("Q-06", "Git", "branch and commit", "immutable release artifact", "feature/t10-ceo-kpi + <COMMIT_SHA>", "YES", "YES", "release owner", "MISSING", "commit LABPAY patch first"),
        ("Q-07", "settings module", "settings module and env-file path", "safe config loading", "config.settings.prod + <SECURE_ENV_FILE>", "YES", "YES", "release owner", "MISSING", "do not send values"),
        ("Q-08", "domain", "staging domain / allowed hosts / CSRF origin", "HTTPS host validation", "staging.example.com", "YES", "YES", "infra", "MISSING", "allowlist only"),
        ("Q-09", "database", "database host class/name/role privilege", "prove non-production", "staging PostgreSQL / erp_staging / least privilege", "YES", "YES", "DB owner", "MISSING", "no URL/password"),
        ("Q-10", "restore target DB", "restore target DB and CREATEDB/pre-created approval", "isolated restore", "erp_staging_restore_drill", "YES", "YES", "DB owner", "MISSING", "must not be active DB"),
        ("Q-11", "backup", "archive path/checksum", "restore integrity", "<BACKUP_DIR>/erp.dump + SHA256", "YES", "YES", "DB owner", "MISSING", ""),
        ("Q-12", "media", "media root and backup method", "sensitive Excel policy", "/srv/app/media + encrypted backup", "YES", "YES", "infra", "MISSING", ""),
        ("Q-13", "Nginx", "site config path / nginx -t authority", "proxy validation", "/etc/nginx/sites-enabled/erp", "YES", "YES", "infra", "MISSING", ""),
        ("Q-14", "Gunicorn", "service name / systemctl authority", "service smoke", "construction-erp-staging", "YES", "YES", "infra", "MISSING", ""),
        ("Q-15", "test users", "CEO/HQ/FIELD staging-safe accounts", "route/RBAC smoke", "ceo-test, hq-test, field-test", "YES", "YES", "release owner", "MISSING", "no real PII"),
        ("Q-16", "approvals", "rollback and staging pilot approver", "go/no-go authority", "release owner + infra owner", "YES", "YES", "release owner", "MISSING", "staging pilot approver"),
    ])

    write_csv("release1_staging_authority_matrix.csv", ["Authority_ID", "Activity", "Required_Role", "Allowed_Operator", "Approval_Required", "Approval_Owner", "Evidence_Required", "Forbidden_Without_Approval", "Notes"], [
        ("A-01", "SSH login", "staging operator", "approved release operator", "YES", "infra", "access confirmation", "YES", "bastion policy"),
        ("A-02", "pull/fetch code", "deploy operator", "service owner", "YES", "release owner", "commit SHA", "YES", "no branch drift"),
        ("A-03", "install Python dependencies", "deploy operator", "service owner", "YES", "release owner", "pip result", "YES", "lock approved versions"),
        ("A-04", "set environment variables", "config custodian", "infra", "YES", "security owner", "status only", "YES", "no values printed"),
        ("A-05", "run migrations", "DB/deploy operator", "DB owner", "YES", "release owner", "backup + migrate output", "YES", "not part of current smoke"),
        ("A-06", "restart Gunicorn", "systemd operator", "infra", "YES", "infra", "systemctl status", "YES", ""),
        ("A-07", "reload Nginx", "systemd operator", "infra", "YES", "infra", "nginx -t + reload", "YES", ""),
        ("A-08", "run nginx -t", "Nginx operator", "infra", "YES", "infra", "nginx test output", "YES", ""),
        ("A-09", "create isolated restore DB", "DB owner", "DB operator", "YES", "DB owner", "DB name + privilege", "YES", "CREATEDB or pre-created"),
        ("A-10", "restore backup to isolated DB", "DB owner", "DB operator", "YES", "DB owner", "restore log/checksum", "YES", "never active DB"),
        ("A-11", "inspect media folder", "storage operator", "infra", "YES", "security owner", "permission summary", "YES", "no file content"),
        ("A-12", "create media backup", "storage operator", "infra", "YES", "DB/security owner", "backup ID/checksum", "YES", "encrypted destination"),
        ("A-13", "run smoke tests", "release operator", "approved tester", "YES", "release owner", "matrices", "YES", "test users only"),
        ("A-14", "approve limited staging pilot", "release approver", "release owner", "YES", "release owner", "approval form", "YES", "production excluded"),
        ("A-15", "approve production release", "executive/release authority", "designated approver", "YES", "production owner", "separate gate", "YES", "not in this pack"),
    ])

    write_csv("release1_staging_env_var_request_template.csv", ["Env_Key", "Purpose", "Required_For_Staging", "Required_For_Production", "Expected_Status", "Allowed_To_Print_Value", "Example_Format_No_Secret", "Validation_Method", "Notes"], [
        ("DJANGO_SETTINGS_MODULE", "settings selection", "YES", "YES", "PRESENT", "YES", "config.settings.prod", "echo name only", ""),
        ("SECRET_KEY", "Django signing", "YES", "YES", "PRESENT", "NO", "SECRET_KEY=PRESENT", "presence only", ""),
        ("DEBUG", "debug mode", "YES", "YES", "FALSE", "YES", "false", "settings status", ""),
        ("ALLOWED_HOSTS", "host validation", "YES", "YES", "ALLOWLIST", "YES", "staging.example.com", "config review", "no wildcard"),
        ("CSRF_TRUSTED_ORIGINS", "CSRF validation", "YES", "YES", "PRESENT", "YES", "https://staging.example.com", "config review", ""),
        ("DATABASE_URL / DATABASE", "PostgreSQL", "YES", "YES", "PRESENT", "NO", "DATABASE_URL=PRESENT", "connection status only", ""),
        ("STATIC_ROOT", "static collection", "YES", "YES", "WRITABLE", "YES", "/srv/app/staticfiles", "path permission", ""),
        ("MEDIA_ROOT", "uploads and Excel", "YES", "YES", "WRITABLE_RESTRICTED", "YES", "/srv/app/media", "path permission", ""),
        ("STATIC_URL / MEDIA_URL", "URL routing", "YES", "YES", "PRESENT", "YES", "/static/ and /media/", "Nginx smoke", ""),
        ("SECURE_SSL_REDIRECT", "HTTPS", "YES", "YES", "TRUE", "YES", "true", "settings status", ""),
        ("SESSION_COOKIE_SECURE", "secure session", "YES", "YES", "TRUE", "YES", "true", "settings status", ""),
        ("CSRF_COOKIE_SECURE", "secure CSRF", "YES", "YES", "TRUE", "YES", "true", "settings status", ""),
        ("LOG_LEVEL", "logging", "YES", "YES", "PRESENT", "YES", "INFO", "settings status", "no PII logs"),
        ("EMAIL settings", "optional notification", "NO", "AS_REQUIRED", "NOT_APPLICABLE", "NO", "PRESENT if used", "presence only", ""),
        ("AWS/S3 settings", "optional storage", "NO", "AS_REQUIRED", "NOT_APPLICABLE", "NO", "PRESENT if used", "presence only", ""),
        ("HEALTHCHECK_ALLOWED_HOST", "health policy", "NO", "AS_REQUIRED", "NOT_APPLICABLE", "YES", "staging.example.com", "route smoke", ""),
    ])

    write_csv("release1_staging_db_restore_authority_checklist.csv", ["Check_ID", "Requirement", "Current_Status", "Required_Status", "Why_Required", "Safe_Command_Template", "Evidence_File", "Result", "Notes"], [
        ("D-01", "confirm staging DB is not production", "UNKNOWN", "not production", "prevent production write", "psql <STAGING_DB> -c 'select current_database()'", "restore safety check", "HOLD", "no credentials printed"),
        ("D-02", "confirm restore target is isolated", "MISSING", "isolated", "prevent active DB overwrite", "createdb <RESTORE_DB_NAME>", "restore log", "HOLD", "name contains restore/drill"),
        ("D-03", "confirm restore DB name", "MISSING", "provided", "target control", "echo <RESTORE_DB_NAME>", "approval form", "HOLD", "safe identifier only"),
        ("D-04", "confirm CREATEDB or pre-created DB", "DENIED_LOCAL", "CREATEDB or pre-created", "restore authority", "psql -c 'select rolcreatedb'", "privilege check", "HOLD", "DB owner"),
        ("D-05", "confirm backup archive path", "LOCAL_ONLY", "provided", "archive integrity", "pg_restore --list <BACKUP_FILE>", "archive list", "HOLD", ""),
        ("D-06", "confirm backup checksum", "LOCAL_ONLY", "provided", "tamper detection", "sha256sum <BACKUP_FILE>", "checksum evidence", "HOLD", ""),
        ("D-07", "confirm pg_restore available", "LOCAL_ONLY", "available", "restore execution", "pg_restore --version", "command output", "HOLD", ""),
        ("D-08", "confirm restore does not target active DB", "MISSING", "isolated", "non-destructive", "pg_restore --dbname <RESTORE_DB_NAME> <BACKUP_FILE>", "restore log", "HOLD", ""),
        ("D-09", "confirm restore verification command", "MISSING", "provided", "post-restore smoke", "python manage.py check", "restore report", "HOLD", ""),
        ("D-10", "confirm AuditLog preservation check", "MISSING", "required", "audit continuity", "select count from audit log", "restore report", "HOLD", "count only"),
        ("D-11", "confirm cleanup policy", "MISSING", "approved", "retain evidence", "dropdb <RESTORE_DB_NAME> only if approved", "approval form", "HOLD", ""),
        ("D-12", "confirm media backup policy", "PENDING", "approved", "sensitive Excel", "archive metadata only", "media policy", "HOLD", ""),
    ])

    write_csv("release1_staging_nginx_gunicorn_execution_checklist.csv", ["Check_ID", "Area", "Requirement", "Command_Template", "Expected_Result", "Evidence_File", "Status", "Notes"], [
        ("G-01", "WSGI", "WSGI import", "python -c \"import config.wsgi; print('WSGI_IMPORT_OK')\"", "WSGI_IMPORT_OK", "actual WSGI output", "PENDING", ""),
        ("G-02", "Gunicorn", "Gunicorn import", "python -c \"import gunicorn; print('GUNICORN_IMPORT_OK')\"", "GUNICORN_IMPORT_OK", "actual Gunicorn output", "PENDING", ""),
        ("G-03", "Gunicorn", "systemd service file path", "systemctl cat <GUNICORN_SERVICE>", "approved unit", "service config", "PENDING", ""),
        ("G-04", "Gunicorn", "service status", "systemctl status <GUNICORN_SERVICE> --no-pager", "active", "gunicorn status", "PENDING", ""),
        ("G-05", "Gunicorn", "restart permission", "sudo systemctl restart <GUNICORN_SERVICE>", "approved restart", "approval form", "PENDING", ""),
        ("G-06", "Gunicorn", "journalctl check", "journalctl -u <GUNICORN_SERVICE> -n 100 --no-pager", "no startup error", "journal excerpt", "PENDING", "mask secrets"),
        ("G-07", "Nginx", "Nginx config file path", "sudo nginx -T", "active site identified", "Nginx config summary", "PENDING", "mask secrets"),
        ("G-08", "Nginx", "nginx -t", "sudo nginx -t", "syntax successful", "nginx test", "PENDING", ""),
        ("G-09", "Nginx", "reload permission", "sudo systemctl reload nginx", "approved reload", "approval form", "PENDING", ""),
        ("G-10", "Nginx", "HTTPS health request", "curl -fsS https://<STAGING_DOMAIN>/healthz/", "200", "health result", "PENDING", ""),
        ("G-11", "Nginx", "proxy_pass to Gunicorn", "grep proxy_pass <NGINX_SITE>", "<GUNICORN_BIND>", "config summary", "PENDING", ""),
        ("G-12", "Nginx", "static alias", "grep static <NGINX_SITE>", "STATIC_ROOT", "static smoke", "PENDING", ""),
        ("G-13", "Nginx", "media alias/policy", "grep media <NGINX_SITE>", "approved media policy", "media policy", "PENDING", ""),
        ("G-14", "Nginx", "upload size", "grep client_max_body_size <NGINX_SITE>", "Excel limit", "config summary", "PENDING", ""),
        ("G-15", "Nginx", "timeout", "grep proxy_read_timeout <NGINX_SITE>", "120s or approved", "config summary", "PENDING", ""),
        ("G-16", "Nginx", "forwarded headers", "grep X-Forwarded-Proto <NGINX_SITE>", "header present", "config summary", "PENDING", ""),
        ("G-17", "Nginx", "log paths", "grep -E 'access_log|error_log' <NGINX_SITE>", "writable paths", "log summary", "PENDING", ""),
    ])

    write_csv("release1_staging_media_backup_policy_template.csv", ["Area", "Policy_Question", "Required_For_Staging", "Required_For_Production", "Current_Answer", "Recommended_Answer", "Risk_If_Unresolved", "Owner", "Notes"], [
        ("media", "media contains real upload files", "YES", "YES", "UNKNOWN", "inventory before pilot", "sensitive data exposure", "security", ""),
        ("media", "media contains sensitive Excel", "YES", "YES", "UNKNOWN", "treat as sensitive Excel", "privacy breach", "security", ""),
        ("media", "media is backed up", "YES", "YES", "PENDING", "encrypted scheduled backup", "data loss", "infra", ""),
        ("media", "encrypted at rest", "YES", "YES", "UNKNOWN", "approved encrypted storage", "data exposure", "security", ""),
        ("media", "Nginx may serve media directly", "YES", "YES", "UNKNOWN", "protected download unless approved public", "unauthorized download", "security", ""),
        ("media", "retention period", "YES", "YES", "PENDING", "documented retention", "unbounded storage", "ops", ""),
        ("media", "backup storage location", "YES", "YES", "PENDING", "separate protected location", "single-host loss", "infra", ""),
        ("media", "restore test", "YES", "YES", "PENDING", "isolated restore verification", "unverified recovery", "infra", ""),
        ("media", "Korean filename handling", "YES", "YES", "NOT_TESTED", "upload/download smoke", "filename corruption", "QA", ""),
        ("media", "Excel generated files", "YES", "YES", "PENDING", "writable restricted storage", "failed export", "infra", ""),
    ])

    write_csv("release1_staging_smoke_rerun_input_manifest.csv", ["Input_ID", "Required_Input", "Provided_Value_Status", "Example_No_Secret", "Used_By", "Required", "Blocker_If_Missing", "Notes"], [
        ("I-01", "Linux staging host + SSH method", "MISSING", "stg-app-01 via approved bastion", "all host checks", "YES", "host smoke cannot start", ""),
        ("I-02", "service account + project/venv paths", "MISSING", "erp-staging /srv/app /srv/venv", "Gunicorn", "YES", "service check blocked", ""),
        ("I-03", "branch/commit", "MISSING", "<COMMIT_SHA>", "deployment validation", "YES", "artifact not immutable", "commit LABPAY patch"),
        ("I-04", "settings/env status", "MISSING", "config.settings.prod; SECRET_KEY=PRESENT", "security smoke", "YES", "security check blocked", "no values"),
        ("I-05", "staging DB classification", "MISSING", "non-production staging PostgreSQL", "restore safety", "YES", "restore blocked", ""),
        ("I-06", "isolated restore target authority", "MISSING", "erp_staging_restore_drill", "restore drill", "YES", "restore blocked", "CREATEDB or pre-created"),
        ("I-07", "backup path/checksum", "MISSING", "<BACKUP_DIR>/erp.dump", "restore drill", "YES", "restore blocked", ""),
        ("I-08", "Nginx/Gunicorn service config and authority", "MISSING", "service names and config paths", "proxy smoke", "YES", "proxy check blocked", ""),
        ("I-09", "media policy", "MISSING", "restricted media + encrypted backup", "upload/export scope", "YES", "staging policy blocked", ""),
        ("I-10", "CEO/HQ/FIELD safe test accounts", "MISSING", "role-specific staging accounts", "RBAC smoke", "YES", "RBAC smoke blocked", ""),
        ("I-11", "release owner approval", "MISSING", "approved limited smoke scope", "go/no-go", "YES", "rerun not authorized", "production excluded"),
    ])

    write("release1_staging_owner_approval_form.md", """
# Staging Access and Smoke Approval Form

## 승인 목적
Authorize the limited, non-production `RELEASE-1-STAGING-SMOKE-RERUN` scope.

## 현재 상태
Local application smoke passed, but staging host and isolated restore authority are missing. Limited staging pilot is not approved by this form alone.

## 제공할 Staging 정보
- Host identifier and SSH method:
- Service account and project/venv paths:
- Branch/commit:
- Settings module and secure env-file path:
- Staging DB classification and isolated restore target:
- Backup archive/checksum location:
- Gunicorn/Nginx service/config paths:
- Media backup policy:

## 허용 작업
Read-only discovery, WSGI/Gunicorn/Nginx validation, approved service restart/reload, HTTPS health/route/RBAC smoke, and restore only to an approved isolated DB.

## 금지 작업
No production host/DB access, active DB restore, migration unless separately approved, destructive cleanup, real e-card upload, secret printing, or production release.

## Restore 권한 승인
- Restore target is isolated and not production:
- CREATEDB or pre-created empty DB provided:
- DB owner approval:

## Nginx/Gunicorn 작업 승인
- nginx -t/reload approver:
- Gunicorn restart/journalctl approver:

## Staging smoke 실행 승인
- Scope approved:
- Restrictions:

## Limited staging pilot 승인 조건
Actual host smoke, isolated restore, RBAC PASS, no P0, and release owner go/no-go are mandatory.

## Production release 제외 확인
Production release is explicitly excluded from this approval.

Approver:
Date:
Signature or explicit instruction:
Notes:
""")

    write_csv("release1_staging_access_gap_register.csv", ["Gap_ID", "Area", "Gap", "Severity", "P0_P1_P2", "Blocks_Rerun", "Blocks_Staging_Pilot", "Blocks_Production", "Required_Action", "Owner", "Status", "Notes"], [
        ("GAP-01", "Host", "Linux staging host missing", "HIGH", "P1", "YES", "YES", "YES", "provide host and SSH method", "infra", "OPEN", ""),
        ("GAP-02", "Proxy", "Gunicorn/Nginx actual execution missing", "HIGH", "P1", "YES", "YES", "YES", "authorize systemctl and nginx -t", "infra", "OPEN", ""),
        ("GAP-03", "Restore", "isolated restore DB privilege missing", "HIGH", "P1", "YES", "YES", "YES", "CREATEDB or pre-create isolated DB", "DB owner", "OPEN", ""),
        ("GAP-04", "Media", "media backup policy pending", "HIGH", "P1", "YES", "YES", "YES", "approve storage/retention/access policy", "security", "OPEN", ""),
        ("GAP-05", "Finance", "final revenue accounting policy pending", "MEDIUM", "P1", "NO", "NO", "YES", "approve finance policy", "finance", "OPEN", "separate"),
        ("GAP-06", "LABPAY", "safe real e-card file pending", "MEDIUM", "P2", "NO", "NO", "YES", "sanitized safe-file validation", "labor", "OPEN", "separate"),
        ("GAP-07", "Operations", "user training pending", "MEDIUM", "P2", "NO", "YES", "YES", "pilot rehearsal", "ops", "OPEN", ""),
        ("GAP-08", "Release", "production release remains excluded", "HIGH", "P1", "NO", "NO", "YES", "complete separate production gates", "release owner", "OPEN", ""),
    ])

    write_csv("release1_staging_access_evidence_manifest.csv", ["Evidence_ID", "Artifact", "Purpose", "Contains_Secret", "Contains_PII", "Source", "Reviewer", "Notes"], [
        ("AP-E01", "release1_staging_access_pack.md", "coordination guide", "NO", "NO", "RELEASE-1 evidence", "release owner", "documentation only"),
        ("AP-E02", "release1_staging_access_questionnaire.csv", "collect required inputs", "NO", "NO", "access gaps", "infra", "placeholders only"),
        ("AP-E03", "release1_staging_authority_matrix.csv", "approve activities", "NO", "NO", "governance", "release owner", ""),
        ("AP-E04", "release1_staging_env_var_request_template.csv", "safe config request", "NO", "NO", "settings discovery", "security", "values forbidden"),
        ("AP-E05", "release1_staging_db_restore_authority_checklist.csv", "safe restore prep", "NO", "NO", "restore HOLD", "DB owner", ""),
        ("AP-E06", "release1_staging_nginx_gunicorn_execution_checklist.csv", "host execution plan", "NO", "NO", "RELEASE-1-FIX templates", "infra", ""),
        ("AP-E07", "release1_staging_media_backup_policy_template.csv", "media policy", "NO", "NO", "staging smoke gap", "security", ""),
        ("AP-E08", "release1_staging_owner_approval_form.md", "scope approval", "NO", "NO", "governance", "release owner", ""),
    ])
    write("release1_staging_access_quick_message_to_infra.md", """
# Request to Infra: staging smoke inputs

Please provide the completed questionnaire and approval form for a non-production smoke only. Required: Linux staging host/SSH, service account, branch/commit, safe settings status, non-production DB classification, isolated restore DB authority, backup checksum location, Nginx/Gunicorn service paths/authority, media backup policy, and staging-safe CEO/HQ/FIELD test accounts. Do not send passwords, keys, DATABASE_URL values, or production credentials.
""")
    write("release1_staging_smoke_rerun_command_plan.md", """
# RELEASE-1-STAGING-SMOKE-RERUN command plan

1. Validate host identity, non-production DB class, branch/commit, and secure env status.
2. Run WSGI import, Gunicorn import/service status, Nginx nginx -t, then HTTPS healthz.
3. Verify static/media policy without reading sensitive file contents.
4. Create or use approved isolated restore DB; verify archive checksum; restore without touching active DB; run migration/health/count-only AuditLog checks.
5. Run CEO/HQ/FIELD/LABPAY route and RBAC smoke with staging-safe test accounts.
6. Scan evidence for UTF-8, secrets, and raw PII; request limited staging pilot approval only if P0 is zero.
""")
    scan()


if __name__ == "__main__":
    main()
