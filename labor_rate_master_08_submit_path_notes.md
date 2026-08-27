# FIELD Timesheet Submit Path

- `/app/field/labor/timesheets/<id>/` POST with `action=submit` is handled by `field_timesheet_form`.
- The view calls `upsert_timesheet_lines`, then `submit_timesheet`.
- `submit_timesheet` now resolves every line before opening its write transaction.
- Missing roles block submission while the draft and its zero-rate lines remain available for correction.
- The view now renders `ValidationError.messages`, avoiding Django's list-style string representation.
- Existing submitted-line snapshots are retained in `TimesheetLine.unit_rate` and `TimesheetLine.amount`.
