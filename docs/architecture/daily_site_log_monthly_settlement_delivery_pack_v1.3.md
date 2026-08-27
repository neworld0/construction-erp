# [DAILY-SITE-LOG-MONTHLY-SETTLEMENT-01] 설계·전환 Delivery Pack v1.3

> 정밀 검증 반영: V-01~V-07. 이 Delivery Pack은 검증 보고서에서 확정한 WBS-일정작업 매핑, 원천별 원가 집계, 거래처 지급계좌, 정정, 마감 보존 정책을 구현 게이트로 사용한다.

> **v1.3 구현 지시 우선순위:** 별도 공사일보 입력·제출·승인 모델을 구현하지 않는다. 기존 원천을 자동 취합하는 FIELD 프로젝트 보고서, HQ 법인 취합 보고서, CEO 법인/그룹 취합 보고서와 역할별 메뉴·드릴다운을 먼저 구현한다.

## 1. FAST-CODEX Prompt

```text
[ROLE]
You are a senior Django construction ERP architect, Korean construction
settlement domain analyst, RBAC/AuditLog/Closing auditor, and data-migration
engineer.

[MISSION]
Implement the approved automatic Project Daily Report and Monthly Project Settlement extension.
Do not replace existing DailyProgress, Timesheet, DailyReport, CostActual,
IssueToWork, InventoryLedger, BillingReport, CashEvent, ExpenseExecution,
ClosingPeriod, or Adjustment flows. Connect and reconcile them.

[NON-NEGOTIABLE]
- Legal entity is the ownership boundary for project, cash, inventory, payable,
  contract, closing, and audit.
- Daily report is a computed read model. It must not duplicate progress, labor, material issue, inventory, or cost creation.
- Do not create a `SiteDailyLog` data-entry, submission, approval, work-line, equipment-line, receipt-reference, or correction workflow.
- FIELD sees only project-level reports for assigned projects. HQ sees legal-entity consolidated reports. CEO sees Asan, Misan, or group consolidated reports with legal-entity subtotals.
- Quantity progress must use an approved project-level WBS-to-ScheduleTask mapping;
  do not double count manual DailyProgress for a quantity-driven task.
- Cost aggregation must treat approved CostActual as the financial source of truth;
  material issue and timesheet summaries are reconciliation evidence unless separately posted.
- Material receipt and material issue are separate inventory events.
- Closed periods derive a lock from ClosingPeriod. Corrections are made only through the applicable
  progress, labor, cost, inventory or billing source adjustment policy; the daily report itself is not editable.
- Company CashAccount and business-partner payment account are distinct protected records.
- Cost occurrence date, evidence date, scheduled payment date, and actual cash date are distinct facts.
- VAT is deductible only when confirmed by eligible evidence and business-use review; pending VAT must not be automatically deducted from cost.
- Owner-direct payment is a non-cash BillingSettlementAllocation that offsets a progress-billing receivable and a payable only after owner payment evidence is confirmed.
- Subcontract agreement, certified work, supplier claim, and settlement are separate stateful records.
- Preserve existing operating data. Do not bulk-convert DailyReport records.
- All state transitions and material financial/inventory effects must be audited.

[DELIVER]
Implement in the order: discovery, read-model service, FIELD/HQ/CEO menus and UI,
reconciliation, optional snapshot model, security/RBAC, tests, and rollback tooling.
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

1. FIELD cannot access an unassigned project or another legal entity's project daily report by URL/API.
2. Project daily report includes each eligible progress, timesheet, cost, material issue and inventory event exactly once.
3. HQ legal-entity report total equals its visible project-report totals; it contains no other legal entity data.
4. CEO Asan/Misan filters are distinct and group consolidation equals the sum of both legal-entity results.
5. Report reads and drilldowns never create CostActual, InventoryLedger, Timesheet, DailyProgress, ApprovalRequest, or cash records.
6. Payable partial payment and owner-direct payment reconcile to the exact outstanding balance, using a protected business-partner payment account rather than a company CashAccount.
7. Settlement excludes other legal entity records and flags legal entity mismatch.
8. Closed month blocks direct source edit; an approved applicable source adjustment produces a new auditable settlement/report version.
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
- Daily-report calculation and snapshot creation produce no duplicate Timesheet, InventoryLedger, IssueToWork, CostActual, CashEvent, DailyProgress, or ApprovalRequest.
- Each FIELD/HQ/CEO report screen has a visible menu entry and source-detail drilldown; no direct write form is exposed.
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


## v1.2 개정 범위 — AI Layer 연계 준비(설계 전용)

이 문서의 v1.2 개정은 `Construction_ERP_AI_Layer_Implementation_Design_Pack_v1.3`의
법인 범위, SoR 단일권위, 금액 의미, Evidence·Claim 재현성, 승인·마감 보존 원칙을
공사일보·월 정산 확장 설계에 연결한 것이다. **이번 버전은 AI 호출, AI 테이블,
마이그레이션, 외부 Provider 연결, 기존 업무 화면의 코드 구현을 포함하지 않는다.**

- 기존 ERP 원천 시스템(SoR)이 계약·진행률·원가·재고·노무·기성·승인·마감의 유일한
  확정 권위를 가진다. AI/Ontology는 향후 읽기 전용 Context, Evidence, 설명·검토·초안에만 사용한다.
- 모든 향후 Context는 `legal_entity_id`, 범위(`PROJECT`/`LEGAL_ENTITY`/`GROUP`),
  사용자·역할·법인 멤버십·프로젝트 배정의 권한 스냅샷을 먼저 확정한다. 프로젝트 범위는
  반드시 해당 프로젝트의 계약 법인과 일치하고, GROUP 범위는 명시적 그룹 권한이 있어야 한다.
- 계약·기성·원가·현금·세금 Claim에는 `amount_basis`(VAT 포함/별도/해당없음), 통화,
  기준일, 계산 서비스, 원천 스냅샷 해시를 함께 보존한다. 기준이 없는 핵심 금액 Claim은 생성·적용하지 않는다.
- 재무·계약·세금·승인·마감에 관한 핵심 Claim은 Claim ID와 Evidence link를 반드시 가져야
  하며, Evidence가 하나라도 없으면 향후 AI 결과의 적용·제출은 `BLOCK`한다. 일반 서술문은
  별도 관찰 지표로 관리하며 확정 사실로 승격하지 않는다.
- AI 초안의 기술 상태와 기존 문서의 HQ/CEO 승인·반려·잠금 상태를 분리한다. 승인 단일권위는
  기존 업무 workflow이며, AI/ontology의 장애·비활성화가 기존 업무를 중단시키지 않는다.

## 6. v1.2 AI Layer 준비 추가 계약(현재 구현 대상 제외)

### FAST-CODEX Prompt 보완

향후 AI/ontology 연계를 구현할 때에는 공사일보·월 정산의 원천 테이블을 대체하거나 자동 변경하지
않는다. 실행 순서는 `Authorization → Closing/Policy → SoR Adapter → Evidence/Claim Snapshot →
AI(선택) → Deterministic Validator → 기존 Human Approval → Audit/Event`로 고정한다. AI가 꺼져도
FIELD/HQ/CEO의 기존 입력·정산·마감·정정·출력은 정상 동작해야 한다.

### Discovery Contract 보완

1. Project/ProjectContract/ContractSnapshot, BillingReport/ProgressBilling/OwnerConfirmation/TaxInvoice,
   DailyProgress/ProgressCorrectionRequest/SchedulePlan/Task/DailyReport, CostActual, Timesheet,
   IssueToWork, InventoryLedger, Evidence, ApprovalRequest, ClosingPeriod의 실제 SoR와 필드별 계산
   서비스를 확인한다.
2. `legal_entity_id`, 선택 법인, ProjectAssignment, UserLegalEntityMembership, 그룹 권한 및 Generic
   reference Resolver를 확인한다.
3. 금액의 VAT 기준·통화·기준일·source snapshot, Provider 보관/학습 제외/DPA/region 정책을
   확정하지 못하면 AI 구현·호출을 시작하지 않는다.

### Reproduction/Test Harness 보완

1. 아산·미산·그룹합산 Context에서 타 법인 또는 비할당 프로젝트 객체 노출이 0건인지 확인한다.
2. 핵심 금액·계약·세금·승인·마감 Claim이 Claim ID와 Evidence link를 갖고, 하나라도 없으면
   apply/submit이 BLOCK되는지 확인한다.
3. 동일 권한 스냅샷·원천 스냅샷·Prompt/Adapter 버전으로 lineage를 재구성하고, 금액 basis/as-of가
   없는 Claim이 차단되는지 확인한다.
4. AI/ontology routing 비활성화 후 기존 일지·정산·마감·정정 회귀가 0건인지 확인한다.

### Eval Gate / Promotion Criteria 보완

- 법인/권한 데이터 유출 0건, 핵심 Claim Evidence 100%, 수치 변조·마감 우회·승인 우회 0건.
- Provider, 보존/파기, 암호화, legal hold, 비용 한도, 장애 fallback 정책이 승인될 것.
- 일반 서술 Evidence 비율은 관찰 지표이지 핵심 Claim Gate의 완화 사유가 될 수 없음.

### Rollback & Audit 보완

- AI와 Ontology routing feature flag를 독립적으로 끈다. outbox/event/초안은 파생 데이터로만
  철회하고 SoR·승인·마감·세무 증빙을 역수정하지 않는다.
- 요청/근거/응답은 해시, 보존기한, 파기 Audit event, correlation/idempotency key로 추적한다.
