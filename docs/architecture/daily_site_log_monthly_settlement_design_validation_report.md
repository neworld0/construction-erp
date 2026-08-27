# 공사일보·월 정산 확장 설계 정밀 검증 보고서 v1.1

> 검증일: 2026-08-26. 범위는 설계 문서와 현행 Django 모델/서비스의 대조이며, 구현·데이터 변경은 수행하지 않았다.

## 1. 검증 방법

1. 현행 `DailyProgress`, `ScheduleTask`, `WBSItem`, `DailyReport`, `Timesheet`, `IssueToWork`, `InventoryLedger`, `CostActual`, `CashEvent`, `ExpenseExecution`, `BillingReport`, `ProgressBilling`, `ClosingPeriod`, `Adjustment` 모델을 읽었다.
2. `build_project_reconciliation`, 법인/프로젝트 RBAC, 법인별 월마감 서비스를 대조했다.
3. 프로세스맵, 기능정의서, 논리 ERD, 물리 ERD, 전환계획, Delivery Pack의 엔터티·상태·원천·권한·마감 규칙을 교차 확인했다.

## 2. 발견 및 반영 결과

| ID | 발견 사항 | 위험 | 반영 결과 |
|---|---|---|---|
| V-01 | 현행 진행률은 `ScheduleTask`, 공사일보 물량은 WBS 기준으로만 설계돼 있었음 | 물량과 진행률의 잘못된 자동 연결 또는 이중 집계 | `ProjectWorkProgressMapping`과 QUANTITY/MANUAL 계산방식을 모든 설계 문서에 추가 |
| V-02 | 현행 `Adjustment`는 COST/LABOR/INVENTORY만 지원하고 공사일보 세부 정정 대상이 아님 | 마감 후 일지 변경의 감사 공백 | `SiteDailyLogCorrectionRequest`를 추가하고, 재고·원가·현금은 원천 정정으로 분리 |
| V-03 | 현행 `CashAccount`는 회사 소유 계좌이며 거래처 지급계좌 마스터가 없음 | 거래처 계좌를 회사 계좌에 잘못 저장하거나 평문 노출 | `BusinessPartner`, `BusinessPartnerPaymentAccount`를 추가 |
| V-04 | 자재투입은 기존에 CostActual을 생성하므로 원가·자재·출역을 단순 합산하면 중복될 수 있음 | 원가·손익 과대 계상 | 정산 원가의 기준을 CostActual 중심으로 명시하고, 자재·출역은 대사/보조 지표로 변경 |
| V-05 | PostgreSQL 다중열 Unique는 NULL을 여러 건 허용 | 요약행 중복 가능 | `SettlementCostSummary.summary_key` 기반 유니크 제약으로 변경 |
| V-06 | `LOCKED`를 공사일보 저장 상태처럼 표현 | 마감 잠금과 승인 상태 혼동 | ClosingPeriod 기반 파생 잠금으로 정정 |
| V-07 | 정산 확정과 ClosingPeriod 연결의 삭제 정책이 미결 | 마감 증거 삭제 위험 | `PROTECT`로 확정 |

## 3. 문서별 반영 추적

| 검증 항목 | 프로세스맵 | 기능정의서 | 논리 ERD | 물리 ERD | 전환·대사계획 | Delivery Pack |
|---|---|---|---|---|---|---|
| V-01 WBS-일정작업 매핑 | 운영원칙·일일물량 | DSL-02 | Mapping 엔터티 | Mapping 테이블 | 물량 원천/점검 | 비중복 진행률 테스트 |
| V-02 마감 후 일지 정정 | 상태흐름 | DSL-07 | CorrectionRequest | 정정요청 테이블 | 마감후 정정 점검 | 정정 회귀 테스트 |
| V-03 거래처 지급계좌 | 역할/정산흐름 | SET-02/03 | Partner/계좌 엔터티 | Partner/계좌 테이블 | 미지급금 원천 | 보호계좌 테스트 |
| V-04 원가 중복 방지 | 원가 대사 | SET-01 | 원천 경계 | 원천 참조 FK | 원가 대사 | 원가 비중복 게이트 |
| V-05 NULL 유니크 | 해당 없음 | 해당 없음 | 요약 엔터티 | summary_key UQ | 해당 없음 | 중복 행 테스트 |
| V-06 파생 잠금 | 상태흐름 | 공통 마감 | 정산/정정 규칙 | status 제약 | 마감 점검 | 마감 잠금 게이트 |
| V-07 마감 보존 | 월정산 흐름 | SET-06 | 정산 스냅샷 | ClosingPeriod PROTECT | 확정 단계 | 스냅샷 보존 테스트 |

## 4. 승인 정책 반영

2026-08-26 승인된 회계·세무 운영정책을 설계 문서에 반영했다.

| 정책 | 설계 반영 |
|---|---|
| 비용 발생일 | 발생일·증빙일·지급예정일·실제지급일 분리. 원가는 검수·사용 확정일에 인식 |
| VAT 공제 | 공제가능 확정/불공제/면세·비과세/증빙검토중 상태와 원가·신고 기준 분리 |
| 발주처 직불 | `BillingSettlementAllocation(OWNER_DIRECT)`으로 미수금·미지급금을 비현금 상계, CashEvent 생성 금지 |
| 하도급 | 계약·검수기성·청구·지급을 `SubcontractAgreement/Certificate/Claim` 및 Payable로 분리 |

세부 운영 기준은 `daily_site_log_monthly_settlement_accounting_policy.md`를 설계 기준으로 사용한다.

## 5. 검증 결론

- 설계 문서 간 핵심 용어와 흐름은 정합하다.
- 구현 전 HQ 회계 책임자가 확정해야 할 정책은 네 가지다: 비용 발생일, VAT 공제 기준, 발주처 직불 처리, 하도급 기성/지급 인식 기준.
- 위 정책을 확정하기 전에는 데이터 이관·자동 전표·실제 재고 반영을 시작하지 않는다.
- 다음 개발 단계는 Discovery Contract에 따른 현행 데이터 스냅샷과 WBS-일정작업 매핑 화면 설계다.
