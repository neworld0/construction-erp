# FIELD 출역부 모바일 UI Discovery

- View: `apps.labor.web_views.field_timesheet_form`
- Template: `templates/app/field/timesheet_form.html`
- Form class: 없음. 뷰가 `lines-<index>-*` POST 값을 직접 구성해 기존 서비스에 전달한다.
- 작업 정보 필드: `project_id`, `work_date`, 출역부 전체 `note`
- 출역 행 필드: `worker_id`, `labor_role_id`, `headcount`, `hours`, `rate_type`, `memo`
- 근로자 선택: `WorkerMaster` 기반이며 `/app/field/labor/workers/search/` AJAX 검색이 이미 있다.
- 기존 레이아웃: 8개 행을 하나의 테이블에 렌더링하여 모바일 가로 넘침 위험이 있었다.
- 변경 레이아웃: 각 출역 행을 카드로 분리하고 모바일에서 한 열로 렌더링한다.
- WBS: 현재 Timesheet 모델과 이 입력 화면에는 WBS 선택 필드가 없다. 존재하지 않는 값을 UI에 추가하지 않았다.
- CSS: 이 템플릿의 scoped style block에만 반응형 규칙을 추가했다.
