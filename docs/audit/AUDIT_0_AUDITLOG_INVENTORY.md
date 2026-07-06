# AUDIT-0 AuditLog Inventory

작성일: 2026-07-06  
출처: `log_action(`, `AuditLog.objects.create`, action constants 정적 검색

## 1. AuditLog Model Contract

| Field | 관찰 |
|---|---|
| `actor` | nullable FK `auth.User` |
| `action` | `CharField(max_length=80)` |
| `object_type`, `object_id` | generic object reference |
| `project` | nullable FK Project |
| `request_id`, `ip`, `user_agent` | request context |
| `before_json`, `after_json`, `meta_json` | JSON snapshots |
| Indexes | object, project, action |

`apps/audit/services/logger.py`에 `SENSITIVE_KEYS = ("password", "token", "secret")` 관찰. 주민번호/계좌번호 계열 key masking은 별도 점검 필요.

## 2. Action Inventory

| Category | Action identifiers observed | Representative files | Snapshot/metadata note | Sensitive risk |
|---|---|---|---|---|
| Approval | `APPROVAL_SUBMIT`, `APPROVAL_APPROVE`, `APPROVAL_REJECT` | `apps/core/services/approvals.py`, `apps/core/serializers.py` | object_type generic | low/medium |
| Project/import | `PROJECT_CREATE`, `PROJECT_IMPORT_PARSE`, `PROJECT_IMPORT_COMMIT`, `PROJECT_BUDGET_IMPORT_COMMIT`, `PROJECT_WBS_IMPORT_COMMIT` | `apps/projects/hq_views.py` | import summary meta | Excel row names only; avoid source PII |
| Project baseline | `PROJECT_BASELINE` object logs, approve/reject actions inferred | `apps/projects/hq_views.py` | before/after project status | medium |
| Budget CBS | `BUDGET_CBS_SELECT`, `BUDGET_CBS_BLOCKED` | `apps/projects/hq_views.py` | CBS mapping metadata | low |
| Contract | contract change submit/approve/reject | `apps/contracts/views.py`, `apps/contracts/services.py` | before/after changes | medium |
| WBS change | approve WBS change | `apps/projects/services/wbs_change_approval.py` | baseline version metadata | medium |
| Approval package | package create/submit/approve/reject | `apps/projects/services/approval_package.py` | generic item list | medium |
| CBS/Master | `MASTER_CBS_*`, alias add/set/delete, update blocked | `apps/master/web_views.py` | proposed JSON | medium |
| Evidence | `EVIDENCE_CREATE`, `EVIDENCE_FILE_ADD`, `EVIDENCE_UPDATE`, `FILE_DOWNLOAD` | `apps/evidence/views.py`, `apps/evidence/web_views.py`, `apps/field/web_views.py` | file metadata | file names may reveal sensitive info |
| Closing | `CLOSING_REQUEST_CREATE/SUBMIT/APPROVE/REJECT`, `PROJECT_CLOSE_*` | `apps/closing/web_views.py`, `apps/closing/services.py` | period/project info | medium |
| Adjustment | adjustment actions | `apps/closing/adjustments.py` | amount/reason | financial |
| Inventory | `INVENTORY_LEDGER_CREATE`, `INVENTORY_LEDGER_BLOCKED_CLOSED`, warehouse/item actions | `apps/inventory/services.py`, `apps/inventory/web_views.py` | stock/amount metadata | medium |
| Labor worker | `LABOR_WORKER_CREATE`, `LABOR_WORKER_UPDATE`, `LABOR_WORKER_DELETE`, `LABOR_WORKER_DEACTIVATE`, `LABOR_WORKER_ALREADY_INACTIVE` | `apps/labor/services.py` | masked snapshots | P0 if raw PII included |
| Labor role/rate | `LABOR_ROLE_*`, `LABOR_RATE_*`, overlap blocked | `apps/labor/services.py` | role/rate fields | low/medium |
| Labor ledger | `LABOR_WORK_LEDGER_CREATE/UPDATE`, `LABOR_REPORTING_PROJECT_UPDATE` | `apps/labor/services.py` | work unit/wage/project | payroll accuracy |
| E-card | `LABOR_ECARD_IMPORT_UPLOAD`, `LABOR_ECARD_IMPORT_PARSE`, `LABOR_ECARD_RECONCILE` | `apps/labor/services.py` | batch summary | must not include raw rrn |
| Reconciliation | `LABOR_RECONCILIATION_RESOLVE`, `LABOR_RECONCILIATION_BULK_RESOLVE`, `LABOR_RECONCILIATION_WORKER_MATCH` | `apps/labor/services.py` | resolution/final amount | high |
| Confirmed work | `LABOR_CONFIRMED_WORKDAY_GENERATE`, `LABOR_ECARD_RECONCILIATION_CONFIRM` | `apps/labor/services.py` | counts/final work units | P0 confirmed data |
| Excel export | `LABOR_EXCEL_EXPORT_GENERATE`, `LABOR_EXCEL_EXPORT_DOWNLOAD` | `apps/labor/services.py` | file names/counts/download actor | file access audit |
| Payroll | `LABOR_MONTHLY_PAYROLL_GENERATE`, `PAYROLL_BATCH_*`, `PAYROLL_LINES_UPDATE` | `apps/labor/services.py` | amounts/periods | financial |
| Risk | risk ack | `apps/risk/views.py` | finding status | low |

## 3. Sensitive-Data Check

관찰된 민감 필드:
- `WorkerMaster.rrn_encrypted`, `rrn_masked`, `identity_hash`
- `WorkerMaster.account_number_encrypted`, `account_number_masked`
- `ElectronicCardWorkRaw.rrn_encrypted`, `rrn_masked`, `identity_hash`
- `.env*`, settings DB password handling

관찰된 보호 장치:
- `WorkerMaster.set_rrn`, `set_account_number`, masking helpers
- e-card parse stores masked/hash and encrypted raw
- worker delete/deactivate audit metadata uses `rrn_masked`
- AuditLog logger masks `password`, `token`, `secret`

위험 추론:
- `log_action` 기본 masking key에 `rrn`, `resident_no`, `account_number`, `rrn_encrypted`, `account_number_encrypted`가 포함되어 있지 않은 것으로 관찰됩니다. 호출부가 조심하고 있지만, future caller가 raw dict를 넘기면 P0 개인정보 로그 위험이 있습니다.

## 4. Missing Audit Candidates

| Candidate | Why |
|---|---|
| URL/action method denial | unsafe GET/action 차단 실패는 운영 감사에 남지 않음 |
| Closing guard blocked writes | 일부 blocked case만 audit. 표준화 필요 |
| Project detail manual budget edits | save/delete/new BudgetItem 변경 전후 AuditLog 여부 정밀 확인 필요 |
| FIELD progress draft/submit/edit | 일부 log 관찰. coverage matrix 필요 |
| Inventory master edits | `_log_action_safe` warning 이력 때문에 signature/coverage 점검 필요 |

## 5. 권고

| Priority | Recommendation |
|---|---|
| P0 | `SENSITIVE_KEYS`에 `rrn`, `resident`, `account`, `identity_hash`, `rrn_encrypted`, `account_number_encrypted` 계열 추가 |
| P1 | Audit action naming registry 문서화 및 테스트 |
| P1 | confirmed/export/payroll/closing actions는 mandatory audit contract test 작성 |
| P2 | AuditLog 실패 warning을 운영 dashboard에 노출하는 health check |

