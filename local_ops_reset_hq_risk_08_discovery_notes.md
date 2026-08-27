# LOCAL-OPS-RESET-HQ-RISK-01 Discovery Notes

- HQ operating-hub risk count came from `apps.core.todo.get_risk_counts`, which previously counted every OPEN RiskFinding.
- HQ risk cards came from a separate unfiltered OPEN RiskFinding queryset in `apps.core.views.hq_app_view`.
- CEO main summary had an active-project filter, but HQ did not use that policy and CEO project rollups could still count demo findings.
- The remaining row is `RiskFinding #1`: `Demo risk finding`, `open/high`, `project_id=NULL`, `object_type=PROJECT`, `object_id=1`, rule key `DEMO_RISK`.
- Project deletion set the nullable FK to NULL. The generic reference remained. The original reset cleanup did not classify all demo rows explicitly.
- Shared dashboard visibility now requires an OPEN risk linked to an active project and excludes demo/seed signals from rule key, title, and details.
