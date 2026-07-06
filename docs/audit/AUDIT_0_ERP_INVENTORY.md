# AUDIT-0 ERP 전체 구조 인벤토리

작성일: 2026-07-06  
범위: `construction-erp` Django codebase 정적 감사  
성격: READ-ONLY 구조 인벤토리. 애플리케이션 동작 변경 없음.

## 1. 관찰된 사실

### 1.1 Repository Topology

| 영역 | 경로 | 관찰 내용 | 위험 메모 |
|---|---|---|---|
| Django entry | `manage.py` | 표준 Django management entry | 낮음 |
| URL root | `config/urls.py` | public, app, api, admin, two_factor 포함 | URL 중복/redirect는 별도 점검 필요 |
| Settings | `config/settings/` | `base.py`, `local.py`, `prod.py` 구조 | `.env*` 파일 존재. 값은 열람하지 않음 |
| Apps | `apps/` | 20개 app 디렉터리 관찰 | 업무 도메인이 넓어 cross-app FK/권한 위험 큼 |
| Templates | `templates/`, 일부 `apps/*/templates/` | HQ/FIELD/CEO/public 템플릿 혼재 | hard-coded path 다수 |
| Data | `data/master/cbs_costitems_v1.csv` | CBS CSV seed/import 데이터 | CSV/DB CBS 정합성 관리 필요 |
| Docs | `docs/` | 기존 운영 문서 일부 존재 | 감사 문서는 `docs/audit/` 추가 |
| Scripts | `scripts/` | 기존 script 디렉터리 존재 | 이번 감사에서 script 추가 없음 |
| Media/evidence | `media/`, `evidence/` | 업로드/증빙 저장 영역 | 민감 파일 포함 가능성. 내용 열람 금지 |

### 1.2 App Inventory

| App | Main responsibility | Has models | Has services | Has views | Has URLs | Has templates | Has tests | Risk note |
|---|---|---:|---:|---:|---:|---:|---:|---|
| `audit` | AuditLog API/admin/logger | Yes | logger module | Yes | Yes | No | Yes | 감사 계약은 있으나 action naming 표준화 필요 |
| `ceo` | CEO dashboard, approval, KPI views | No | KPI in submodule | Yes | Yes | Yes | Yes | CEO/HQ 겸용 URL 일부 존재 |
| `closing` | 월 마감, 프로젝트 마감, 정산 조정 | Yes | Yes | Yes | Yes | Yes | No | 마감 guard 누락 시 P0/P1 위험 |
| `contracts` | ContractChange, snapshot | Yes | Yes | Yes | Yes | Yes | Yes | 계약 snapshot/승인 회전 중요 |
| `core` | 로그인, RBAC, HQ shell, approvals | Yes | approvals submodule | Yes | Yes | Yes | Yes | 허브 URL/권한/상세 화면 집중 |
| `cost` | CBS CostItem, cost actual, revenue | Yes | seed/import commands | Yes | Yes | No | Yes | CBS category와 예산 category 분리 주의 |
| `dashboard` | 빈 app | No | No | No | No | No | No | 정리 후보 |
| `evidence` | Evidence, EvidenceFile, policy | Yes | resolve module | Yes | Yes | Yes | Yes | 파일 접근/다운로드 감사 중요 |
| `field` | FIELD dashboard, progress, cost/report entry | Yes | embedded in views | Yes | Yes | Yes | Yes | web_views가 매우 큼. business logic 집중 |
| `finance` | P/L, revenue, cash | Yes | No | API views | Yes | No | Yes | project access filtering 중요 |
| `inventory` | 창고/품목/출고/재고 | Yes | Yes | Yes | Yes | Yes | No | `_log_action_safe` signature warning 이력 있음 |
| `kpi` | KPI API/service | No | Yes | API views | Yes | No | No | dashboard lineage 검증 필요 |
| `labor` | LABPAY, worker, timesheet, e-card, payroll | Yes | Yes | Yes | Yes | Yes | Yes | 가장 큰 운영 위험 영역. 개인정보 포함 |
| `master` | CBS approval/change request, templates | Yes | command | Yes | Yes | Yes | No | CBS 직접 수정 vs 승인 흐름 혼재 |
| `projects` | project onboarding, import, budget, WBS | Yes | submodules | Yes | Yes | Yes | Yes | `hq_views.py`가 대형 복합 로직 |
| `public_site` | public homepage/contact | Yes | No | Yes | Yes | Yes | Yes | 낮음 |
| `reports` | FieldReport web workflow | Yes | No | Yes | Yes | Yes | No | approval/evidence와 연결 |
| `risk` | risk rules/events/findings | Yes | engine submodule | Yes | Yes | No | Yes | rule 결과와 운영 조치 연결 약함 |
| `schedule` | schedule plan, task, progress | Yes | plan_change submodule | Yes | Yes | Yes | Yes | WBS-derived task 동기화가 중요 |
| `users` | 빈 app | No | No | No | No | No | No | 정리 후보 |

## 2. Management Commands

| 경로 | 목적 | 위험 메모 |
|---|---|---|
| `apps/core/management/commands/seed_initial.py` | 초기 사용자/프로젝트 seed | 기본 비밀번호 env/default 관리 주의 |
| `apps/core/management/commands/seed_demo_flow.py` | demo flow seed | 운영 DB 실행 방지 필요 |
| `apps/core/management/commands/seed_demo_3sites.py` | 3-site demo seed | 운영 DB 실행 방지 필요 |
| `apps/core/management/commands/seed_demo_3sites_e2e.py` | 대형 E2E demo seed | side effect 큼 |
| `apps/cost/management/commands/import_cbs_costitems.py` | CSV CBS 일괄 import | dry-run/update 정책 있음 |
| `apps/cost/management/commands/seed_civil_road_cbs.py` | civil road CBS seed | idempotency 테스트 존재 |
| `apps/cost/management/commands/repair_project_budget_categories.py` | 예산 category repair | 운영 전 dry-run/출력 확인 필요 |
| `apps/cost/management/commands/repair_project_budget_cbs.py` | CBS repair | 데이터 보정 명령 |
| `apps/cost/management/commands/repair_project_owner_supplied_budget.py` | 관급자재 budget 후보 점검 | 보수적 dry-run 정책 필요 |
| `apps/master/management/commands/seed_cbs_costitems.py` | master CBS seed | cost import command와 중복 가능 |
| `apps/master/management/commands/seed_master_templates.py` | master template seed | 템플릿 version 정합성 필요 |

## 3. Test Coverage Snapshot

관찰된 테스트 파일은 `apps/*/tests/` 중심이며, 프로젝트 import/LABPAY/evidence/audit/RBAC 쪽이 상대적으로 강합니다.

| Domain | 대표 테스트 | 메모 |
|---|---|---|
| Project import/budget/WBS | `apps/projects/tests/test_project_import_*.py`, `test_project_new_preview.py` | 최근 회귀 테스트 집중됨 |
| LABPAY/e-card/payroll | `apps/labor/tests/test_e_card_imports.py`, `test_worker_master_model.py` | LABPAY-1~10 흐름 다수 포함 |
| RBAC | `apps/core/rbac/tests/*.py` | assignment regression 존재 |
| AuditLog | `apps/audit/tests/test_audit_logs.py` | sensitive key masking 테스트 존재 |
| Evidence | `apps/evidence/tests/*.py` | secure download/policy gate 테스트 존재 |
| Inventory | 테스트 디렉터리 없음 | P2 보강 후보 |
| Closing | 테스트 디렉터리 없음 | P1 보강 후보 |
| Master/CBS approval | 테스트 디렉터리 없음 | P1/P2 보강 후보 |

## 4. 민감정보 파일/경로 관찰

내용은 열람하지 않았고 경로만 기록합니다.

| 경로 | Risk type |
|---|---|
| `.env`, `.env.local`, `.env.prod`, `.env.demo` | secret/config value 포함 가능 |
| `media/` | 업로드 원본 파일/Excel 포함 가능 |
| `evidence/` | 증빙 파일 포함 가능 |

## 5. 위험 추론

| Priority | 추론 |
|---|---|
| P0/P1 | `labor`, `projects`, `closing`, `master`는 운영/재무/확정 데이터와 직접 연결되므로 service-level guard, transaction, AuditLog 표준화가 중요합니다. |
| P1 | `field.web_views.py`, `projects.hq_views.py`, `labor.services.py`가 큰 파일로 업무 로직을 많이 품고 있어 수정 회귀 위험이 큽니다. |
| P2 | hard-coded URL이 많고 route redirect가 섞여 있어 link integrity 자동 검사가 필요합니다. |
| P3 | 빈 app(`dashboard`, `users`)과 중복 seed/import command는 유지보수 정리 후보입니다. |

