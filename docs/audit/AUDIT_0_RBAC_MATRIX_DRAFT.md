# AUDIT-0 RBAC Matrix Draft

작성일: 2026-07-06  
출처: `require_role`, `require_project_access`, URL/view 정적 탐색

## 1. RBAC Building Blocks

| Identifier | Path | Observed behavior |
|---|---|---|
| `Role.CEO/HQ/FIELD` | `apps/core/rbac/models.py` | 세 가지 주요 role |
| `get_user_role` | `apps/core/rbac/permissions.py` | profile/group/superuser fallback |
| `require_role` | `apps/core/rbac/permissions.py` | role allowlist enforcement |
| `require_project_access` | `apps/core/rbac/permissions.py` | CEO/HQ allow, FIELD requires active `ProjectAssignment` |
| `ProjectAssignment` | `apps/core/models.py` | user/project unique, `is_active` |
| 2FA middleware | `apps/core/middleware/two_factor_enforce.py` | role별 2FA 정책 |

## 2. Draft Matrix

| URL/workflow | CEO | HQ | FIELD | Project-scoped | Service-level permission | View-level permission | Risk note |
|---|---:|---:|---:|---:|---:|---:|---|
| `/app/hq/` HQ home | Yes | Yes | No | No | N/A | Yes | CEO가 HQ path 접근 시 redirect logic 존재 |
| `/app/hq/projects/` | Yes | Yes | No | No | N/A | Yes | OK |
| `/app/hq/projects/new/` | Yes | Yes | No | No | partial | Yes | project import service embedded |
| `/app/hq/projects/<id>/` | Yes | Yes | No | project id | partial | Yes | multi-action POST |
| `/app/hq/master/cbs/` | Yes | Yes | No | No | partial | Yes | CBS approval vs direct toggle 정책 주의 |
| `/app/ceo/cbs/` | Yes | HQ may access 일부 | No | No | partial | Yes | CEO/HQ 겸용 view 일부 |
| `/app/hq/labor/workers/` | Yes | Yes | No | No | Yes for write services | Yes | 개인정보 |
| `/app/hq/labor/workers/<id>/delete/` | Yes | Yes | No | No | Yes | Yes + POST | deletion/deactivation safe path |
| `/app/hq/labor/work-ledger/` | Yes | Yes | No | No | Yes in services | Yes | payroll source |
| `/app/hq/labor/reporting-map/` | Yes | Yes | No | No | Yes | Yes | bulk update |
| `/app/hq/labor/e-card-imports/` | Yes | Yes | No | project optional | Yes | Yes | upload/parse/reconcile actions |
| `/app/hq/labor/e-card-imports/<batch_id>/` | Yes | Yes | No | via batch project | Yes | Yes | confirm/export critical |
| `/app/hq/labor/excel-exports/<id>/download/` | Yes | Yes | No | via export project | Yes | Yes | file download audit |
| `/app/hq/labor/monthly-payroll/` | Yes | Yes | No | No | Yes | Yes | payroll |
| `/app/hq/labor/payroll-allocation/` | Yes | Yes | No | No | Yes | Yes | payment allocation |
| `/app/field/` | Maybe read for HQ/CEO | Maybe read for HQ/CEO | Yes | FIELD assigned project | view helpers | Yes | mixed role dashboard |
| `/app/field/progress/*` | No? | HQ/CEO may read/edit? | Yes | Yes | view | Yes | scope tests exist |
| `/app/field/labor/timesheets/` | No | No | Yes | Yes | Yes | Yes | FIELD own/project scoped |
| `/app/reports/` | Yes | Yes | Yes | FIELD scoped | partial | Yes | FIELD created_by restrictions |
| `/app/evidence-files/<id>/open/` | Yes | Yes | Yes if project access | Yes | resolver | Yes | file access critical |
| API `/api/labor/*` | Yes | Yes | mixed | Some | service/view | API | granular tests needed |
| API `/api/inventory/*` | Yes | Yes | mixed | Some | service/view | API | inventory tests absent |

## 3. High-Risk RBAC Cases

| Case | Observed fact | Risk inference |
|---|---|---|
| FIELD accessing HQ URLs | HQ views mostly call `require_role([Role.HQ, Role.CEO])` | Need automated URL-level test for every `/app/hq/` route |
| FIELD unassigned project | `require_project_access` uses `ProjectAssignment.is_active` | Need tests for all FIELD detail/edit/download routes |
| Service callable without role | Some services assume caller enforced role | Future view/API could bypass |
| Download/export URLs | e-card export/evidence file download have explicit view/service checks observed | Must keep mandatory tests |
| CEO modifying source data | CEO allowed in some HQ operational screens | Need policy decision: CEO approve-only vs edit-capable |
| Generic object refs | Approval/Evidence/Audit object_type/id are not DB FK | project access resolver must be exhaustive |

## 4. 권고 Matrix Tests

| Test suite | Scope |
|---|---|
| `AUDIT-2-HQ-URL-RBAC` | every `/app/hq/` URL: FIELD 403/PermissionDenied |
| `AUDIT-2-FIELD-PROJECT-SCOPE` | FIELD cannot access unassigned project resources |
| `AUDIT-2-DOWNLOAD-RBAC` | evidence/export downloads role + project scoped |
| `AUDIT-2-SERVICE-RBAC` | critical service functions reject FIELD where HQ-only |

