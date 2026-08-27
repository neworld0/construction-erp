# LOCAL-OPS-RESET-CEO-RECENT-01 Discovery Notes

- HQ `최근 승인 처리` uses `recent_actions` from `AuditLog` in `apps.core.views.hq_app_view`.
- CEO `최근 승인 완료` uses approved `ApprovalRequest` rows in `apps.ceo.app_views._build_recent_approved_items`.
- `AuditLog` is intentionally preserved by local reset. Project deletion changes its nullable project FK to NULL.
- `ApprovalRequest` has no Project FK. Its target object can be deleted with the project while the approval row remains.
- The local diagnostic found 16 approval-related AuditLog rows with no active project and 10 approved ApprovalRequest rows whose project-scoped targets no longer resolve.
- Both sources are retained as history, but the dashboards now require an existing active project before rendering an operational recent-approval row.
