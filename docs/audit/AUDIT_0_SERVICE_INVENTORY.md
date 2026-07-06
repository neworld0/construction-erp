# AUDIT-0 Service Inventory

작성일: 2026-07-06  
출처: `apps/*/services.py`, service submodules, 주요 embedded business logic 정적 탐색

## 1. High-Level Service Map

| Domain | File path | 대표 함수/식별자 | Writes DB? | transaction.atomic? | RBAC? | Closing guard? | AuditLog? | Idempotent? | Risk note |
|---|---|---|---:|---:|---:|---:|---:|---:|---|
| Audit logging | `apps/audit/services/logger.py` | `log_action` | Yes | No | Caller | N/A | N/A | append-only | sensitive key masking 제한적 |
| Approval | `apps/core/services/approvals.py` | approve/reject helpers | Yes | 일부 | Caller | object-specific | Yes | No | generic object resolver risk |
| Closing | `apps/closing/services.py` | `close_month`, `assert_month_open`, `submit_project_close`, `approve_project_close` | Yes | Yes | Caller | Core guard | Yes | No | project close validation 핵심 |
| Adjustment | `apps/closing/adjustments.py` | adjustment create/submit/approve/reject | Yes | 일부 | Caller | month/project policy | Yes | No | financial correction |
| Contracts | `apps/contracts/services.py` | snapshot rotation | Yes | Yes | Caller | Not obvious | Yes | No | contract snapshot lineage |
| Project onboarding/import | `apps/projects/hq_views.py` | `hq_project_new`, `_build_project_import_context`, `_build_budget_review_rows...` | Yes | Yes in save path | View | 일부 | Yes | partial | 대형 embedded logic |
| Excel parser | `apps/projects/excel_import.py` | contract budget/WBS/summary parsers | No | N/A | N/A | N/A | No | Yes | Excel layout drift |
| WBS approval | `apps/projects/services/wbs_change_approval.py` | `approve_wbs_change_request` | Yes | Yes | Caller | Not obvious | Yes | No | baseline rewrite |
| Approval package | `apps/projects/services/approval_package.py` | package submit/approve/reject | Yes | Yes | Caller | Not obvious | Yes | No | object refs generic |
| CBS import | `apps/cost/management/commands/import_cbs_costitems.py` | import command | Yes | Yes | CLI | N/A | warning only | Yes by code | production run control |
| FIELD progress | `apps/field/web_views.py` | `_handle_progress_submit`, `_ensure_progress_tasks_for_project` | Yes | Yes in sync | View/project | `is_project_or_month_locked` | Yes | mixed | large view-embedded logic |
| Evidence | `apps/evidence/services/resolve.py`, `web_views.py` | object resolver, file handling | Yes | mixed | View/project | Yes | Yes | No | generic object access |
| Inventory | `apps/inventory/services.py` | ledger, issue/transfer helpers | Yes | Yes | Caller | `is_month_closed` observed | Yes | mixed | inventory tests absent |
| Labor worker | `apps/labor/services.py` | `create_worker_master`, `update_worker_master`, `delete_or_deactivate_worker_master` | Yes | Yes for delete/deactivate | Yes | N/A | Yes | No | PII handling |
| Labor ledger | `apps/labor/services.py` | `create_labor_work_ledger`, update/reporting map | Yes | Yes | Yes | Yes | Yes | mixed | payroll source |
| E-card upload/parse | `apps/labor/services.py` | `create_electronic_card_import_batch`, `parse_electronic_card_import_batch` | Yes | Yes | Yes | N/A | Yes | reparse clears/rebuilds | raw PII + Excel |
| Reconcile/resolve | `apps/labor/services.py` | `reconcile_electronic_card_batch`, `resolve_labor_reconciliation_result`, bulk/match | Yes | Yes | Yes | N/A | Yes | rerun rebuilds | confirmed 상태 guard |
| Confirmed workday | `apps/labor/services.py` | `generate_labor_confirmed_work_days`, `confirm_electronic_card_reconciliation_batch` | Yes | Yes | Yes | N/A | Yes | duplicate prevented | P0 confirmed data |
| CWMA export | `apps/labor/services.py` | `generate_cwma_card_reupload_excel`, `register_labor_excel_export_download` | Yes + file | Yes | Yes | N/A | Yes | history rows | original workbook preservation |
| Monthly payroll | `apps/labor/services.py` | `generate_labor_monthly_payroll` | Yes | Yes | Yes | Yes | Yes | regenerate | payroll accuracy |
| Payroll allocation | `apps/labor/services.py` | create/update/submit allocation batch | Yes | Yes | Yes | Yes | Yes | No | payment allocation |
| KPI | `apps/kpi/services.py`, `apps/ceo/services/kpi_engine.py` | KPI aggregation | Read mostly | N/A | Caller | N/A | No | Yes | dashboard lineage |
| Risk | `apps/risk/services/engine.py` | `emit_event`, `evaluate_event` | Yes | Yes | Caller | N/A | No | event-based | duplicate finding policy |

## 2. Embedded Business Logic Hotspots

| File | Observed fact | Risk inference |
|---|---|---|
| `apps/projects/hq_views.py` | Project new/detail, Excel import matching, budget review, save, repair helpers in one large file | P1 regression risk; service extraction later |
| `apps/field/web_views.py` | FIELD dashboard/progress/cost/report/evidence logic concentrated | P1 regression risk; project access/closing guard audit needed |
| `apps/labor/services.py` | Worker, ledger, e-card, reconciliation, confirmed, export, payroll in one large service | P0/P1 critical path; contract tests essential |
| `apps/master/web_views.py` | CBS form/change request/approval/alias logic in view | P1 CBS policy bypass risk |

## 3. Transaction/Audit Observations

| Observed fact | Risk inference |
|---|---|
| LABPAY critical functions use `transaction.atomic()` in create/parse/reconcile/confirm/export paths | Good. Continue requiring transaction for confirmed/export writes |
| Multiple services catch AuditLog failure as warning | Good for availability, but audit loss may go unnoticed |
| Some API/view flows rely on caller to enforce RBAC | Service direct use in future can bypass role checks |
| Closing guard appears in labor/inventory/field paths, but not centrally enforced by model | New write paths can bypass close unless audited |

## 4. Idempotency Notes

| Flow | Current behavior observed | Risk |
|---|---|---|
| E-card parse | reparse deletes/rebuilds raw/day for batch | acceptable before confirm; confirmed guard required |
| E-card reconcile | rerun rebuilds reconciliation before confirm | acceptable; confirmed guard required |
| Confirmed workday | unique reconciliation_result prevents duplicate rows | good |
| CWMA export | repeated generation creates history rows | good |
| CBS CSV import | code-based upsert, skip by default | good |
| Project import | one-time project creation; preview session files | temp file cleanup and unmatched confirmation risk |

