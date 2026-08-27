# BUDGET-IMPORT-CBS-MATCH-01

## Result
- status: PASS
- root cause: source CBS metadata was discarded before matching; three required masters were not in the civil-road seed.
- safety: unresolved valid rows remain visible as `UNMATCHED_CBS` and block registration.
- reconciliation fixture: 11 rows / 132,000,000 contract amount / 0 difference after exact master provision.
- migrations: none

## Operator action
Run `python manage.py seed_civil_road_cbs` in the approved environment to provision the new reusable CBS masters, then re-preview the workbook. The import path does not create masters automatically.
