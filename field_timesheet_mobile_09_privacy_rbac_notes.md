# FIELD 출역부 모바일 UI 개인정보·권한 점검

- 접근 뷰는 `require_role(request.user, [Role.FIELD])`를 유지한다.
- 근로자 검색 API는 FIELD 역할과 프로젝트 배정 권한을 검증한다.
- 화면의 안전한 근로자 표시는 `근로자명 / 기본 노무 역할`이다.
- 주민등록번호, 연락처, 계좌번호, 주소는 검색 응답과 모바일 입력 카드에 표시하지 않는다.
- FIELD의 HQ 근로자 마스터 신규 URL 접근은 403으로 차단된다.
- UI 패치는 `create_timesheet`, `upsert_timesheet_lines`, `_assert_month_open` 및 승인 상태 잠금 로직을 변경하지 않는다.
