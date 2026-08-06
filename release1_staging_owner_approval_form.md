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
