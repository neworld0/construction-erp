# WBS Baseline Date Root Cause

WBS Excel parsing already retains `plan_start_date` and `plan_end_date`, but
`hq_project_new` previously saved blank formset values directly to `WBSItem`.
The FIELD schedule bootstrap then copied those blank values to `ScheduleTask`.

The fix resolves missing WBS dates from the project's start and end dates at
baseline creation time. Explicit Excel dates remain authoritative.
