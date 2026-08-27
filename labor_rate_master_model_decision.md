# Labor Rate Master Decision

Reuse `LaborRateTable`; do not create a second rate model.

HQ owns the existing rate UI at `/app/hq/master/labor/rates/`. FIELD only selects workers, roles, work units, hours, and rate type. On submission, the system resolves the effective project/global rate and stores the resolved unit rate and amount on `TimesheetLine`.

`seed_labor_rates` is an immediate LOCAL-OPS bootstrap path. It creates global DAY rates from 2026-08-01 for the canonical LAB codes and active legacy roles with the same Korean name, so existing WorkerMaster role foreign keys are not rewritten.
