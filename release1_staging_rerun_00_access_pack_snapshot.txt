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
