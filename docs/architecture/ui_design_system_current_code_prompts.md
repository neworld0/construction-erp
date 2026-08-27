# UI 디자인 재구성 프롬프트 — 현재 코드 기준

작성일: 2026-08-24  
적용 순서: `UI-DESIGN-SYSTEM-01` → `FIELD-MOBILE-HOME-01` → `FIELD-MOBILE-INPUTS-01` → `CEO-MOBILE-COCKPIT-01` → `HQ-OPERATIONS-HUB-01` → `UI-REGRESSION-AUDIT-01`

## 공통 전제

- Django 5.2 기반 `construction-erp`의 기존 업무 로직, URL, RBAC, AuditLog, Closing/Adjustment 정책은 유지한다.
- 현재 법인 범위는 화면의 필수 문맥이다. FIELD/HQ는 선택한 운영 법인만, CEO는 `아산`·`미산`·`아미산(그룹합산)` 중 선택 범위만 보여야 한다.
- `Project.legal_entity`, `UserLegalEntityMembership`, `ProjectAssignment`, `get_current_legal_entity()` 및 기존 프로젝트 접근 검증을 우회하거나 화면 편의를 위해 넓히지 않는다.
- 화면의 한글 상태값은 `임시저장`, `제출`, `승인 대기`, `승인`, `반려`, `마감`으로 통일한다. 기존 `field_status`, `utils` 태그와 공통 `.status-badge`를 우선 사용한다.
- 현재 공통 골격은 `templates/app/base_app.html`, FIELD 공통 탭은 `templates/components/field_tabs.html` 및 각 FIELD 템플릿, CEO는 `apps/ceo/templates/ceo/app_home.html`, HQ는 `templates/app/hq_home.html`이다.
- 데이터 모델·마이그레이션은 이 UI 작업의 기본 범위가 아니다. 꼭 필요해지는 경우에만 별도 승인과 migration/test를 수행한다.

---

## [UI-DESIGN-SYSTEM-01] 공통 색상·카드·버튼·배지·모바일 액션 디자인 시스템 적용

### 1. FAST-CODEX Prompt

`templates/app/base_app.html`을 단일 디자인 토큰의 기준으로 정리한다. 다크 테마는 유지하되, 색상·간격·테두리·그림자·글자 크기·입력 컨트롤을 CSS 변수와 재사용 클래스에 모은다. `.card`, `.btn`, `.btn-outline`, `.status-badge`, `.alert`, 표, 폼, 빈 상태, 모바일 액션 바를 통일한다. 헤더의 운영 법인 선택기와 `이전 화면/홈페이지로/로그아웃`은 모든 폭에서 잘리거나 늘어나지 않아야 한다. 화면별 광범위 CSS(`button`, `form`, `table` 등)가 공통 헤더를 깨지 않도록 범위를 페이지 컨테이너로 한정한다. 현존 URL과 POST name/action은 바꾸지 않는다.

### 2. Discovery Contract

- `base_app.html`의 헤더, 법인 전환 form, 전역 버튼, 상태 배지 및 각 템플릿의 중복 CSS를 조사한다.
- `field_status`와 `utils` 사용처, 인라인 상태 표현, 기존 모바일 media query를 목록화한다.
- CSS 변경 전에 FIELD/HQ/CEO 각 1개 대표 화면의 360px·768px·1440px 캡처 기준을 잡는다.

### 3. Reproduction/Test Harness

- FIELD `/app/field/`, HQ `/app/hq/`, CEO `/app/ceo/`에서 헤더·운영법인 선택·전역 버튼·상태 배지를 확인한다.
- 임시저장/제출/승인/반려/마감 샘플 상태의 한글·색상·크기를 확인한다.
- `manage.py check`, 대상 템플릿 렌더 테스트, 360px overflow 검사를 실행한다.

### 4. Eval Gate / Promotion Criteria

- 공통 UI는 동일 클래스와 토큰으로 표현되고, 전역 버튼 라벨이 어떤 화면에서도 잘리지 않는다.
- 법인 선택기와 권한 동작은 변경 전과 같다.
- 상태 영어 원문이 FIELD 사용자 화면에 노출되지 않는다.

### 5. Rollback & Operational Audit Checklist

- CSS/템플릿만 변경하며 DB는 변경하지 않는다.
- 변경 파일과 화면별 전/후 캡처·검증 결과를 기록한다.
- 로그인·법인 전환·제출 버튼 작동 이상이 확인되면 해당 공통 스타일 변경만 되돌린다.

---

## [FIELD-MOBILE-HOME-01] FIELD 모바일 홈/하단 탭/오늘 할 일 구조 적용

### 1. FAST-CODEX Prompt

`apps/field/templates/field/dashboard.html`과 `templates/components/field_tabs.html`을 기준으로 FIELD 홈을 모바일 우선 구조로 재구성한다. 프로젝트 선택과 현재 운영 법인을 상단에 명확히 표시하고, `진행률·보고서·원가·자재 투입·창고 조회·출역부·승인완료`를 같은 아이콘/원형 또는 pill 탭 체계로 제공한다. 모바일에서는 하단 고정 내비게이션 또는 접근성 있는 대체 방식으로 오늘 주로 쓰는 입력 기능에 즉시 접근하게 한다. 오늘 할 일은 미제출, 반려 후 수정 필요, 승인 대기, 마감/소급 요청 등 실제 상태만 표시하고 해당 상세 URL로 이동시킨다. 탭과 목록은 현재 선택 법인 및 배정 프로젝트만 표시해야 한다.

### 2. Discovery Contract

- `field_dashboard` context의 프로젝트·진행률·원가·보고서·소급요청·승인목록 데이터를 확인한다.
- 각 FIELD 하위 URL이 공통 탭을 포함하는지, 쿼리의 `project_id`를 보존하는지 확인한다.
- FIELD가 아산/미산 양쪽에 배정된 경우 운영 법인을 바꿀 때 프로젝트·할 일이 즉시 분리되는 것을 확인한다.

### 3. Reproduction/Test Harness

- 360px에서 탭·버튼·프로젝트 선택이 가로 넘침 없이 작동한다.
- 아산 선택 시 미산 프로젝트, 미산 선택 시 아산 프로젝트의 탭 링크/목록/오늘 할 일이 보이지 않는지 확인한다.
- 반려, 임시저장, 제출 상태의 각 항목이 올바른 수정 또는 상세 페이지로 연결되는지 확인한다.

### 4. Eval Gate / Promotion Criteria

- 1~2회 터치로 주요 FIELD 입력 화면에 도달한다.
- 동일한 탭 디자인과 상태 배지가 모든 FIELD 화면에 적용된다.
- URL 직접 입력으로 다른 법인·미배정 프로젝트를 열 수 없다.

### 5. Rollback & Operational Audit Checklist

- URL 및 제출 payload는 보존한다.
- 하단 탭 고정으로 제출 버튼, 날짜 선택기, 입력 행이 가려지지 않는지 확인한다.
- 오류 발생 시 기존 상단 탭을 남긴 상태로 모바일 내비게이션 변경만 되돌린다.

---

## [FIELD-MOBILE-INPUTS-01] 진행률·출역·원가·자재 입력 화면 카드형 전환

### 1. FAST-CODEX Prompt

FIELD 진행률, 원가, 자재 투입, 출역부 화면을 한 화면에 많은 표를 노출하는 방식에서 모바일 카드형 입력으로 개선한다. 각 입력행은 날짜·프로젝트·WBS/CBS·수량/공수·단가·금액·상태·메모를 읽기 쉬운 그룹으로 배치하고, 합계·자동계산·제출 가능 여부를 명확하게 표시한다. 품목명 검색 후 CBS 자동 추천, 창고 재고 기반 자재 단가 자동 반영, 출역 단가 자동 적용 같은 현재 도메인 동작을 보존한다. 제출/반려/마감/정정 제한 메시지는 사용자가 다음 조치를 알 수 있는 한글 문장으로 표시한다.

### 2. Discovery Contract

- 대상 템플릿: FIELD dashboard의 progress/cost 영역, `inventory_issue_form.html`, `timesheet_list.html` 및 관련 상세/수정 화면을 조사한다.
- 자동금액 계산 JavaScript, formset 이름, 검색 API, 서버 측 재고·마감·권한 검증을 식별한다.
- 임시저장→제출→HQ 승인/반려→수정→재제출 흐름을 화면별로 문서화한다.

### 3. Reproduction/Test Harness

- 360px에서 진행률·원가·자재·출역 각각 임시저장과 제출을 수행한다.
- 수량×자동 단가=금액, 근로자×적용 단가=노무비가 표시와 서버 저장 값 모두 일치하는지 확인한다.
- 반려 항목 수정 가능, 승인/마감 항목 수정 불가, 다른 법인/미배정 프로젝트 요청 403을 확인한다.

### 4. Eval Gate / Promotion Criteria

- 핵심 입력 항목·상태·합계·오류가 가로 스크롤 없이 보인다.
- 자동완성/추천은 현재 법인의 배정 프로젝트와 예산·재고 범위 밖 데이터를 노출하지 않는다.
- 마감 및 정정 통제, AuditLog, 승인 상태 전이는 회귀하지 않는다.

### 5. Rollback & Operational Audit Checklist

- form field name, CSRF, action, 서버 검증은 변경하지 않는다.
- 계산/제출 시나리오별 전후 데이터를 대조한다.
- 장애 시 카드 레이아웃만 복원하되, 새로 도입한 안전 메시지는 유지한다.

---

## [CEO-MOBILE-COCKPIT-01] CEO 모바일 KPI Cockpit 재구성

### 1. FAST-CODEX Prompt

`apps/ceo/templates/ceo/app_home.html`을 CEO의 모바일 Cockpit으로 재구성한다. 상단에는 기준일과 집계 범위 선택(`아산`, `미산`, `아미산(그룹합산)`)을 고정해 명확히 보이고, 아래에는 실제 누적 매출(VAT 별도), 잠정 진행률 매출(VAT 별도), 누적 원가(VAT 별도 정책), 승인 인건비, 실제/잠정 손익, 매출 인식 상태, 선급금 잔액, 기성 미수금, 평균 진행률, 예정 현금을 우선순위로 배치한다. KPI 카드는 해당 카드에 집계된 모든 발생 내역의 표 상세 화면으로 연결한다. 프로젝트 누적 막대는 여러 프로젝트를 표현하고, 막대를 선택하면 시간축 꺾은선 상세로 이동한다. 법인별/그룹별 집계는 절대 혼합되거나 동일 값으로 오표시되지 않아야 한다.

### 2. Discovery Contract

- CEO entity scope context, KPI 계산 서비스, metric detail routes, project progress detail route를 확인한다.
- ASAN/MISAN/GROUP에서 제공하는 queryset과 합산 규칙을 확인하며, 그룹은 법인별 원장 합산일 뿐 원장 혼합이 아님을 유지한다.
- VAT 표기/계산 기준과 품질 범례(`확정`, `미정`, `추정`)의 기존 문구를 보존한다.

### 3. Reproduction/Test Harness

- 각 entity scope에서 KPI 수, 승인 대기, 최근 승인, 차트 데이터가 맞는 법인 자료만 포함하는지 확인한다.
- 그룹은 아산+미산 합계로만 표시하고, 미산에 프로젝트가 없을 경우 아산 수치를 미산에 복제하지 않는지 확인한다.
- 360px/768px에서 KPI, 필터, 차트, 상세 표 링크를 확인한다.

### 4. Eval Gate / Promotion Criteria

- KPI 카드의 제목·값·상세 목록의 집계 기준이 일치한다.
- 법인 전환 직후 API와 화면 모두 동일한 법인 범위를 사용한다.
- CEO 조회 전용 HQ 화면에서는 승인 실행 버튼을 노출하지 않는다.

### 5. Rollback & Operational Audit Checklist

- KPI 산식·매출 인식·VAT·마감 스냅샷 데이터는 UI 작업으로 변경하지 않는다.
- 범위별 KPI 비교표와 화면 캡처를 남긴다.
- 범위 혼합이 감지되면 해당 Cockpit 배포를 중지하고 기존 dashboard 템플릿으로 즉시 복구한다.

---

## [HQ-OPERATIONS-HUB-01] HQ 운영 허브·승인 큐·마감 큐 재구성

### 1. FAST-CODEX Prompt

`templates/app/hq_home.html`을 HQ 실무자의 운영 허브로 재구성한다. 모든 기능 버튼을 동등하게 나열하지 말고, `지금 처리할 일`, `승인 대기`, `마감·대사`, `프로젝트·마스터`, `재무·노무` 그룹으로 정리한다. 승인 큐는 진행률, 일일보고, 원가, 자재 투입/품목 요청, 출역부, 계약·계획 변경, 기성·준공 결재를 업무 유형·프로젝트·제출자·경과 시간·상태·바로 처리로 표시한다. 월마감/준공 대사·미정산·반려·소급입력 요청은 즉시 드러나는 마감 큐로 제공한다. 선택한 운영 법인만 표시하고, 그룹 HQ는 허용된 법인 전환 후 그 법인의 큐만 처리한다.

### 2. Discovery Contract

- HQ dashboard context의 `todo_items`, pending collections, `quick_links`, `recent_actions`, risk/closing/reconciliation 데이터를 조사한다.
- 각 큐의 상세 URL과 승인 권한을 확인하며, CEO 승인 전용 기능은 HQ에서 실행 버튼을 만들지 않는다.
- 현재 운영 법인 필터가 아직 없는 HQ 창고·재무·마스터 목록을 발견하면 별도 보완 목록으로 분리한다. UI 변경으로 데이터 범위를 넓히지 않는다.

### 3. Reproduction/Test Harness

- 아산/미산을 전환해 승인 대기·최근 승인·리스크·마감 큐가 각각 분리되는지 확인한다.
- 큐의 개수와 상세 목록 count를 비교한다.
- 360px에서 우선 처리 큐가 가장 먼저 보이고, 각 바로가기 버튼이 충분한 터치 영역인지 확인한다.

### 4. Eval Gate / Promotion Criteria

- 제출된 FIELD 업무가 해당 HQ 법인의 운영 허브에서 놓치지 않고 보인다.
- 반려/마감/소급 입력 요청은 상태와 다음 조치가 명확하다.
- 미산에 프로젝트가 없는 상태에서는 아산 승인 내역이 미산 큐에 표시되지 않는다.

### 5. Rollback & Operational Audit Checklist

- 승인 실행 서비스, AuditLog, Closing 상태전이는 변경하지 않는다.
- 큐별 전후 count와 선택 법인별 비교 결과를 보관한다.
- 큐 누락 시 이전 상세 링크는 유지하고 허브 배치만 되돌린다.

---

## [UI-REGRESSION-AUDIT-01] RBAC, 한글, 모바일 viewport, AuditLog, 기존 기능 회귀 검증

### 1. FAST-CODEX Prompt

앞의 다섯 UI 작업이 끝난 뒤, 표시·접근성·권한·업무 흐름을 함께 검증한다. UI 테스트만으로 완료 처리하지 말고, FIELD/HQ/CEO/그룹 HQ/시스템 master 역할과 아산/미산/그룹 범위를 조합해 URL 직접 접근, 목록, 상세, 검색/자동완성, 제출/승인/반려/마감/정정까지 확인한다. 한글 깨짐, 영어 상태값, 모바일 가로 넘침, 버튼 오작동, 민감정보 노출, AuditLog 누락을 찾아 수정한다.

### 2. Discovery Contract

- 현재 RBAC helper, 법인 선택 session/context processor, 주요 URL과 템플릿 로드 태그를 조사한다.
- UI 변경 파일, 영향 URL, 기존 테스트를 목록화한다.
- 확인된 사실과 운영 확인이 필요한 가정을 분리한다.

### 3. Reproduction/Test Harness

- `manage.py check`, `makemigrations --check --dry-run`, 관련 pytest를 실행한다.
- FIELD 교차배정 사용자: 선택 법인 내 배정 프로젝트 허용/다른 법인 또는 미배정 프로젝트 차단을 검사한다.
- HQ/CEO: 아산·미산·그룹 범위에서 목록/지표/최근승인/승인 큐 비교를 검사한다.
- 360px·768px·1440px에서 헤더, 탭, 입력, 표, 버튼의 overflow를 검사한다.
- 실제 승인/반려/정정 동작에 AuditLog가 남는지 검사한다.

### 4. Eval Gate / Promotion Criteria

- 권한 없는 URL 직접 접근은 403 또는 권한 오류로 종료하며 데이터가 노출되지 않는다.
- 법인 범위별 데이터 누출이 0건이다.
- 한글 상태·안내 문구가 일관되고, 지원 화면에서 가로 overflow/잘림이 없다.
- 관련 테스트와 기존 핵심 회귀 테스트가 통과한다.

### 5. Rollback & Operational Audit Checklist

- 변경 파일, 테스트 결과, 화면별 전후 캡처, 발견/조치 목록을 남긴다.
- UI만 되돌릴 수 있도록 업무 로직 변경과 커밋/패치를 분리한다.
- 권한 또는 데이터 범위 이상은 즉시 배포 중지 사유로 처리한다.
