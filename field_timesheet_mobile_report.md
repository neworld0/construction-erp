# FIELD-TIMESHEET-MOBILE-UX-01 운영 보고서

## 결과

FIELD 출역부 입력 화면을 모바일 카드형 UI로 변경했다. 근로자 검색, WorkerMaster FK 저장, 기본 노무 역할 반영, 기존 마감·승인 보호는 유지된다. 마이그레이션은 없다.

## 모바일 동작

- 작업 정보: 프로젝트, 작업일자, 작업 비고
- 출역 근로자 카드: 근로자 검색과 선택 결과 요약
- 노무 내역: 노무역할, 공수, 시간, 단가유형
- 메모: 각 출역 행의 특이사항 textarea
- 액션: 모바일 sticky 임시저장, 목록, 출역 저장 및 제출

## 검증

- `python manage.py check`: PASS
- `python manage.py makemigrations --check --dry-run`: PASS
- 단일 통합 pytest 실행: 90 passed
- 브라우저 시각 검증: 제어 가능한 브라우저 연결 부재로 HOLD. 실제 FIELD 계정으로 360px, 390px, 414px 폭 확인이 남아 있다.

## 롤백

이 변경은 템플릿과 테스트만 포함한다. DB 롤백은 필요 없다. 문제가 있으면 `templates/app/field/timesheet_form.html`과 `apps/labor/tests/test_field_timesheet_mobile_ui.py`만 되돌리면 된다.
