# Labor Rate Model Discovery

- Existing model: `apps.labor.models.LaborRateTable`
- Fields: `labor_role`, `rate_type`, `unit_rate`, `effective_from`, `effective_to`, `scope_type`, `project`, `is_active`, `note`
- Existing resolution: `apps.labor.services.get_applicable_rate(project, labor_role, date, rate_type=...)`
- Precedence: active project rate first, then active global rate; both honor effective dates.
- Existing HQ UI: `/app/hq/master/labor/rates/`, restricted to HQ/CEO, with list/new/edit/active toggle.
- Existing AuditLog: `create_rate` and `update_rate` already record rate master events.
- Root failure: no applicable `LaborRateTable` row for the TimesheetLine labor role and date.
- No migration is required because the rate master, effective date policy, project override, and unit-rate snapshot fields already exist.
