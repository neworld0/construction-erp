# 공사일보·월 정산 확장 설계 정밀 검증 보고서 v1.5

> **v1.5 검증 결론:** 참고 양식의 단일 현장 일지와 다프로젝트 업무일지에서 공통으로 요구되는 전일·금일·월누계 및 프로젝트별 업무 내역을 파생 보고서로 반영한다. 현재 ERP에 장비·물량 별도 원천은 없으므로 입력되지 않은 정보를 보고서에 추정해 쓰지 않는다.

> 검증일: 2026-08-26. 범위는 설계 문서와 현행 Django 모델/서비스의 대조이며, 구현·데이터 변경은 수행하지 않았다.

> **v1.3 추가 검증:** 사용자는 기존 진행률·출역·원가·자재투입에서 데이터를 입력하고, 공사일보는 프로젝트별 및 전사 취합 보고서로 자동 작성되어야 한다고 확정했다.

> **v1.4 추가 검증:** FIELD 보고서 메뉴를 유지하면 동일 일일 정보를 다시 작성하게 되는지 확인했다. 결론은 신규 FIELD 보고서 메뉴를 제거하고, 기존 FieldReport는 이력·미결 승인 처리로만 보존하는 것이 원천 단일성과 감사 보존을 함께 만족한다는 것이다.

## v1.3 추가 발견·반영

| ID | 발견 사항 | 위험 | v1.3 반영 |
|---|---|---|---|
| V-08 | 별도 공사일보 입력·제출·승인 구조가 기존 FIELD 원천 입력과 중복됨 | 이중 입력, 수량/원가 불일치, 별도 승인 큐 누락 | 공사일보를 파생 읽기 보고서로 전환. 별도 입력·승인 상태 제거 |
| V-09 | 현장별 보고서와 HQ/CEO 취합 보고서의 범위·메뉴가 정의되지 않음 | 현장 담당자와 경영진이 서로 다른 기준의 수치를 확인 | FIELD=배정 프로젝트, HQ=법인 전체 프로젝트, CEO=법인/그룹 취합으로 고정 |
| V-10 | 취합 화면에서 법인별 합산 순서가 없으면 아산/미산 데이터가 혼입될 수 있음 | 법인 경계·경영지표 왜곡 | 법인별 프로젝트 결과를 먼저 산출하고 그룹합산은 그 결과만 합산 |
| V-11 | 공사일보 스냅샷과 원천 상세 연결 기준이 없음 | 마감·기성 근거 재현 불가 | 기준일·원천 컷오프·계산 버전·payload hash 및 원천 ID 드릴다운 계약 추가 |

### v1.3 판정

- `SiteDailyLog` 계열의 모델·입력 UI·별도 승인 UI는 **구현 중단 및 제거 대상**이다. 이미 테스트용으로 생성한 행은 운영 데이터로 승격하지 않고, 배포 전에 기능 플래그를 끈 뒤 안전하게 폐기 여부를 별도 검토한다.
- 공사일보 데이터의 유일한 확정 원천은 기존 진행률·출역·원가·자재투입·재고 원천이다.
- FIELD, HQ, CEO에는 각각 보고서 메뉴가 필수이며, 메뉴가 없거나 타 법인·비배정 프로젝트가 노출되면 배포 불가다.
- 이번 개정은 설계 변경이며, 다음 구현은 v1.3 Delivery Pack의 Discovery Contract를 다시 수행한 후에 시작한다.

## 1. 검증 방법

1. 현행 `DailyProgress`, `ScheduleTask`, `WBSItem`, `DailyReport`, `Timesheet`, `IssueToWork`, `InventoryLedger`, `CostActual`, `CashEvent`, `ExpenseExecution`, `BillingReport`, `ProgressBilling`, `ClosingPeriod`, `Adjustment` 모델을 읽었다.
2. `build_project_reconciliation`, 법인/프로젝트 RBAC, 법인별 월마감 서비스를 대조했다.
3. 프로세스맵, 기능정의서, 논리 ERD, 물리 ERD, 전환계획, Delivery Pack의 엔터티·상태·원천·권한·마감 규칙을 교차 확인했다.

## 2. 발견 및 반영 결과

| ID | 발견 사항 | 위험 | 반영 결과 |
|---|---|---|---|
| V-01 | 현행 진행률은 `ScheduleTask`, 공사일보 물량은 WBS 기준으로만 설계돼 있었음 | 물량과 진행률의 잘못된 자동 연결 또는 이중 집계 | `ProjectWorkProgressMapping`과 QUANTITY/MANUAL 계산방식을 모든 설계 문서에 추가 |
| V-02 | 현행 `Adjustment`는 COST/LABOR/INVENTORY만 지원 | 마감 후 원천 변경의 감사 공백 | 공사일보 정정 객체는 추가하지 않고, 재고·원가·현금·진행률은 각각의 원천 정정 흐름으로 분리 |
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

## 6. v1.2 AI Layer 정합성 검증 결과

| ID | v1.3 AI 설계 계약 | 공사일보·월 정산 v1.2 반영 | 판정 |
|---|---|---|---|
| A-01 | 법인 범위와 권한 스냅샷 | 프로세스·기능·논리/물리 ERD·대사·Delivery Pack에 PROJECT/LEGAL_ENTITY/GROUP 및 RBAC 계약 반영 | PASS |
| A-02 | SoR Adapter와 승인 단일권위 | DailyReport/진행률/기성/세금계산서/승인을 구분하고 AI 초안은 기존 workflow를 대체하지 않음 | PASS |
| A-03 | 금액 의미와 VAT 기준 | amount basis·통화·기준일·계산 서비스·원천 해시 계약 반영 | PASS |
| A-04 | 핵심 Claim Evidence 100% | 재무·계약·세금·승인·마감 Claim의 ID+Evidence 누락 시 BLOCK 규칙 반영 | PASS |
| A-05 | 재현성·보존·Provider 통제 | redacted context, hash, retention, legal hold, provider 승인·fallback을 구현 전 Gate로 반영 | PASS |
| A-06 | 비파괴적 단계 추진 | AI 호출/테이블/마이그레이션/코드 구현을 현 버전 범위에서 명시적으로 제외 | PASS |

### v1.2 결론 및 다음 단계

이번 문서 개정은 설계 정합성 확보 단계로 통과한다. 다음 코드 구현은 AI Foundation이 아니라
v1.1에서 우선순위로 정한 공사일보·월 정산의 기존 ERP 선행 기능과 원천 정합성부터 수행한다.
AI Layer는 다음의 승인 Gate가 모두 충족된 뒤 별도 단계로 시작한다.

1. 법인별 SoR Adapter Matrix 및 필드 소유권·금액 의미 사전 승인
2. Generic Resolver, RBAC, Closing/Adjustment 회귀 검증
3. 핵심 Claim의 Evidence coverage dry-run 100%
4. Provider/보존/암호화/비용/장애 대응 정책 승인
5. AI-off 상태의 기존 업무 회귀 0건
