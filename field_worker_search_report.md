# FIELD-TIMESHEET-WORKER-SEARCH-01 결과

## 결과

FIELD 출역부에 이름 또는 직종으로 활성 근로자를 찾는 검색형 선택기를 적용했다. 선택 결과는 기존 `TimesheetLine.worker` FK 저장 흐름에 연결된다.

## 보안과 권한

- 검색은 FIELD 역할만 사용할 수 있다.
- 요청한 프로젝트가 FIELD 사용자에게 배정되지 않았으면 403을 반환한다.
- 검색 결과는 `id`, `text`, `role_id`만 반환한다.
- `text`는 근로자 이름과 기본 노무 역할명만 사용한다.
- 주민등록번호, 연락처, 계좌번호, 주소는 검색 조건, JSON 응답, 화면 후보에 포함하지 않는다.

## 검증

- `python manage.py check`: PASS
- `python manage.py makemigrations --check --dry-run`: PASS, 변경 없음
- `pytest -q apps/labor/tests/test_field_timesheet_worker_search.py apps/labor/tests/test_field_timesheet_worker_selection.py apps/labor/tests/test_e_card_imports.py`: PASS, 51 passed

pytest 종료 과정에서 Windows 공용 임시 폴더 권한 경고가 있었으나, pytest 종료 코드는 0이고 테스트는 통과했다.

## 후속 과제

현재 데이터 모델에는 근로자-프로젝트 배정 관계가 없다. 따라서 이번 단계에서는 FIELD 사용자의 프로젝트 접근을 검증하고 회사의 활성 근로자를 후보로 제공한다. 근로자별 현장 제한이 필요해지면 P2로 별도 배정 정책과 모델을 설계한다.
