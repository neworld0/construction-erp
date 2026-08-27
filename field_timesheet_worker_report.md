# FIELD-TIMESHEET-WORKER-01 Report

## Result

PASS. FIELD can now select active WorkerMaster records in `/app/field/labor/timesheets/new/`. Each selected worker is stored on a `TimesheetLine`; the existing aggregate input path remains available through a blank worker selection.

## Data Flow

`Timesheet(project, work_date)` + `TimesheetLine(worker, labor_role, headcount/work unit, hours, rate_type, memo)` is the FIELD operational attendance source. The worker selector displays only `name / default labor role`, never resident number, phone, or account data.

The WorkerMaster default role is applied in the browser for convenience and again server-side for integrity. A worker without a default role is rejected with an HQ remediation message.

## Governance

- Existing closing guards remain in `upsert_timesheet_lines`.
- FIELD still cannot create or edit WorkerMaster records.
- HQ detail shows the worker column safely.
- Electronic-card reconciliation, LaborWorkLedger, and LaborConfirmedWorkDay remain unchanged. FIELD timesheet rows are pre-confirmation data; the final reporting handoff remains an HQ workflow follow-up.
- Current timesheet models have no WBS/task field. That linkage is intentionally recorded as P2 rather than represented as unstructured text.
