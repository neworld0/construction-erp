# Root Cause

The local project reset correctly preserved audit and approval history. HQ had previously rendered the latest approval-related AuditLog rows without requiring an active project. CEO had previously rendered approved ApprovalRequest rows even when their underlying project-scoped object was gone, using a generic fallback label.

The fix keeps both ledgers unchanged and filters only the dashboard surfaces. Valid approval records tied to active projects remain visible; projectless and unresolved historical records render as an empty recent-approval state.
