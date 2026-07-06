# AUDIT-0 URL/View/Template Inventory

작성일: 2026-07-06  
출처: Django URL resolver + 정적 템플릿/뷰 탐색

## 1. 관찰된 사실

### 1.1 Root URL Includes

| Prefix | Include/View | 역할 |
|---|---|---|
| `/admin/` | Django admin | 관리자 |
| `/` | `apps.core.urls`, `apps.public_site.urls`, two_factor | 로그인/public/2FA |
| `/app/` | `apps.core.app_urls` | ERP web shell |
| `/api/` | projects/cost/field/finance/schedule/contracts/evidence/risk/ceo/audit/master/inventory/labor | REST/API |
| `/api/closing/` | `apps.closing.urls` | closing API |
| `/api/kpi/` | `apps.kpi.urls` | KPI API |

### 1.2 High-Priority Web URLs

| URL | View | Template | Role observed | Main workflow | Menu/template link | Risk note |
|---|---|---|---|---|---|---|
| `/app/hq/` | `apps.core.views.hq_app_view` | `templates/app/hq_home.html` | HQ/CEO | HQ hub | Yes | hard-coded quick links 다수 |
| `/app/hq/projects/` | `apps.projects.hq_views.hq_project_list` | `templates/app/hq_projects_list.html` | HQ/CEO | 프로젝트 목록 | Yes | 신규 생성 진입점 |
| `/app/hq/projects/new/` | `apps.projects.hq_views.hq_project_new` | `templates/app/hq/project_new.html` | HQ/CEO | 신규 공사/Excel import | Yes | 가장 복잡한 import workflow |
| `/app/hq/projects/<id>/` | `apps.projects.hq_views.hq_project_detail` | `templates/app/hq_project_detail.html` | HQ/CEO | 기준선/WBS/예산/승인 | Yes | multi-action POST |
| `/app/hq/master/cbs/` | `apps.master.web_views.cbs_list_view` | `templates/app/hq/master_cbs_list.html` | HQ/CEO | CBS master | Yes | CEO 경로와 중복 개념 |
| `/app/hq/master/cbs/new/` | `cbs_create` | `master_cbs_form.html` | HQ/CEO | CBS 변경요청 생성 | Yes | 즉시 생성이 아니라 승인 흐름 |
| `/app/hq/labor/workers/` | `hq_worker_master_list` | `labor_worker_list.html` | HQ/CEO | 근로자 master | Yes | 개인정보 포함, delete/deactivate POST |
| `/app/hq/labor/workers/<id>/delete/` | `hq_worker_master_delete` | redirect | HQ/CEO | 삭제/비활성 | Form POST | GET 차단 필요 |
| `/app/hq/labor/work-ledger/` | `hq_labor_work_ledger_list` | `labor_work_ledger_list.html` | HQ/CEO | 노무 원장 | Yes | confirmed/export data와 연결 |
| `/app/hq/labor/reporting-map/` | `hq_labor_reporting_map` | `labor_reporting_map.html` | HQ/CEO | 신고용 현장 매핑 | Yes | 대량 변경 + closing guard 필요 |
| `/app/hq/labor/e-card-imports/` | `hq_e_card_import_batch_list` | `e_card_imports.html` | HQ/CEO | e-card upload/parse/reconcile list | Yes | file upload/action POST |
| `/app/hq/labor/e-card-imports/<batch_id>/` | `hq_e_card_import_batch_detail` | `e_card_import_detail.html` | HQ/CEO | 대사 검토/확정/export 생성 | Yes | confirmed 후 edit 차단 중요 |
| `/app/hq/labor/confirmed-work-days/` | `hq_confirmed_work_day_list` | `e_card_confirmed_work_days.html` | HQ/CEO | 확정 근로내역 조회 | Yes | read-only |
| `/app/hq/labor/excel-exports/<export_id>/download/` | `hq_labor_excel_export_download` | file response | HQ/CEO | CWMA reupload download | Yes | download audit/role check |
| `/app/hq/labor/monthly-payroll/` | `hq_payroll_list` | `payroll_list.html` | HQ/CEO | 월 급여 요약 | Yes | 계좌 masked 표시 |
| `/app/hq/labor/payroll-allocation/` | `hq_payroll_allocation_list` | `payroll_allocation_list.html` | HQ/CEO | 급여 배부 | Yes | old payroll redirect 존재 |
| `/app/field/` | `apps.field.web_views.field_dashboard` | `apps/field/templates/field/dashboard.html` | FIELD/HQ/CEO mixed | field dashboard | Yes | project scoped resolution 중요 |
| `/app/field/labor/timesheets/` | `field_timesheet_list` | `templates/app/field/timesheet_list.html` | FIELD | 출역부 목록 | Yes | closing/approval guard |
| `/app/hq/closing/` | `hq_closing_list` | `closing_list.html` | HQ/CEO | 월/프로젝트 마감 | Yes | CEO action path도 `/app/hq/closing/...`에 존재 |

### 1.3 Redirect/Duplicate Routes

| URL | Target | Observed fact | Risk inference |
|---|---|---|---|
| `/app/hq/labor/payroll/` | `/app/hq/labor/payroll-allocation/` | legacy redirect | 링크 호환성 좋음. 문서화 필요 |
| `/app/hq/labor/payroll/new/` | `/app/hq/labor/payroll-allocation/new/` | legacy redirect | old link 유지 |
| `/app/hq/labor/payroll/<batch_id>/` | `/app/hq/labor/payroll-allocation/<batch_id>/` | legacy redirect | template/action 확인 필요 |
| `/app/ceo/cbs/cbs/` | `/app/ceo/cbs/` | redirect | 중복 route 보정 |
| `/app/hq/master/labor/...` | labor master URLs included twice in resolver output | `apps.core.app_urls` includes `apps.labor.web_urls` under `hq/master/` and web_urls likely includes master labor routes | 중복 include 여부 정밀 점검 후보 |

## 2. Template Link Integrity 관찰

관찰된 사실:
- `templates/app/hq_home.html`는 최근 운영 바로가기 링크가 많이 추가되어 hard-coded path가 증가했습니다.
- `templates/app/hq/labor_reporting_map.html`, `templates/app/hq/labor_work_ledger_list.html`, `templates/app/hq/e_card_imports.html` 등은 직접 URL path를 사용합니다.
- URL name 사용보다 literal path 사용이 많습니다.

위험 추론:
- URL rename/refactor 시 template link regression이 발생하기 쉽습니다.
- `pytest` 수준의 link resolver smoke test가 별도로 필요합니다.

## 3. Required Checks 결과 요약

| Check | 관찰 | Risk |
|---|---|---|
| 각 template link가 실제 URL인지 | 전체 자동검증은 이번 문서 생성에서 미실행. resolver 목록과 주요 link는 육안 대조 | AUDIT-1 필요 |
| old/new payroll route duplicated? | legacy redirect 존재 | 낮음. 단 template에서 old route 지속 사용 여부 확인 필요 |
| HQ links accessible only to HQ/CEO? | 대부분 `require_role([Role.HQ, Role.CEO])` 관찰 | service-level 보강 필요 |
| FIELD routes project-scoped? | `require_project_access`, assignment helper 관찰 | 일부 view별 정밀 matrix 필요 |
| delete/download/action POST-only? | workers delete는 POST 차단 구현 이력. e-card actions form POST | 모든 action URL 자동 테스트 필요 |

## 4. 다음 티켓 후보

| Ticket | 목적 |
|---|---|
| AUDIT-1 URL/View/Template Link Integrity | 모든 hard-coded link를 resolver로 검증 |
| AUDIT-2 RBAC Matrix Enforcement | URL별 CEO/HQ/FIELD 허용 테스트 |
| AUDIT-3 Unsafe Action Method Audit | delete/approve/submit/download POST/GET 정책 표준화 |

