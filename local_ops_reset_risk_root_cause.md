# Root Cause

The local reset removed `Project #1`. `RiskFinding #1` used a nullable `project` FK with `on_delete=SET_NULL`, so its project link became NULL while its generic `PROJECT#1` reference remained. The old CEO dashboard summary queried all OPEN findings and displayed that orphan as one HIGH/OPEN risk.

The dashboard now excludes findings without an active linked project. Future local reset dry-runs identify this record as `ORPHAN_PROJECT_RISK`, and apply mode deletes it with the project-reset risk cleanup phase. No current DB cleanup apply was performed in this task.
