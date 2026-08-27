# [DAILY-SITE-LOG-MONTHLY-SETTLEMENT-01] 설계·전환 Delivery Pack v1.1

> 정밀 검증 반영: V-01~V-07. 이 Delivery Pack은 검증 보고서에서 확정한 WBS-일정작업 매핑, 원천별 원가 집계, 거래처 지급계좌, 정정, 마감 보존 정책을 구현 게이트로 사용한다.

## 1. FAST-CODEX Prompt

```text
[ROLE]
You are a senior Django construction ERP architect, Korean construction
settlement domain analyst, RBAC/AuditLog/Closing auditor, and data-migration
engineer.

[MISSION]
Implement the approved Site Daily Log and Monthly Project Settlement extension.
Do not replace existing DailyProgress, Timesheet, DailyReport, CostActual,
IssueToWork, InventoryLedger, BillingReport, CashEvent, ExpenseExecution,
ClosingPeriod, or Adjustment flows. Connect and reconcile them.

[NON-NEGOTIABLE]
- Legal entity is the ownership boundary for project, cash, inventory, payable,
  contract, closing, and audit.
- Daily log must not duplicate labor, material issue, or cost creation.
- Quantity progress must use an approved project-level WBS-to-ScheduleTask mapping;
  do not double count manual DailyProgress for a quantity-driven task.
- Cost aggregation must treat approved CostActual as the financial source of truth;
  material issue and timesheet summaries are reconciliation evidence unless separately posted.
- Material receipt and material issue are separate inventory events.
- Closed periods derive a lock from ClosingPeriod and allow SiteDailyLog changes only through
  SiteDailyLogCorrectionRequest plus the applicable source adjustment policy.
- Company CashAccount and business-partner payment account are distinct protected records.
- Cost occurrence date, evidence date, scheduled payment date, and actual cash date are distinct facts.
- VAT is deductible only when confirmed by eligible evidence and business-use review; pending VAT must not be automatically deducted from cost.
- Owner-direct payment is a non-cash BillingSettlementAllocation that offsets a progress-billing receivable and a payable only after owner payment evidence is confirmed.
- Subcontract agreement, certified work, supplier claim, and settlement are separate stateful records.
- Preserve existing operating data. Do not bulk-convert DailyReport records.
- All state transitions and material financial/inventory effects must be audited.

[DELIVER]
Implement in the order: discovery, models/migrations, services, FIELD/HQ UI,
reconciliation, settlement output, security/RBAC, tests, and rollback tooling.
Use the linked process map, functional specification, logical ERD, physical ERD,
and migration/reconciliation plan as the design authority.
```

## 2. Discovery Contract

Before model or data mutation, confirm:

1. Active database, migration head, and deployed code revision.
2. Actual lifecycle and `on_delete` policy of DailyProgress, DailyReport, Timesheet, CostActual, IssueToWork, InventoryLedger, CashEvent, ExpenseExecution, BillingReport, ProgressBilling, ClosingPeriod, Adjustment, Evidence, and vendor/payment-account models.
3. Existing project/legal entity scope filters in all FIELD/HQ/CEO paths.
4. Existing material receipt capability and whether it can safely represent field direct purchase.
5. Approved accounting policy for VAT, owner-direct payment, payable recognition date, and subcontract settlement.

Separate confirmed observations from accounting assumptions. Do not infer supplier bank account data, tax treatment, or historical contract ownership.

## 3. Reproduction/Test Harness

### Fixture scope

- One Asan landscape/civil project with site warehouse, WBS quantities, approved timesheets, central-to-site transfer, material issue, equipment cost, a partial payable, a progress billing, and a closed prior month.
- One Misan project to prove entity isolation.
- One FIELD user assigned cross-entity for operational support but without authority to create financial events for the other entity.

### Required tests

1. FIELD cannot access an unassigned project or another legal entity's daily log by URL/API.
2. One project/date daily log uniqueness and rejected-log rework work correctly.
3. Approved timesheet and material issue appear exactly once in the daily-log summary.
4. Field receipt increases stock; daily log reference alone never changes stock or creates CostActual.
5. Approved material issue creates its existing CostActual once; daily-log approval does not create a duplicate.
6. Payable partial payment and owner-direct payment reconcile to the exact outstanding balance, using a protected business-partner payment account rather than a company CashAccount.
7. Settlement excludes other legal entity records and flags legal entity mismatch.
8. Closed month blocks direct edit; SiteDailyLogCorrectionRequest and the applicable source adjustment produce a new auditable settlement version.
9. Snapshot numbers reconcile to source IDs and output totals.
10. A NULL cost-item summary cannot create duplicate settlement rows because summary_key is unique.
11. A finalized settlement retains its ClosingPeriod through a PROTECT foreign key.
12. Cost is recognized by occurrence date even when actual company payment is in a later month.
13. Pending/non-deductible VAT remains correctly included in management cost and excluded from VAT credit aggregation.
14. Owner-direct payment reduces the linked billing receivable and payable equally, creates no CashEvent, and cannot exceed either balance.
15. Subcontract certification creates a payable once; claim receipt and payment do not create duplicate cost.

## 4. Eval Gate / Promotion Criteria

- No existing source record is silently migrated, deleted, or reclassified.
- All money and stock changing services use transaction boundaries and idempotency checks.
- Daily-log approval produces no duplicate Timesheet, InventoryLedger, IssueToWork, CostActual, CashEvent, or ApprovalRequest.
- Reconciliation has zero blocking errors before a settlement is marked final.
- Legal-entity isolation, project assignment, closing guard, and audit tests all pass.
- Excel/PDF output reconciles exactly to the settlement snapshot and masks protected payment data.
- HQ accounting approves the payable recognition, direct-payment, VAT, and subcontract policies before production promotion.

## 5. Rollback & Operational Audit Checklist

- Take timestamped row counts and database backup before migration.
- Deploy schema first with nullable/disabled new paths; enable UI only after service tests pass.
- Feature-flag FIELD daily log, field receipt, payable, and settlement output separately.
- If a release is rolled back, disable new writes first; retain rows and audit logs; do not reverse posted stock/cash transactions by deletion.
- Correct erroneous financial/inventory effects using compensating transactions and Adjustment records.
- Record deployer, approver, source revision, migration IDs, reconciliation outcome, and output snapshot hash.
