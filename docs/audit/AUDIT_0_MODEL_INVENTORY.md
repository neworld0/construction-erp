# AUDIT-0 Model Inventory

작성일: 2026-07-06  
출처: Django model introspection + 정적 파일 탐색

## 1. Core Project Models

| App | Model | 중요 필드/관계 | 제약/인덱스 | 운영 역할 | Risk |
|---|---|---|---|---|---|
| `projects` | `Project` | `code` unique, `name`, `project_type`, `status`, `contract_amount`, 기간, template FK | `code` unique | 프로젝트 root aggregate | status 전이 guard 중요 |
| `projects` | `ProjectContract` | `project` OneToOne, contract amount/dates/file/status | project unique | 계약 기준 정보 | Project.contract_amount와 중복 정합성 |
| `projects` | `BudgetItem` | `project` CASCADE, `cost_item` PROTECT, `category`, `planned_amount`, `note` | index `(project,cost_item)` | 예산 기준선 | SOURCE_ROW_BUCKET으로 동일 CBS 중복 허용. 중복 기준 문서화 필요 |
| `projects` | `WBSItem` | `project` CASCADE, `parent`, `weight`, dates, `baseline_version`, `is_baseline` | index `(project,sort_order)` | WBS baseline | FIELD progress task source |
| `projects` | `WBSChangeRequest/Line` | project, request status, proposed version, lines | request/order index | WBS 변경 승인 | approve 시 baseline rewrite 영향 |
| `projects` | `ApprovalPackage/Item` | project, item_type/object_id, status | unique `(package,item_type,object_id)` | 묶음 승인 | object reference generic risk |

## 2. Cost/CBS Models

| App | Model | 중요 필드/관계 | 제약/인덱스 | 운영 역할 | Risk |
|---|---|---|---|---|---|
| `cost` | `CostItem` | `code` unique, `category`, `cost_type`, `work_type`, `is_active` | `code` unique | CBS master | CBS category와 budget category 혼동 위험 |
| `cost` | `CostItemAlias` | cost_item CASCADE, alias, is_primary, created_by | unique `(cost_item,alias)`, primary partial unique | Excel auto match alias | alias 품질이 import 정확도 좌우 |
| `cost` | `CostActual/Line` | project PROTECT, source report, status, total/lines | source report OneToOne | field actual cost | approval/closing guard 중요 |
| `cost` | `RevenueRecognition` | project, contract_snapshot, as_of_date, revenue | unique `(project,contract_snapshot,as_of_date)` | 수익 인식 | snapshot lineage 중요 |
| `master` | `CBSChangeRequest` | cost_item SET_NULL, proposed JSON, status | none observed | CBS 변경 승인 | proposed schema 검증 중요 |
| `master` | `MasterTemplate`, `MasterWBSTemplateItem`, `MasterBudgetTemplateItem` | template category/domain/version, WBS/budget items | unique template category/domain/version | 신규 프로젝트 template | inactive template 참조 정책 필요 |

## 3. Schedule/Progress Models

| App | Model | 중요 필드/관계 | 제약/인덱스 | 운영 역할 | Risk |
|---|---|---|---|---|---|
| `schedule` | `SchedulePlan` | project PROTECT, version_no, is_active | unique `(project,version_no)`, active per project | progress plan | WBSItem sync와 active plan 정합성 |
| `schedule` | `ScheduleTask` | plan CASCADE, name, dates, weight | none observed | progress task | WBS baseline에서 생성됨 |
| `schedule` | `DailyProgress` | project/plan/task PROTECT, reporter, date, percent, note TextField | unique `(project,task,report_date,reporter)` | FIELD 진행률 | monotonic/approval/closing guard 중요 |
| `schedule` | `PlanChangeRequest` | project/base_plan/status/proposed_payload | none observed | 공정 변경 승인 | payload schema 위험 |
| `field` | `DailyReport/Line` | project PROTECT, reporter, status, cost lines | none observed | daily report/cost source | evidence/approval linkage |
| `reports` | `FieldReport/File` | project, status, files | none observed | field report | core approval와 병행 |

## 4. Labor/LABPAY Models

| App | Model | 중요 필드/관계 | 제약/인덱스 | 운영 역할 | Risk |
|---|---|---|---|---|---|
| `labor` | `LaborRole` | code unique, default_cbs, active | code/name indexes | 직종 master | CBS default 정합성 |
| `labor` | `LaborRateTable` | labor_role, rate_type, unit_rate, effective dates, scope | compound index | 단가 master | 기간 overlap guard 중요 |
| `labor` | `WorkerMaster` | name, rrn_encrypted, rrn_masked, identity_hash, account encrypted, active | identity/name/active indexes | 근로자 master | 개인정보/해시 일관성 P0 |
| `labor` | `LaborWorkLedger` | worker/project/role PROTECT, work_unit, wage/tax/status | worker/project/status indexes | ERP 노무 원장 | confirmed/export와 source immutability |
| `labor` | `LaborMonthlyPayroll` | worker/project/report_project, totals, masked account | unique `(year_month,worker,project,report_project)` | 월 급여 요약 | 계좌 masking 유지 |
| `labor` | `ElectronicCardImportBatch` | year_month/project/source_file/status/header summary | year_month/project, status indexes | CWMA upload batch | 원본 파일/summary 관리 |
| `labor` | `ElectronicCardWorkRaw` | batch,row_no, rrn encrypted/masked, identity_hash, day_01..31 | unique `(batch,row_no)` | e-card raw row | raw PII 저장. 로그 노출 금지 |
| `labor` | `ElectronicCardWorkDay` | raw/batch/worker/date/card_value | unique `(raw,work_date)` | e-card day row | worker nullable/unmatched 처리 |
| `labor` | `LaborReconciliationResult` | batch, worker, date, ERP/card/final, resolution | batch/month/project indexes | e-card 대사 결과 | resolution 없이 confirm 방지 필요 |
| `labor` | `LaborConfirmedWorkDay` | batch, worker, projects, final_work_unit, source_basis | unique `(reconciliation_result)` | 확정 근로일 | 확정 후 불변성 P0 |
| `labor` | `LaborExcelExportBatch` | source_batch, generated_file, status, counts | status/year/project indexes | CWMA reupload export | original overwrite 방지 중요 |
| `labor` | `Timesheet/TimesheetLine` | project/date/status, labor_role lines | sheet_no unique | FIELD 출역부 | WorkerMaster 직접 FK 없음 |
| `labor` | `PayrollAllocationBatch/Line` | period/status/amount, project/cbs lines | unique period, unique `(batch,project)` | 급여 배부 | period close guard 중요 |

## 5. Audit/Approval/Closing/Evidence Models

| App | Model | 중요 필드/관계 | 제약/인덱스 | 운영 역할 | Risk |
|---|---|---|---|---|---|
| `audit` | `AuditLog` | actor, action, object_type/id, project, before/after/meta JSON | object/project/action indexes | 운영 감사 로그 | action contract 표준화 필요 |
| `core` | `ApprovalRequest` | object_type/id, status, submit/approve/reject fields | object/status indexes | 공통 승인 | generic object integrity |
| `core` | `UserProfile` | user OneToOne, role | user unique | RBAC role | role fallback 정책 확인 필요 |
| `core` | `ProjectAssignment` | user/project/is_active | unique `(user,project)` | FIELD project access | inactive filtering 중요 |
| `closing` | `ClosingPeriod` | year/month/status/closed_by | unique period | 월 마감 | 모든 write path guard 필요 |
| `closing` | `ProjectClose` | project OneToOne, status/effective_date | project unique | 프로젝트 마감 | 확정 데이터 보호 |
| `closing` | `Adjustment` | target type, project/period, status, amount | period/project indexes | 정산 조정 | 승인 전후 변경 제한 |
| `evidence` | `Evidence/EvidenceFile/Policy` | object_type/id, files, sha256 | object index | 증빙/첨부 | object_type generic access |
| `inventory` | Warehouse/Location/Item/Transfer/Issue/Ledger/Stock | 재고 도메인 FK/unique | 다수 unique/index | 창고/출고/재고 | 테스트 부족 |
| `finance` | CashAccount/CashEvent | masked account, project, amount | project/date indexes | 현금 흐름 | FIELD filtering 확인 필요 |

## 6. Cross-App FK Dependency Map

| From | To | Dependency type | Risk |
|---|---|---|---|
| `BudgetItem` | `CostItem` | PROTECT | CBS 삭제 방지, 예산 category 독립성 필요 |
| `WBSItem` | `Project` | CASCADE | 프로젝트 삭제 시 WBS 삭제 |
| `SchedulePlan/DailyProgress` | `Project/WBS-derived ScheduleTask` | PROTECT/CASCADE | WBS 동기화 누락 시 field 진행률 막힘 |
| `LaborWorkLedger` | `WorkerMaster`, `Project`, `LaborRole` | PROTECT | 근로자 삭제 대신 비활성 필요 |
| `ElectronicCardWorkRaw/Day` | `WorkerMaster` | SET_NULL | 미매칭/수동매칭 가능 |
| `LaborConfirmedWorkDay` | `LaborReconciliationResult` | SET_NULL + unique | 확정 trace 보존 |
| `Evidence` | generic `object_type/object_id` | no DB FK | access/lineage 수동 보장 필요 |
| `ApprovalRequest` | generic `object_type/object_id` | no DB FK | invalid object reference 가능 |
| `AuditLog` | generic `object_type/object_id` + Project nullable | no DB FK | action contract 표준화 필요 |

## 7. Potential Data Integrity Risks

| Marker | Observed fact | Risk inference |
|---|---|---|
| P0 | `LaborConfirmedWorkDay`는 확정 근로일이며 export source | 확정 후 재대사/수정 차단 회귀 테스트를 계속 유지해야 함 |
| P0 | `WorkerMaster`와 e-card raw에 encrypted/masked/hash fields 존재 | 로그/snapshot에 raw 주민번호/계좌가 섞이면 중대 개인정보 사고 |
| P1 | `BudgetItem` same project/cost_item 중복 허용 | SOURCE_ROW_BUCKET에는 필요하지만 manual duplicate UX/집계 설명 필요 |
| P1 | generic object refs: `ApprovalRequest`, `Evidence`, `AuditLog` | DB FK가 없어 삭제/이동 후 orphan 가능 |
| P1 | closing guards는 여러 service/view에 분산 | 새 write path가 guard 없이 생길 위험 |
| P2 | `CBSChangeRequest.proposed` JSON | schema drift 시 승인 반영 오류 가능 |
| P2 | `header_check_summary` JSON에 운영 진단 저장 | 민감값 preview 포함 금지 지속 점검 필요 |

