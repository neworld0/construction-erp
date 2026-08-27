# 공사일보·월 정산 확장 물리 ERD v1.1

> Django/PostgreSQL 기준의 제안 테이블이다. 실제 구현 시 기존 앱의 모델명·마이그레이션 선행 상태를 다시 확인한다. 표의 `projects_project_work_progress_mapping`, `field_site_daily_log_correction_request`, `finance_business_partner`, `finance_subcontract_agreement`는 각각 `ProjectWorkProgressMapping`, `SiteDailyLogCorrectionRequest`, `BusinessPartner`, `SubcontractAgreement` 모델을 뜻한다. 금액의 정밀도와 인덱스는 대량 데이터 검증 후 확정한다.

> 정밀 검증 반영: V-01~V-07 전체. 특히 `summary_key` 유니크 제약(V-05), `ClosingPeriod`의 `PROTECT` 관계(V-07), LOCKED의 파생 상태(V-06)는 구현 시 변경하면 안 되는 제약이다.

## 1. 제안 테이블

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

## 2. 외래키 삭제 정책

| 관계 | 삭제 정책 | 이유 |
|---|---|---|
| 프로젝트 → 공사일보/정산/미지급금 | `PROTECT` | 계약·원가·마감 증거 보존 |
| 공사일보 → 물량/장비/참조/증빙행 | `CASCADE` | 초안 삭제 시 종속 행만 제거. 제출 후에는 삭제 금지 |
| WBS/CostActual/InventoryLedger → 공사일보 참조 | `PROTECT` | 승인 근거의 참조 무결성 유지 |
| 법인 → 정산/미지급금/계정과목 | `PROTECT` | 법인 원장·마감 소유 경계 유지 |
| CashEvent → 지급배분 | `PROTECT` | 확정 현금흐름 삭제 방지 |
| ClosingPeriod → 정산서 | `PROTECT` | 마감 확정 정산의 법적·감사 근거를 삭제하지 않음 |

## 3. 구현 제약

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
