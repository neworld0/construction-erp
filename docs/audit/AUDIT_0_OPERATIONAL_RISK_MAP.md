# AUDIT-0 Operational Risk Map

작성일: 2026-07-06  
범위: 구조 감사 기반 위험 지도

## 1. Risk Map

| Risk ID | Severity | Domain | Observed evidence | Why it matters | Suggested next ticket | Patch now? |
|---|---|---|---|---|---|---|
| AUDIT0-P0-001 | P0 | 개인정보/감사 | `AuditLog` logger masks only `password/token/secret`; 노동 도메인에는 `rrn_encrypted`, `account_number_encrypted` 존재 | raw 주민번호/계좌가 snapshot/meta에 들어가면 중대 사고 | AUDIT-3 AuditLog Contract Hardening | Later, high priority |
| AUDIT0-P0-002 | P0 | LABPAY confirmed data | `LaborConfirmedWorkDay`는 확정/export source. 원본 ledger/card는 수정 금지 정책 | confirm 후 재처리/수정 우회 시 신고 데이터 오염 | AUDIT-6 LABPAY E2E Operational Harness | Later |
| AUDIT0-P0-003 | P0 | Closing policy | `assert_month_open`, `is_project_or_month_locked`가 여러 write path에 분산 | 마감 후 원장/재고/진행률 수정은 재무 손상 | AUDIT-4 Closing/Confirmation Guard Audit | Later |
| AUDIT0-P1-001 | P1 | Project import | `apps/projects/hq_views.py`에 Excel parse/match/review/save 로직 집중 | 신규 공사 생성 회귀가 예산/WBS/FIELD 진행률까지 전파 | AUDIT-5 Excel Import/Export Reliability Audit | Later |
| AUDIT0-P1-002 | P1 | Budget data integrity | `BudgetItem` same project/cost_item 중복 허용. SOURCE_ROW_BUCKET 목적상 필요 | 수동 입력/집계 화면에서 중복 의미 혼동 가능 | AUDIT-7 Project Budget/WBS to FIELD E2E Harness | Later |
| AUDIT0-P1-003 | P1 | RBAC/security | URL role checks는 분산. hard-coded routes 많음 | FIELD/HQ/CEO 경계가 흐려지면 데이터 노출/오조작 | AUDIT-2 RBAC Matrix Enforcement | Later |
| AUDIT0-P1-004 | P1 | CBS governance | `CostItem` direct toggle/edit-name/alias + `CBSChangeRequest` 승인 흐름 공존 | 승인 우회/마스터 정합성 약화 가능 | AUDIT-2/AUDIT-3 CBS Policy Audit | Later |
| AUDIT0-P1-005 | P1 | Inventory | inventory models/services 존재, 테스트 디렉터리 없음 | 재고 ledger/stock은 운영 데이터이나 회귀 방어 약함 | INVENTORY-AUDIT-1 Test Harness | Later |
| AUDIT0-P1-006 | P1 | Closing/adjustment | closing app tests 없음 | 월마감/조정 승인 회귀 감지 약함 | AUDIT-4 Closing/Adjustment Regression | Later |
| AUDIT0-P2-001 | P2 | URL integrity | 많은 template hard-coded href/action | route 변경 시 dead link 가능 | AUDIT-1 URL/View/Template Link Integrity | Later |
| AUDIT0-P2-002 | P2 | Auditability | AuditLog 실패를 warning으로 삼키는 경로 다수 | 운영자는 감사 누락을 모를 수 있음 | AUDIT-3 AuditLog Health Surface | Later |
| AUDIT0-P2-003 | P2 | Excel reliability | project/e-card/CBS import 모두 Excel/CSV layout에 의존 | 공단/계약서 양식 변경 시 운영 중단 | AUDIT-5 Excel Import/Export Reliability Audit | Later |
| AUDIT0-P2-004 | P2 | Dashboard lineage | KPI/CEO dashboard가 여러 aggregate를 읽음 | 숫자 출처 불명확 시 신뢰 하락 | AUDIT-8 CEO Dashboard Data Lineage Audit | Later |
| AUDIT0-P2-005 | P2 | Generic object refs | Approval/Evidence/Audit use object_type/object_id | orphan/잘못된 resolver 가능 | AUDIT-3 Generic Object Resolver Contract | Later |
| AUDIT0-P2-006 | P2 | UI/operator usability | 일부 템플릿 mojibake 이력, picker/icon/link 수정 반복 | 운영자 입력 오류/신뢰 하락 | UI-I18N-1 Template UTF-8 Sweep | Later |
| AUDIT0-P3-001 | P3 | Maintainability | 빈 app `dashboard`, `users` | 혼란/검색 노이즈 | CLEANUP-1 Empty App Review | Later |
| AUDIT0-P3-002 | P3 | Maintainability | `apps/master`와 `apps/cost`에 CBS seed/import command 복수 | 운영자가 잘못된 command 실행 가능 | CBS-CMD-1 Seed/Import Command Guide | Later |
| AUDIT0-P3-003 | P3 | Test organization | LABPAY 테스트가 `test_e_card_imports.py`에 다수 집중 | 파일 비대화로 유지보수 난이도 증가 | TEST-ORG-1 Labor Test Split | Later |

## 2. Risk Categories Summary

| Category | Key risks |
|---|---|
| Data integrity | confirmed workday immutability, BudgetItem duplicate semantics, generic refs |
| Financial/accounting accuracy | budget baseline, payroll, allocation, closing |
| Labor/payroll/reporting accuracy | WorkerMaster identity, e-card parse/reconcile/export |
| Auditability | sensitive masking, action registry, audit failure visibility |
| RBAC/security | HQ/FIELD boundary, download/export project scope |
| Personal information/privacy | WorkerMaster/e-card raw 주민번호/계좌 |
| Closing/approval policy bypass | distributed guards |
| Excel import/export reliability | project budget/WBS, e-card, CBS CSV |
| Test coverage | inventory/closing/master gaps |
| UI/operator usability | hard-coded links, Korean label/mojibake issues |
| Maintainability | large service/view files, duplicate commands |

## 3. Observed Fact vs Risk Inference

관찰된 사실:
- 모델/URL/서비스 구조는 Django introspection과 파일 검색으로 확인했습니다.
- 민감 파일 내용은 열람하지 않았습니다.
- 앱 코드 동작은 변경하지 않았습니다.

위험 추론:
- 본 문서의 severity는 코드 구조, 데이터 모델, 최근 작업 이력, 테스트 분포를 기준으로 한 우선순위 초안입니다.
- 각 위험은 별도 티켓에서 재현 테스트와 최소 패치로 검증해야 합니다.

