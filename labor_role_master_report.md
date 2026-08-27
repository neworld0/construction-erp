# LABOR-ROLE-MASTER-01 Report

## Result

PASS. The HQ worker registration form now reads only active `LaborRole` rows and the canonical LOCAL-OPS roles are seeded idempotently.

## Required Roles

| Code | Name | Role group | Dropdown |
|---|---|---|---|
| LAB-GEN | 보통인부 | UNSKILLED | Yes |
| LAB-PAV | 포장공 | SKILLED | Yes |
| LAB-EQP | 장비공 | OPERATOR | Yes |
| LAB-CMP | 다짐공 | SKILLED | Yes |
| LAB-PNT | 도색공 | SKILLED | Yes |

## Operational Notes

- The local database now has eleven active roles: the original six plus the five canonical LOCAL-OPS roles.
- Existing `ORDINARY-WORKER` and `CIVIL-PAVING` records were not recoded, so existing WorkerMaster and ledger references remain stable.
- `LaborRateTable` is a separate master. The new roles have no default rate; rate configuration is a follow-up operational task rather than an implicit payroll-rate change.
- HQ and CEO retain existing worker-master access. FIELD remains blocked by the existing RBAC guard.
- No migration or PII handling change was made.
