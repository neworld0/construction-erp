# OPS-1B-R2 inactive 프로젝트 정리 및 CEO 대시보드 표시 검증

## 종합 결론

- 상태: PASS
- dry-run: PASS
- apply: PASS, 삭제 0건
- 삭제 대상 프로젝트 수: 0건
- 삭제된 프로젝트 수: 0건
- CEO 대시보드 표시: PASS
- P0/P1/P2: 0 / 1 / 1

inactive 프로젝트는 `Project.is_active=False`로 정의했다. closed 상태이더라도 active인 프로젝트는 삭제하지 않는 정책이다. local demo DB guard를 통과한 뒤 dry-run과 apply를 실행했으며, 현재 비활성 프로젝트는 없어서 어떤 데이터도 삭제되지 않았다.

## inactive 프로젝트 및 삭제 manifest

`ops1b_r2_inactive_project_manifest.csv`에는 헤더만 존재한다. 이는 삭제 대상이 0건이라는 의미다. active 파일럿 `OPS1B-RERUN-SAMPLE-001`은 명시적으로 제외되며 `is_active=True`, `status=active`를 유지한다.

## 종속 데이터 manifest

프로젝트 삭제가 필요한 경우 DailyProgress, ScheduleTask, SchedulePlan, BudgetItem, WBSItem, RevenueRecognition, CostActual, ContractSnapshot, ProjectContract, ProjectAssignment만 project-scoped 후보로 취급한다. AuditLog는 `AUDIT_PRESERVE`로 분류해 삭제하지 않는다. 사용자, 역할, 권한, 글로벌 CostItem/CBS는 대상이 아니다.

## CEO 대시보드 표시 결과

파일럿 프로젝트는 `/app/ceo/`와 `/app/ceo/projects/`에서 모두 HTTP 200을 반환하고, 대시보드와 프로젝트 목록에 표시된다. inclusion 조건은 `Project.is_active=True`이며, 파일럿은 이를 충족한다.

## KPI 대시보드 seed

- 계약금액: 571022700.00원
- 예산합계: 571022700원
- WBS 가중치 합계: 100%
- 작업 진행률: 12.5%
- 대시보드 가중 진행률: 5.625%
- 원가: 10000000.00원
- 인식수익: 32120026.88원
- 이익: 22120026.88원
- dashboard 대사 차이: 0

## 남은 이슈

OPS1BR-001 안전한 비식별 전자카드 파일이 없다. 이 항목은 `LABPAY-REAL-1`로 분리하며, inactive purge 및 CEO KPI 가시성에는 영향을 주지 않는다.

## 한글 UTF-8 및 개인정보

R2 산출물 source scan은 PASS다. 원문 주민등록번호, 전화번호, 계좌번호를 산출물에 기록하지 않았다.

## 최종 판정

PASS. active 파일럿은 보존됐고 CEO 대시보드에서 확인 가능하다. production code 및 migration 변경은 없다. OPS-1C KPI reconciliation을 진행할 수 있다.
