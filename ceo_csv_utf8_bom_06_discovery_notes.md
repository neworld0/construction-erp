# CEO CSV UTF-8 BOM Discovery Notes

- Download URL: `/api/ceo/reports/project-summary.csv`.
- Handler: `apps.ceo.views.CEOProjectSummaryReportView`.
- Existing CSV columns are the ten stable `project_*`, KPI, and risk columns.
- Before this patch the response used `text/csv`, a quoted ASCII filename, and no UTF-8 BOM.
- Access is controlled by `CEOAccessPermission` plus CEO/HQ role enforcement. FIELD is denied.
- Existing export auditing remains `REPORT_EXPORT`; no file contents are logged.
- Other CSV exports were discovered but intentionally left outside this focused CEO dashboard patch.
