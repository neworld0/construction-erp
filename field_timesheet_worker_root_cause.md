# Root Cause

FIELD timesheets stored only aggregate `TimesheetLine` data: labor role, headcount, hours, rate type, and memo. The line model had no WorkerMaster foreign key, so a row could not identify the individual worker required by LABPAY operations.

`LaborWorkLedger` already has a worker link, but it is an HQ-managed ledger and lacks the FIELD timesheet rate-type contract. Reusing it for FIELD input would weaken the existing responsibility boundary.
