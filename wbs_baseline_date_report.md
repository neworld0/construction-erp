# WBS Baseline Date Report

## Discovery Contract

- `WBSItem.plan_start_date` and `plan_end_date` already exist and are nullable.
- `hq_project_new` creates baseline rows from the WBS formset.
- FIELD creates `ScheduleTask` rows from the WBS baseline on first progress access.

## Change Contract

- Explicit WBS dates are retained.
- A missing start or end date inherits the matching project date.
- A missing project period blocks the project registration before an undated WBS baseline is committed.
- WBS dates outside the project period are rejected.
- FIELD schedule bootstrap uses WBS dates first, then project dates.

## Validation Record

- `python manage.py check`: PASS before the focused regression bundle.
- `python manage.py makemigrations --check --dry-run`: PASS before the focused regression bundle.
- Focused regression bundle exposed a temporary FIELD compatibility regression caused by an initial guard for legacy blank WBS rows. The guard was removed; existing legacy behavior is preserved. Per the requested one-test-run limit, the bundle was not rerun.
- `python -m compileall` after the correction: PASS.
- `git diff --check` after the correction: PASS.

## Rollback

Revert only the WBS date resolver, the FIELD task date fallback, the preview labels, and the focused test file. No database rollback is required because this change includes no migration.
