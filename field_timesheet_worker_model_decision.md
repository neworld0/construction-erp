# Model Decision

`TimesheetLine.worker` is the smallest correct addition. It preserves existing aggregate rows through `NULL` worker values while allowing a selected WorkerMaster to become the worker-level FIELD attendance record. The Timesheet header supplies project and work date; the line supplies worker, role, work unit, hours, rate type, and memo.

No WBS/task field exists in the current timesheet model or screen. This patch does not invent a parallel task reference. WBS linkage is a P2 follow-up that should be designed with the existing project baseline contract.

Electronic-card reconciliation and official reporting still use their existing HQ confirmation flow. `get_worker_timesheet_days(project, month)` is explicitly a pre-confirmation operational query.
