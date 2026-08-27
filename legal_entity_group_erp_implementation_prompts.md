# ASAN Group ERP — 2개 법인 운영 전환 구현 계획 및 5-Layer Delivery Pack

## 목표와 운영 원칙

- 대상 법인: **㈜아산(모회사)**, **㈜미산(종속회사)**
- 아산: 토목·조경 종합건설업 면허 보유
- 미산: 조경 전문건설업 면허 보유
- 화면과 경영관리는 그룹으로 통합하되, 계약·세금·자금·재고·고용·급여·월마감·감사 로그는 반드시 법인별로 분리한다.
- 모든 운영 거래는 하나의 `legal_entity`에 귀속한다. 한 프로젝트가 두 법인에 동시에 귀속될 수 없다.
- 법인 간 자재·인력·장비·관리용역·하도급은 “내부 이관”이 아닌 양 법인에 대칭 기록되는 **법인 간 거래**로 처리한다.
- 기존 데이터는 삭제·재작성하지 않는다. 초기 귀속값 부여, 대사, 승인 및 감사 로그로 전환한다.

## 전체 구현 순서

| 순서 | 구현 묶음 | 선행 조건 | 완료 기준 |
|---|---|---|---|
| 0 | 발견·전환 설계 고정 | 없음 | 영향 데이터, 귀속 규칙, 롤백 계획 승인 |
| 1 | 그룹·법인 마스터 및 법인 권한 | 0 | 법인 전환·접근 차단·감사 로그 작동 |
| 2 | 프로젝트·원가·창고·자재의 법인 분리 | 1 | 법인 간 데이터 누출 없이 현장 운영 가능 |
| 3 | 노무·급여·월마감의 법인 분리 | 1, 2 | 사용자·급여·마감 단위가 법인별로 일치 |
| 4 | 법인 간 거래·정산 | 2, 3 | 양 법인 대칭 전표 및 내부거래 제거 가능 |
| 5 | 그룹 CEO/HQ 경영 통합 및 면허 통제 | 1~4 | 법인/그룹 관점의 KPI·면허 사전 검증 제공 |
| 6 | 기존 데이터 전환·병행운영·승격 | 1~5 | 대사 100%, 복구 가능, 운영 승인 |

---

# 0. 발견·전환 설계 고정

## 1. FAST-CODEX Prompt

```text
# [GROUP-ENTITY-DISCOVERY-01] ASAN·MISAN 법인 분리 전환 발견 및 설계 고정

[ROLE]
You are a senior Django ERP architect, Korean construction ERP domain analyst,
RBAC/AuditLog/Closing auditor, and accounting-data migration engineer.

[MISSION]
Before any model or data mutation, discover the current construction-erp
implementation and produce an approved legal-entity conversion design for:
- ㈜아산: parent / civil and landscape general contractor
- ㈜미산: subsidiary / landscape specialist contractor

[NON-NEGOTIABLE RULES]
- A legal entity is the ownership boundary for contract, sales, purchase, tax,
  bank/cash, inventory ownership, employment, payroll, closing, and audit.
- One project has exactly one contracting legal entity.
- Existing operating data must be preserved; do not delete or silently rewrite it.
- A group management view is not a substitute for each entity’s separate ledger.
- Do not code models, migrations, or seed data in this task.

[DISCOVER]
Inspect actual models, routes, services, templates, tests and current database
records for Project, contract/budget/CBS/WBS, CostActual, warehouse/inventory,
material issue, WorkerMaster, Timesheet, payroll/allocation, office payroll,
billing/revenue, ClosingPeriod, approvals, audit log and user roles.

[DELIVER]
1. Entity-impact inventory with model/table, current owner field, proposed
   legal_entity rule, migration risk, and responsible module.
2. Existing-data attribution matrix: each existing record must be assigned to
   ASAN, MISAN, or NEEDS_REVIEW; no guessed production assignment.
3. Intercompany event catalogue: material sale, equipment rental, staff/admin
   service, subcontract, cash advance/reimbursement, and receivable/payable.
4. Permission matrix for FIELD, entity HQ, group HQ, CEO, and system master.
5. Cutover, parallel-run, reconciliation and rollback design.
6. A minimal implementation sequence aligned with prompts 1–6 below.

[OUTPUT]
Write Korean Markdown under docs/architecture/ and CSV evidence matrices under
docs/architecture/evidence/. Do not expose sensitive IDs, account numbers,
resident numbers or passwords.
```

## 2. Discovery Contract

- Confirm the active database and migration head before inspection.
- Read existing constraints and `on_delete` behaviours before proposing a foreign key.
- List every model that can create financial, payroll, inventory, contractual or closing evidence.
- Separate confirmed facts from assumptions requiring HQ/accounting confirmation.

## 3. Reproduction/Test Harness

- Snapshot row counts by impacted model and project before work.
- Run `manage.py check`, migration-plan inspection, and existing RBAC/closing tests without changes.
- Produce a dry-run attribution report; it must not mutate records.

## 4. Eval Gate / Promotion Criteria

- 100% of in-scope tables and flows are classified.
- No production data assignment is inferred where a contract owner is unknown.
- HQ approves the attribution policy and intercompany event catalogue.

## 5. Rollback & Operational Audit Checklist

- No schema/data changes in this phase; reports are disposable artifacts.
- Keep timestamped row-count snapshots and source revision ID.
- Record the approver of the attribution policy.

---

# 1. 그룹·법인 마스터 및 법인 권한

## 1. FAST-CODEX Prompt

```text
# [GROUP-ENTITY-FOUNDATION-01] Group / Legal Entity Master + Entity-scoped RBAC

[ROLE]
You are a senior Django ERP engineer and RBAC/AuditLog/Closing security auditor.

[MISSION]
Implement the legal-entity foundation for ASAN Group without changing existing
business transaction ownership yet.

[REQUIRED MODEL]
- OrganizationGroup: code, name, active.
- LegalEntity: group FK, code, Korean legal name, registration identifiers
  (masked/encrypted where required), business type, active, accounting currency,
  effective dates.
- LegalEntityLicense: entity FK, license type/name/number (masked if required),
  issuer, valid dates, status, evidence attachment.
- UserLegalEntityMembership: user FK, legal entity FK, access scope
  (FIELD, ENTITY_HQ, GROUP_HQ, CEO_VIEW), active dates.

[SEED]
- ASAN-GROUP / ASAN: ㈜아산, parent, civil + landscape general contractor.
- ASAN-GROUP / MISAN: ㈜미산, subsidiary, landscape specialist contractor.
- Do not invent licence numbers; seed only confirmed licence categories and mark
  unconfirmed fields as requiring HQ registration.

[RBAC]
- Preserve existing Role and ProjectAssignment behaviour.
- Add a mandatory current-entity context for users with more than one entity.
- FIELD can access only assigned projects of the project’s legal entity.
- Entity HQ handles only explicitly granted entities.
- Group HQ and CEO may view both entities; approval authority remains separately
  granted per workflow and must never be inferred from read access.
- Direct URL, API, export and download access must enforce the same entity scope.
- Every context switch, membership change and denied access must be audit logged.

[UI]
- Add a compact legal-entity selector to HQ/CEO global navigation.
- Display the current legal entity on transactional screens.
- Keep current users functional during transition using a temporary, auditable
  default entity policy; do not silently grant cross-entity access.

[MIGRATIONS / TESTS]
- Use reversible Django migrations and data migration only for the two legal
  entity master records and explicitly approved memberships.
- Add model, permission, URL-direct-access and audit-log tests.
```

## 2. Discovery Contract

- Identify the existing custom user model, `UserProfile`, role guards and template base files.
- Confirm whether current accounts represent ASAN only before applying temporary default membership.

## 3. Reproduction/Test Harness

- FIELD user assigned to ASAN cannot open MISAN URL by manual entry.
- Entity HQ can change only their membership’s entity.
- CEO can compare two entities but cannot gain an approval right merely through the selector.
- Existing single-entity user can still open existing screens after migration.

## 4. Eval Gate / Promotion Criteria

- Two legal entities and memberships exist exactly once.
- Direct routes, APIs, CSV/Excel/PDF downloads all reject out-of-entity access.
- `manage.py check`, migrations, and focused RBAC tests pass.

## 5. Rollback & Operational Audit Checklist

- Disable new selector through feature flag if needed; do not delete master records.
- Reverse only schema migration in an isolated restore test; retain audit logs.
- Log every seeded membership and temporary default assignment.

---

# 2. 프로젝트·원가·창고·자재의 법인 분리

## 1. FAST-CODEX Prompt

```text
# [GROUP-ENTITY-OPERATIONS-01] Entity-owned Project, Cost, Warehouse and Inventory

[ROLE]
You are a Django construction ERP engineer, inventory ownership designer,
CBS/WBS auditor and data-migration engineer.

[MISSION]
Make project and operating evidence legally entity-scoped.

[SCOPE]
Project, contract/budget import, CBS/WBS, CostActual, budget exceptions,
Warehouse, StockBalance/StockMovement, InventoryReceipt, Transfer,
MaterialIssue and project material request.

[DESIGN]
- Add non-null `legal_entity` to Project; use the project as the authoritative
  entity source for child records wherever possible. Do not duplicate entity
  fields on children unless cross-project querying/performance requires it.
- Add legal_entity to standalone ownership models: Warehouse, inventory item
  ownership/balance/movement, bank-facing purchase/receipt records and any
  non-project cost evidence.
- Warehouse transfer is allowed only inside the same legal entity.
- A material crossing ASAN ↔ MISAN must be created by the future intercompany
  workflow, never by the existing internal-transfer button.
- CBS/WBS templates may be group-shared, but a project budget and cost actual
  belong only to its project legal entity.
- Preserve VAT input policy and the current closing/adjustment guards.

[DATA CONVERSION]
- Use the approved attribution matrix from discovery.
- Populate only confirmed records automatically; create an HQ review queue for
  `NEEDS_REVIEW` records and prevent their financial posting until resolved.
- Do not change values, dates, approval states or historical snapshots.

[UI / EXPORT]
- Entity selector filters project lists, cost lists, warehouse stock, material
  issues and every export.
- Show entity name on transaction detail, stock reports and cost/export headers.

[TEST]
- Include cross-entity URL/API denial, same-entity transfer success,
  cross-entity transfer rejection, attributed legacy-data regression and closed
  month regression tests.
```

## 2. Discovery Contract

- Enumerate each inventory movement type and determine current ownership source.
- Identify all reports that aggregate costs or stock without a project filter.

## 3. Reproduction/Test Harness

- ASAN project cost cannot select MISAN warehouse/material balance.
- FIELD user sees only the selected entity’s assigned projects and CBS budget.
- Historical ASAN scenario V4/V5 records retain their values and status.

## 4. Eval Gate / Promotion Criteria

- No warehouse/internal transfer crosses an entity boundary.
- Every live project and warehouse has a confirmed or review-queued entity.
- Current cost, inventory and closing tests remain green.

## 5. Rollback & Operational Audit Checklist

- Take transaction counts/value totals by entity before and after migration.
- Keep `NEEDS_REVIEW` transactions outside posting; never force an attribution.
- Feature flag entity filters only after data reconciliation is signed off.

---

# 3. 노무·급여·월마감의 법인 분리

## 1. FAST-CODEX Prompt

```text
# [GROUP-ENTITY-LABPAY-CLOSE-01] Entity-scoped Employment, Payroll and Closing

[ROLE]
You are a LABPAY domain engineer, Korean payroll data steward,
RBAC/Closing/AuditLog auditor and Django migration engineer.

[MISSION]
Implement legal-entity ownership for worker employment, timesheets, labor rate
policy, office payroll, payroll allocation, labor compliance exports and closing.

[RULES]
- WorkerMaster and OfficeEmployeeProfile must carry an employing legal entity.
- One payroll run, payslip, tax/insurance export and wage payment belongs to one
  employing legal entity. Never merge employees’ statutory payroll across entities.
- A worker may be linked to projects of another entity only through an approved
  intercompany service/secondment record; do not pretend the worker is employed
  by both entities.
- Labor rates may be group-template defaults, but effective rates and payroll
  snapshots must resolve under the employer/project legal entity.
- ClosingPeriod must be keyed by legal entity + year + month, with distinct
  approval, correction and audit history.
- Existing CEO/HQ closing control policies remain intact within each entity.

[UI]
- Require legal entity when registering a worker, office employee, payroll run,
  rate policy and closing period.
- Clearly display “고용 법인”, “프로젝트 법인”, and, when applicable,
  “비용 부담 법인”.
- Compliance export filename/header must state the legal entity.

[MIGRATION]
- Use approved attribution data for employees/runs/closing periods.
- A record without a confirmed employer entity remains `NEEDS_REVIEW` and cannot
  produce a statutory export or payment.
- Preserve encrypted personal fields and avoid logging their values.

[TEST]
- Add tests for payroll run uniqueness per entity/month, closed-month isolation,
  employee data access isolation, statutory export entity header, and audited
  approved secondment path.
```

## 2. Discovery Contract

- Confirm all labour/payslip exports and whether their legal employer is currently derivable.
- Identify current uniqueness constraints that must become `(legal_entity, period)` constraints.

## 3. Reproduction/Test Harness

- ASAN and MISAN can each create an August payroll run without conflict.
- Closing ASAN August does not close MISAN August.
- A MISAN HQ cannot download ASAN employee payslips or labour compliance files.

## 4. Eval Gate / Promotion Criteria

- Payroll, labour reports and closing periods are entity-isolated in database and UI.
- Existing approved payroll snapshots remain unchanged after attribution.
- Focused LABPAY, closing, RBAC and export tests pass.

## 5. Rollback & Operational Audit Checklist

- Keep a pre-conversion encrypted-data-safe manifest of employee/run counts.
- Do not reverse or delete statutory export history.
- Audit legal employer corrections and require HQ approval for any re-attribution.

---

# 4. 법인 간 거래·정산

## 1. FAST-CODEX Prompt

```text
# [GROUP-INTERCOMPANY-01] ASAN ↔ MISAN Intercompany Transaction and Settlement

[ROLE]
You are a construction ERP finance architect, intercompany accounting designer,
inventory ownership specialist and Django workflow engineer.

[MISSION]
Create an auditable, approval-controlled legal-entity transaction workflow.

[EVENT TYPES]
- Material sale/purchase
- Equipment rental/service
- Staff or administration service charge
- Subcontract work / progress billing
- Reimbursement or cash advance settlement

[MANDATORY DESIGN]
- Every transaction has supplier entity, customer entity, transaction type,
  contract/reference, taxable amount, VAT amount, posting date, due date,
  approval status, mirrored receivable/payable references and evidence.
- A submitted intercompany transaction must create matching draft records on
  both sides; final posting requires both entity-side approvals or a formally
  approved group-HQ delegated rule.
- For material supply: supplier stock-out + customer stock-in only after approval;
  preserve valuation method and prevent negative stock.
- For subcontract/service: supplier revenue + customer cost; do not alter the
  original external-contract project owner.
- Never use an ordinary warehouse transfer, cost-date correction or manual
  journal to bypass this flow.
- Entity-period closing blocks new postings and routes valid late items through
  correction/adjustment policy.

[GROUP ELIMINATION]
- Build a management-elimination dataset, not a mutation of statutory ledgers.
- Pair the two sides by immutable intercompany transaction number.
- Surface unmatched, amount-mismatched, VAT-mismatched and period-mismatched
  items to HQ reconciliation queue.

[AUDIT / RBAC]
- Restrict each entity’s approver to their own side.
- Audit creation, changes, approval, reversal, cancellation and evidence links.
- Cancellation must create a reversal, never delete an approved posting.

[TEST]
- Full material and service lifecycle; one-side rejection; cross-entity direct
  URL denial; closed-period denial; mismatch reconciliation; cancellation reversal.
```

## 2. Discovery Contract

- Confirm current financial, inventory and approval posting mechanisms before adding an intercompany ledger.
- Agree the first release event types and whether tax invoices are generated in or only referenced by ERP.

## 3. Reproduction/Test Harness

- Create ASAN-to-MISAN material transaction; verify reciprocal drafts, stock and value only post after approval.
- Verify group report eliminates only matched final records.

## 4. Eval Gate / Promotion Criteria

- No approved intercompany transaction lacks a counterpart or immutable link.
- Entity statutory totals remain unchanged by management elimination.
- Reversal leaves original and reversal audit trail intact.

## 5. Rollback & Operational Audit Checklist

- Disable transaction submission feature flag; do not delete paired records.
- Recover using audited reversal workflow only.
- Daily unmatched-pair report is available to group HQ.

---

# 5. 그룹 CEO/HQ 경영 통합 및 면허 통제

## 1. FAST-CODEX Prompt

```text
# [GROUP-MANAGEMENT-01] Group Management Dashboard + Legal Entity License Gate

[ROLE]
You are a CEO dashboard engineer, construction licensing workflow designer,
data visualization specialist and RBAC/AuditLog reviewer.

[MISSION]
Provide lawful entity views and a clearly labelled group management view, then
prevent a project from being registered under an entity without a matching
licence/approval.

[DASHBOARD]
- Add scope switch: 그룹 경영 통합 / ㈜아산 / ㈜미산.
- Entity view: project progress, revenue, cost, labour, payroll, cash, receivable,
  inventory, closing and approval KPIs only for that entity.
- Group management view: entity columns plus total; show external results,
  intercompany gross, elimination adjustment, and management net separately.
- Never label management aggregation as statutory consolidated financial statements.
- All detail-card drilldowns retain selected scope and entity filters.
- CEO has view rights; approval rights remain workflow-specific.

[LICENSE GATE]
- Project registration requires contracting entity and work/license category.
- Match selected category against active LegalEntityLicense validity dates.
- When no valid licence exists, block creation or require a documented exception
  approval before draft registration. Do not invent licence number/evidence.
- Retain licence snapshot on contract/project creation for later audit.

[TEST]
- Multiple project/entity KPI totals and drilldowns.
- Elimination not included twice in group net.
- Expired/missing licence blocks contract project registration.
- Direct URL/API cannot override selected legal entity.
```

## 2. Discovery Contract

- Map every existing CEO/HQ KPI to source models and decide statutory vs management view.
- Confirm licence categories and validity evidence with HQ before enabling the hard block.

## 3. Reproduction/Test Harness

- Create ASAN and MISAN projects; verify entity totals and group total.
- Create matched intercompany service and confirm gross/elimination/net are all traceable.

## 4. Eval Gate / Promotion Criteria

- Every group KPI drills down to entity-owned source records.
- No viewer can see an entity outside their membership except explicitly granted group roles.
- Licence gate has evidence, audit and exception workflow.

## 5. Rollback & Operational Audit Checklist

- Initially run licence gate in warning mode; promote to block only after master validation.
- Keep dashboard scope behind feature flag; retain current single-entity dashboard as fallback.
- Archive KPI reconciliation results for each release.

---

# 6. 기존 데이터 전환·병행 운영·승격

## 1. FAST-CODEX Prompt

```text
# [GROUP-ENTITY-CUTOVER-01] ASAN·MISAN Data Conversion, Parallel Run and Promotion

[ROLE]
You are an ERP cutover lead, construction accounting reconciler,
data-migration engineer and audit/rollback operator.

[MISSION]
Move the existing single-company ERP safely to two legal entities without
deleting historical data or interrupting field operations.

[CUTOVER PLAN]
1. Backup and read-only baseline snapshots.
2. Dry-run legal-entity attribution using approved matrix.
3. HQ review/approval of exceptions.
4. Apply idempotent data migration in a scheduled window.
5. Reconcile entity totals against pre-cutover totals and source documents.
6. Run one monthly close and one intercompany transaction in parallel mode.
7. Promote entity enforcement and group dashboard by feature flag.

[RECONCILIATION]
For each entity and group, compare before/after counts and values for projects,
contracts, CBS budget, cost actuals, stock quantity/value, material issues,
timesheets, labour/payroll, office payroll, receivables, billings, revenue,
cash and closing snapshots.

[OPERATING CONTROLS]
- Freeze high-risk master changes during cutover.
- Provide HQ exception queue, daily reconciliation report and user-facing guide.
- Keep field users entering only their legal entity’s assigned project.
- Rehearse restore in an isolated environment before production promotion.

[DELIVER]
- Executable dry-run and apply scripts, never with hidden destructive commands.
- CSV/Markdown reconciliation pack.
- Release checklist, rollback runbook, role-based SOP and sign-off record.
- Automated regression test suite and post-deployment smoke checks.
```

## 2. Discovery Contract

- Confirm backup/restore owner, maintenance window, current migration head and all external integrations.
- Obtain formal HQ attribution approval before apply mode.

## 3. Reproduction/Test Harness

- Run conversion twice on a copy: second run must be idempotent.
- Restore the copy from backup and verify row/value equality.
- Execute FIELD/HQ/CEO smoke tests for both legal entities and group scope.

## 4. Eval Gate / Promotion Criteria

- Reconciliation exceptions are zero or formally accepted with named owner and due date.
- No cross-entity access or posting bypass is found in automated and manual tests.
- Backup/restore rehearsal and operational sign-off completed.

## 5. Rollback & Operational Audit Checklist

- Roll back only through rehearsed database restore or reversible migration plan.
- Do not delete audit logs, historical payroll exports, invoices or closed-period snapshots.
- Capture exact release version, migration list, operator, start/end time and reconciliation evidence.
```

## 착수 순서 제안

1. Prompt 0을 먼저 실행하여 현재 데이터를 법인별로 귀속할 기준을 확정한다.
2. Prompt 1을 구현·검증하고, 아산/미산 법인 선택 및 권한 경계부터 적용한다.
3. Prompt 2와 3을 순차 적용한다. 재고·원가와 노무·급여·마감은 같은 배포에 섞지 않는다.
4. 실제 법인 간 거래가 발생하기 직전에 Prompt 4를 배포한다.
5. 데이터 대사 기반이 확보된 뒤 Prompt 5의 그룹 대시보드를 공개한다.
6. Prompt 6은 각 단계의 배포 때마다 갱신하며, 최종 전환 전에 반드시 복구 리허설을 한다.
