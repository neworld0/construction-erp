# LABOR-ROLE-MASTER-01 Discovery Notes

- Canonical master model: `apps.labor.models.LaborRole`.
- `WorkerMaster.default_labor_role` is a nullable `ForeignKey` to `LaborRole`.
- The HQ worker form is `apps.labor.forms.WorkerMasterForm` and renders the field at `/app/hq/labor/workers/new/`.
- Before this change the form ordered all `LaborRole` rows without filtering inactive rows.
- The local database contained six active roles and no `LAB-GEN`, `LAB-PAV`, `LAB-EQP`, `LAB-CMP`, or `LAB-PNT` codes.
- Existing roles are created by prior operational/demo data, not by a reusable LaborRole seed command.
- `LaborRole.code` is unique. `LaborRateTable` exists separately and no default rates were present for the required roles.
- The seed uses the canonical master model, has no template-only options, and does not alter WorkerMaster PII handling.
