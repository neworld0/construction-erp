# OPS-1C KPI Reconciliation and CEO Dashboard Value Validation

## 종합 결론
- OPS-1C 상태: PASS
- CEO dashboard: CEO/HQ 역할 세션에서 경로와 값 확인
- KPI 대사: 모든 필수 항목 허용 오차 내 일치
- OPS-2 진행 가능 여부: YES
- P0: 0
- P1: 최종 회계 매출 정책 확정 필요
- P2: LABPAY-REAL-1 안전 전자카드 파일 검증

## 검증 대상 프로젝트
- Project_Code: OPS1B-RERUN-SAMPLE-001
- Project_Name: 국도 유지보수 파일럿 공사
- Contract_Amount: 571022700.00
- Budget_Total: 571022700
- WBS_Total: 100.00
- Progress: 5.625000% (작업 12.5%가 아닌 가중 프로젝트 진행률)
- Cost: 10000000.00
- Revenue Policy: PROGRESS_BASED_PROVISIONAL

## CEO dashboard 조회 결과
- 기준일: 2026-08-04
- 대시보드 목록은 활성 프로젝트만 포함하며, 가중 진행률을 사용합니다.
- CEO 프로젝트 목록은 프로젝트명을 표시하고, 코드는 별도 데이터 식별자로 확인했습니다.
- 검증 중 KPI 상세 화면의 잘못된 `budgetitem_set` prefetch로 인한 500을 확인했고, 실제 관계명 `budget_items`로 수정한 뒤 HTTP 200을 재확인했습니다.

## 수동 계산식
- 가중 진행률 = 45 x 12.5 / 100 = 5.625000
- 인식 매출 = 571022700.00 x 5.625000 / 100 = 32120026.88
- 예상 이익 = 32120026.88 - 10000000.00 = 22120026.88
- 예상 이익률 = 22120026.88 / 32120026.88 x 100 = 68.86677574287260372305142978

## KPI별 대사 결과
모든 KPI는 `ops1c_ceo_dashboard_value_matrix.csv`에서 원천과 허용오차를 함께 확인할 수 있습니다.

## 차이 발생 항목
차이 목록은 `ops1c_kpi_difference_register.csv`를 참조합니다.
KPI 값 차이는 없으며, 상세 화면 관계명 오류는 `ops1c_data_issue_register.csv`에 P0 해결 이력으로 기록했습니다.

## RBAC 표시/차단 결과
CEO/HQ 접근, FIELD CEO 차단, 익명 로그인 리디렉션을 확인했습니다. 배정 기반 FIELD 진행률 경로는 별도 표에 기록했습니다.

## 한글 UTF-8 / 개인정보 검증
- 원문 주민번호, 전화번호, 계좌번호를 산출물에 기록하지 않았습니다.
- 한국어 프로젝트명과 WBS 명칭은 DB 추출에서 정상 UTF-8로 확인했습니다.

## 남은 HOLD 항목
- 없음. 다만 최종 회계 매출 정책과 LABPAY 실파일 검증은 후속 운영 항목입니다.

## OPS-2 매뉴얼 반영 항목
- CEO KPI는 PROGRESS_BASED_PROVISIONAL 정책임을 명확히 표기합니다.
- 가중 진행률과 단일 작업 진행률을 구분해 설명합니다.

## 최종 판정
- PASS
- Patch needed before OPS-2: NO
- Commit needed: NO unless user asks
