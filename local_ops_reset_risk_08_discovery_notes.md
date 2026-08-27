# LOCAL-OPS-RESET-RISK-01 Discovery Notes

- `RiskFinding.project` is nullable and uses `SET_NULL`; deleting a project can leave its finding without a project FK.
- `RiskFinding` also keeps `object_type` and `object_id`. The remaining local row is `RiskFinding #1`, `open/high`, `object_type=PROJECT`, `object_id=1`, with `project_id=NULL`.
- No current `Project #1` exists, so the row is an `ORPHAN_PROJECT_RISK`, not a global/system risk. The model has no global/system scope field.
- The CEO home view previously counted every OPEN `RiskFinding`, including projectless rows. It now counts only OPEN findings connected to an active project.
- The local reset script previously selected only `RiskFinding.project_id in target_ids`; it now also selects projectless `PROJECT` references to target or missing project IDs.
- `RiskRule` and `AuditLog` remain preserved. Future reset apply records `LOCAL_OPS_RISK_RESET_CLEANUP`.
