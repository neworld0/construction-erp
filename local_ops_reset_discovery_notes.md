# LOCAL-OPS Reset Discovery Notes

## Database Safety

- Engine: PostgreSQL
- Database: `construction_erp_demo`
- Host: `127.0.0.1`
- Guard result: local/demo conditions passed.

## Project-Scoped Data

The reset script discovered direct Project relationships across projects, labor,
schedule, cost, finance, contracts, closing, inventory, field, reports, risk,
and project assignment models. `SchedulePlan`, labor ledgers, e-card batches,
contracts, cost records, and site warehouses use protective dependencies, so
they are removed in explicit child-first order before `Project`.

## Preserved Data

- Users, groups, permissions, UserProfile, WorkerMaster
- CostItem/CBS and aliases, labor roles, global masters
- AuditLog (its project FK is set to null by Project deletion)
- ClosingPeriod
- Physical media files, unless a separately approved media-deletion run occurs

Generic Evidence and ApprovalRequest records are deleted only for known
project/project-import/project-contract object references. Other generic
references remain preserved.
