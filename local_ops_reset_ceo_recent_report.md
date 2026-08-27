# LOCAL-OPS-RESET-CEO-RECENT-01 Report

## Result

- HQ recent approvals now include only approval AuditLog rows linked to active projects.
- CEO recent approved items now require their target to resolve to an active project, including `PROJECT_BASELINE` approvals.
- No AuditLog or ApprovalRequest row was deleted or updated.
- Local diagnostic reports 16 projectless approval AuditLog rows and 10 orphan project-scoped approved requests; dashboard-visible current approval count is 0.

## Verification

- `python manage.py check`: PASS
- `python manage.py makemigrations --check --dry-run`: PASS
- Focused recent-approval and CEO dashboard regression tests: 12 passed
- Read-only diagnostic and guarded reset dry-run: PASS
