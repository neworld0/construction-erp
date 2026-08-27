# 공사일보·월 정산 확장 물리 ERD v1.4

> Django/PostgreSQL 기준의 제안 테이블이다. 실제 구현 시 기존 앱의 모델명·마이그레이션 선행 상태를 다시 확인한다. 표의 `projects_project_work_progress_mapping`, `finance_business_partner`, `finance_subcontract_agreement`는 각각 `ProjectWorkProgressMapping`, `BusinessPartner`, `SubcontractAgreement` 모델을 뜻한다. `field_site_daily_log_correction_request` 제안은 v1.3에서 폐기한다. 금액의 정밀도와 인덱스는 대량 데이터 검증 후 확정한다.

> 정밀 검증 반영: V-01~V-07 전체. 특히 `summary_key` 유니크 제약(V-05), `ClosingPeriod`의 `PROTECT` 관계(V-07), LOCKED의 파생 상태(V-06)는 구현 시 변경하면 안 되는 제약이다.

> **v1.3 데이터 경계:** `field_site_daily_log*` 테이블은 만들지 않는다. 실시간 공사일보는 서비스 조회 결과이며, 정산·마감 근거를 보존할 필요가 있을 때만 최소 스냅샷 테이블을 사용한다. 모든 상세 데이터는 기존 원천 ID로 드릴다운한다.

> **v1.4 보존 정책:** 기존 `reports_fieldreport*` 테이블은 삭제·재분류하지 않는다. 신규 생성 UI와 FIELD 메뉴만 제거하고, 기존 행은 감사·승인 이력 조회를 위해 유지한다.

## v1.3 추가·삭제 물리 설계

| 대상 | 결론 | 핵심 필드/제약 |
|---|---|---|
| `reporting_daily_report_snapshot` | 선택적 신규 | `legal_entity_id`, `scope_type(PROJECT/LEGAL_ENTITY/GROUP)`, `project_id nullable`, `as_of_date`, `source_cutoff_at`, `payload_json`, `payload_hash`, `closing_period_id PROTECT`, `created_by`, `created_at` |
| 스냅샷 식별 | 필수 | `UNIQUE(legal_entity_id, scope_type, project_id, as_of_date, version_no)`; GROUP은 별도 group scope key 사용 |
| `field_site_daily_log*` | 생성 금지 | 별도 초안·제출·승인·물량·장비·정정 테이블을 만들지 않음 |
| 기존 원천 | 변경 최소화 | 진행률·출역·원가·자재투입·재고의 기존 상태/정정/감사 이력을 재사용 |

### 조회 인덱스 기준

- `DailyProgress`, `Timesheet`, `CostActual`, `IssueToWork`, `InventoryLedger`에는 최소한 `project_id + 업무일/발생일 + status` 조회가 가능해야 한다.
- 모든 집계 쿼리는 `legal_entity_id → project_id → as_of_date` 순으로 범위를 고정한다. 그룹합산은 법인별 결과를 먼저 계산한 뒤 합친다.
- 스냅샷에는 원천 행을 복제하지 않고 원천 ID·수량·금액·상태·계산기 버전과 `payload_hash`를 저장한다.

## 부록 A. v1.2 제안 테이블 (v1.3에서 대체됨; 구현 근거로 사용 금지)

| 테이블 | PK | 주요 FK | 주요 컬럼 | 제약/인덱스 |
|---|---|---|---|---|
| `field_site_daily_log` | `id` | `project_id`, `reporter_id`, `approved_by_id`, `rejected_by_id` | `report_date`, `today_work`, `tomorrow_work`, `special_notes`, `status`, 승인/반려 스냅샷 | UQ `(project_id, report_date)`, IDX `(project_id, report_date, status)` |
| `projects_project_work_progress_mapping` | `id` | `project_id`, `wbs_item_id`, `schedule_task_id` | `calculation_mode`, `uom`, `planned_qty`, `is_active` | UQ `(project_id, wbs_item_id, schedule_task_id)`, ScheduleTask별 활성 계산방식 충돌은 서비스 검증 |
| `field_site_daily_log_work_line` | `id` | `site_daily_log_id`, `progress_mapping_id` | `uom`, `planned_qty`, `prior_approved_qty`, `today_qty`, `cumulative_qty`, `memo` | UQ `(site_daily_log_id, progress_mapping_id)`, CHECK 수량 ≥ 0 |
| `field_site_daily_log_equipment_line` | `id` | `site_daily_log_id`, 선택 `cost_actual_id` | `equipment_name`, `spec`, `usage_unit`, `today_usage_qty`, `cumulative_usage_qty`, `ownership_type` | IDX `(site_daily_log_id, equipment_name)` |
| `field_site_daily_log_receipt_ref` | `id` | `site_daily_log_id`, `inventory_ledger_id` | `source_type`, `qty_snapshot`, `unit_cost_snapshot`, `amount_snapshot` | UQ `(site_daily_log_id, inventory_ledger_id)` |
| `field_site_daily_log_evidence` | `id` | `site_daily_log_id`, `evidence_id` | `purpose`, `sort_order` | UQ `(site_daily_log_id, evidence_id)` |
| `field_site_daily_log_correction_request` | `id` | `site_daily_log_id`, `project_id`, `requested_by_id`, 승인자 FK | `original_snapshot`, `proposed_payload`, `reason`, `status`, 영향 스냅샷 | 활성 요청 UQ `(site_daily_log_id)` 조건부, IDX `(project_id, status)` |
| `finance_business_partner` | `id` | 선택 `legal_entity_id` | `code`, `name`, 사업자 식별값, `is_active` | 법인별 코드 UQ, 민감값 별도 보관 |
| `finance_business_partner_payment_account` | `id` | `business_partner_id` | 은행명, 암호화 계좌값, 마스킹값, 예금주, 유효기간 | 활성 기본계좌는 거래처당 하나 |
| `finance_payable_item` | `id` | `legal_entity_id`, `project_id`, `business_partner_id`, 선택 `payment_account_id`, `cost_actual_id`, `expense_execution_id`, `subcontract_certificate_id` | `occurrence_date`, `evidence_date`, `tax_invoice_supply_date`, `due_date`, 공급가/VAT/합계, `vat_status`, `status`, `payment_method` | IDX `(legal_entity_id, project_id, status, due_date)`, 금액 ≥ 0 |
| `finance_payable_payment_allocation` | `id` | `payable_item_id`, `cash_event_id` | `allocated_amount`, `allocated_at` | 회사 CashEvent OUT만 연결, UQ `(payable_item_id, cash_event_id)`, 금액 > 0 |
| `finance_billing_settlement_allocation` | `id` | `progress_billing_id`, 선택 `cash_event_id`, 선택 `payable_item_id` | `settlement_type`, 공급가/VAT/총액, `status`, `owner_payment_reference`, `confirmed_at` | CASH_RECEIPT는 CashEvent 필수, OWNER_DIRECT는 PayableItem·증빙 필수 및 CashEvent NULL |
| `finance_subcontract_agreement` | `id` | `legal_entity_id`, `project_id`, `business_partner_id` | 계약/변경 공급가·VAT·총액, 선급금·기성공제·유보금 조건, 상태 | IDX `(legal_entity_id, project_id, status)` |
| `finance_subcontract_progress_certificate` | `id` | `subcontract_agreement_id`, 선택 `payable_item_id` | `certificate_no`, 검수일, 발생일, 공급가/VAT/총액, 상태 | UQ `(subcontract_agreement_id, certificate_no)` |
| `finance_subcontract_claim` | `id` | `subcontract_agreement_id`, 선택 `certificate_id` | 청구일·증빙일·세금계산서 공급일, 공급가/VAT/총액, 상태 | UQ `(subcontract_agreement_id, claim_no)` |
| `finance_monthly_project_settlement` | `id` | `legal_entity_id`, `project_id`, 선택 `closing_period_id` | `year`, `month`, `status`, 계약/기성/원가/미수 요약값, `generated_at` | UQ `(legal_entity_id, project_id, year, month)`, IDX `(legal_entity_id, year, month, status)` |
| `finance_settlement_cost_summary` | `id` | `settlement_id`, 선택 `cost_item_id` | `summary_key`, `cost_group`, 공급가/VAT/합계, 당월/누계 구분 | UQ `(settlement_id, summary_key)`; NULL을 포함하는 다중열 Unique 사용 금지 |
| `finance_settlement_reconciliation` | `id` | `settlement_id` | `check_code`, `severity`, `expected_value`, `actual_value`, `difference_value`, `status`, `detail` | UQ `(settlement_id, check_code)`, IDX `(settlement_id, severity, status)` |
| `finance_settlement_snapshot` | `id` | `settlement_id`, `created_by_id` | `version`, `snapshot_json`, `output_file`, `file_sha256`, `reason` | UQ `(settlement_id, version)` |
| `finance_account_subject` | `id` | 선택 `legal_entity_id` | `code`, `name`, `account_type`, `is_active` | UQ `(legal_entity_id, code)`, IDX `(name, is_active)` |
| `finance_account_cost_mapping` | `id` | 선택 `legal_entity_id`, `account_subject_id`, `cost_item_id` | 직접/간접, VAT 정책, 유효기간, 기본 증빙정책 | 활성 유효기간 중복 방지, IDX `(legal_entity_id, account_subject_id, effective_from)` |
| `finance_project_cost_allocation_rule` | `id` | `project_id`, `account_cost_mapping_id`, `approved_by_id` | 배부기준·비율·유효기간·상태 | 합계 100%는 서비스 트랜잭션에서 검증 |

## 부록 B. v1.2 외래키 삭제 정책 (v1.3에서 대체됨; SiteDailyLog 관계는 적용 금지)

| 관계 | 삭제 정책 | 이유 |
|---|---|---|
| 프로젝트 → 공사일보/정산/미지급금 | `PROTECT` | 계약·원가·마감 증거 보존 |
| 공사일보 → 물량/장비/참조/증빙행 | `CASCADE` | 초안 삭제 시 종속 행만 제거. 제출 후에는 삭제 금지 |
| WBS/CostActual/InventoryLedger → 공사일보 참조 | `PROTECT` | 승인 근거의 참조 무결성 유지 |
| 법인 → 정산/미지급금/계정과목 | `PROTECT` | 법인 원장·마감 소유 경계 유지 |
| CashEvent → 지급배분 | `PROTECT` | 확정 현금흐름 삭제 방지 |
| ClosingPeriod → 정산서 | `PROTECT` | 마감 확정 정산의 법적·감사 근거를 삭제하지 않음 |

## 부록 C. v1.2 구현 제약 (v1.3에서 대체됨; SiteDailyLog 제약은 적용 금지)

- 공사일보 `status`에는 DRAFT/SUBMITTED/APPROVED/REJECTED만 저장한다. `LOCKED`는 ClosingPeriod에서 계산하는 파생 상태다.
- `PayableItem.occurrence_date`는 검수·사용 확정일이며, `CashEvent.event_date`는 실제 현금일이다. 두 일자를 하나의 열로 통합하지 않는다.
- `vat_status`는 `DEDUCTIBLE_CONFIRMED`, `NONDEDUCTIBLE`, `EXEMPT_OR_NONTAXABLE`, `PENDING_EVIDENCE` 중 하나이며, 공급가/VAT/총액은 모두 보관한다.
- `BillingSettlementAllocation`의 OWNER_DIRECT 행은 회사 현금계좌와 연결할 수 없고, 같은 법인·프로젝트의 ProgressBilling/PayableItem만 연결할 수 있다.
- 기존 `ProgressBilling.cash_event`는 호환용으로 보존하고, 부분수금·직불 처리는 BillingSettlementAllocation으로 단계적 전환한다.
- `DecimalField` 수량은 최소 `max_digits=18, decimal_places=3`을 사용한다.
- 통화는 현재 원화 정수 정책과 맞추어 `BigIntegerField` 또는 고정 소수점을 사용하며, 공급가/VAT/합계를 동시에 저장한다.
- 법인 일치 같은 다중 테이블 검증은 DB `CHECK`만으로 표현하기 어려우므로 `clean()` + 서비스 트랜잭션 + 권한 필터를 함께 적용한다.
- `snapshot_json`은 출력 재현용이며 원천 데이터의 대체물이 아니다. 원천 ID와 집계 규칙 버전을 함께 저장한다.
- 계좌번호는 `PayableItem`에 평문 중복 저장하지 않고 거래처/지급계좌 마스터의 보호된 참조를 사용한다.

## 4. 데이터 이관 원칙

1. 기존 `DailyReport`를 `SiteDailyLog`로 일괄 이관하지 않는다.
2. 기존 `CostActual`, `CashEvent`, `ExpenseExecution`, `ProgressBilling`, `InventoryLedger`는 원천으로 보존한다.
3. 첫 정산서는 과거 원천을 읽어 생성하는 읽기 전용 초안으로 검증하고, 확인 후에만 스냅샷을 확정한다.
4. 제공된 Excel의 외부 통합문서 참조·`#REF!`·수식은 이관 대상이 아니다. 거래행과 증빙 파일만 검증하여 가져온다.


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

## 5. AI Layer 향후 물리 모델 계약(현 버전에서는 마이그레이션 금지)

아래 테이블은 AI Layer 구현 단계의 후보 명세일 뿐, 이번 공사일보·월 정산 선행 구현에
포함되지 않는다. 실제 앱/테이블명, FK, `on_delete`, 암호화 방식, 보존기간은 별도 Discovery에서
현행 스키마와 대조하여 확정한다.

| 후보 테이블 | 필수 열/제약 | 설계 통제 |
|---|---|---|
| `ai_request` | `legal_entity_id NOT NULL`, `scope_kind`, `group_id nullable`, `authorization_snapshot`, `correlation_id`, `idempotency_key UNIQUE` | 법인 범위 선확정·중복 호출 방지 |
| `ai_context_snapshot` | `redacted_context_json`, `encrypted_context_ref`, `context_hash`, `source_as_of_at`, `retention_until` | 최소 공개·재현·보존기간 강제 |
| `ai_evidence` | `claim_id`, `source_locator`, `source_snapshot_json/hash`, `source_captured_at`, `page_or_field_anchor`, `legal_entity_id` | 핵심 Claim의 당시 근거 재현 |
| `ai_response` | `encrypted_raw_response_ref` 또는 `redacted_raw_text`, `structured_json.claims[]`, `response_hash`, `retention_until` | 원문 최소 보관·권한별 열람·파기 |
| `ai_document_draft` | `technical_status`, `applied_to_document_version`, `superseded_by_id`, `content_hash` | 기존 문서 승인 상태와 기술적 초안 상태 분리 |
| `ai_business_event` | UUID event ID, `idempotency_key UNIQUE`, `correlation_id`, `occurred_at`, `recorded_at`, `actor_legal_entity_id`, `payload_hash` | transaction outbox·재시도 중복 방지 |
| `ai_ontology_object_ref/relation` | `source_app/model` 또는 ContentType FK, `legal_entity_id`, `adapter_version`, 관계유형 검증 | Generic FK 약점을 Resolver·서비스 validator로 보완 |

### 현행 선행 구현에 적용할 물리 원칙

- 새 업무 테이블은 법인·프로젝트·원천 문서·기준일을 명확히 FK/인덱스로 보유하고, 법인 범위 없는
  집계·조회 인덱스를 추가하지 않는다.
- 비용·정산·세금 수치에는 VAT 포함/별도·통화·기준일·원천 스냅샷을 명시할 수 있는 데이터 계약을
  먼저 확정한다. 필드가 없는 기존 데이터는 임의 추론해 전환하지 않는다.
- Generic object reference의 존재성·프로젝트·법인·권한 검증은 공통 Resolver/service에서 한다.
  문자열+ID만으로 직접 조회하는 경로를 만들지 않는다.
