# AUDIT-0 Backlog P0-P3

작성일: 2026-07-06

## 1. Prioritized Backlog

| Ticket ID | Title | Priority | Scope | Suggested 5-Layer prompt needed? | Expected files touched | Test target | Rollback note |
|---|---|---|---|---|---|---|---|
| AUDIT-1 | URL/View/Template Link Integrity | P1 | 모든 hard-coded href/action과 resolver 대조, dead link 테스트 | Yes | tests only 우선 | new `apps/core/tests/test_url_integrity.py` | 테스트 제거만으로 rollback |
| AUDIT-2 | RBAC Matrix Enforcement | P1 | CEO/HQ/FIELD URL/API 접근 matrix 자동화 | Yes | tests + small view fixes | `apps/core/rbac/tests/`, app tests | view fix별 revert |
| AUDIT-3 | AuditLog Contract Hardening | P0 | sensitive key masking 확장, action registry, mandatory audit tests | Yes | `apps/audit/services/logger.py`, tests | `apps/audit/tests/`, labor/project tests | masking 추가는 backward safe |
| AUDIT-4 | Closing/Confirmation Guard Audit | P0/P1 | 마감/확정 후 write path 차단 검증 | Yes | tests + minimal guard fixes | closing/labor/field/inventory tests | guard 단위 rollback |
| AUDIT-5 | Excel Import/Export Reliability Audit | P1 | project/e-card/CBS parser fixture suite | Yes | tests + parser fixes | project/labor/cost tests | fixture별 rollback |
| AUDIT-6 | LABPAY 1~10 E2E Operational Harness | P0 | upload-parse-reconcile-resolve-confirm-export end-to-end | Yes | tests primarily | `apps/labor/tests/` split | test-only rollback |
| AUDIT-7 | Project Budget/WBS to FIELD Progress E2E Harness | P1 | project import -> WBS -> ScheduleTask -> progress | Yes | tests + minor sync fixes | project/field/schedule tests | sync fix rollback |
| AUDIT-8 | CEO Dashboard Data Lineage Audit | P2 | KPI/dashboard number source mapping and tests | Yes | docs/tests/services | ceo/kpi tests | report-only rollback |
| INVENTORY-AUDIT-1 | Inventory Workflow Regression Harness | P1 | warehouse/item/transfer/issue/ledger/stock tests | Yes | tests + service fixes | new inventory tests | isolated |
| CBS-POLICY-1 | CBS Direct Edit vs Approval Policy Clarification | P1 | master CBS toggle/name/alias/change request policy | Yes | master views/tests/docs | new master tests | policy branch rollback |
| PRIVACY-1 | WorkerMaster/E-card Snapshot Privacy Sweep | P0 | raw rrn/account log/template exposure scan | Yes | audit/labor tests + masking | audit/labor tests | safe masking rollback |
| CLEANUP-1 | Empty App Review | P3 | `dashboard`, `users` app 정리 여부 결정 | No | docs/settings only if decided | manage.py check | defer if uncertain |

## 2. Recommended Sequence

1. `AUDIT-3 AuditLog Contract Hardening`
2. `AUDIT-4 Closing/Confirmation Guard Audit`
3. `AUDIT-2 RBAC Matrix Enforcement`
4. `AUDIT-1 URL/View/Template Link Integrity`
5. `AUDIT-6 LABPAY 1~10 E2E Operational Harness`
6. `AUDIT-5 Excel Import/Export Reliability Audit`
7. `AUDIT-7 Project Budget/WBS to FIELD Progress E2E Harness`
8. `AUDIT-8 CEO Dashboard Data Lineage Audit`

## 3. Ticket Template

```text
[FAST-CODEX] <TICKET-ID> <Title>

STOP:
- No schema change unless explicitly required
- Keep Korean UTF-8 intact
- Do not expose raw 개인정보
- 1 test run max

Goal:
- <business outcome>

Discovery:
- Inspect <files>

Implementation:
- Minimal targeted patch

Tests:
- <specific pytest target>
```

