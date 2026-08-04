# ERP 관리자 Runbook

## 일상 점검
```powershell
python manage.py check
python manage.py makemigrations --check --dry-run
```
오류가 있으면 배포·데이터 정리 전에 원인을 기록합니다. source scan으로 한글 UTF-8과 개인정보 노출 여부를 확인합니다.

## 데이터 작업 원칙
- 프로젝트 삭제는 반드시 dry-run manifest를 먼저 생성하고 `--apply`를 별도로 실행합니다.
- 로컬/demo DB에서만 정리 도구를 실행합니다.
- 운영 DB 삭제·복구는 백업과 승인 없이 실행하지 않습니다.
- Global CBS, 사용자, 역할, 권한, AuditLog는 프로젝트 정리 대상에 포함하지 않습니다.

## 장애 대응
**Dashboard 500**: URL, 역할, 기준일, 서버 로그를 기록하고 최근 배포·관계명·템플릿 오류를 확인합니다.

**RBAC bypass**: 즉시 접근을 중지하고 역할·ProjectAssignment·라우트 권한을 점검합니다.

**Closing guard failure**: 원본 데이터를 변경하지 말고 마감 상태와 승인된 정정 흐름을 확인합니다.

**raw PII exposure**: 로그·다운로드·화면을 차단하고 보안 담당자에게 알립니다.

**Excel generation failure**: 원본 파일을 보존하고 배치 상태·파일 저장소·권한·AuditLog를 확인합니다.

## rollback 원칙
코드는 승인된 배포 버전으로 rollback할 수 있습니다. 데이터 rollback은 검증된 백업이 있어야 하며, AuditLog는 보존합니다.

## RELEASE-1 준비
RELEASE-1 전에는 백업·복구 드릴, 배포 dry-run, 사용자 교육, LABPAY 안전 실파일 검증, 최종 회계 매출 정책을 완료합니다.
