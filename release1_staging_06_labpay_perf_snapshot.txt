# RELEASE-1-FIX LABPAY e-card import list performance diagnosis

## Route and baseline
Route: `/app/hq/labor/e-card-imports/`. The prior queryset used `Count(distinct=True)` across raw rows, day rows, and reconciliation results in one SQL query. With 3 batches, 72 raw rows, 2,232 day rows, and 702 reconciliation rows, the one-time read-only legacy query took 265.355231 seconds.

## Patch
The list now applies filters and the 50-batch limit before counting. It obtains raw/day/reconciliation counts with three grouped relations queries and attaches transient display attributes. No model, schema, upload, parse, reconcile, AuditLog, or RBAC behavior changed.

## after measurement
The post-patch route returned HTTP 200 in all three runs. The cold run was 0.367431 seconds and warmed runs were approximately 0.008 seconds, well under the 10-second hard ceiling. Against the 265.355231-second baseline, the conservative cold-run improvement is approximately 99.86 percent.

## SQL and response time evidence
```csv
Run_ID,Route,Scenario,Batch_Count,Raw_Row_Count,Day_Row_Count,Reconciliation_Row_Count,SQL_Query_Count,Elapsed_Seconds,Baseline_or_After,Result,Notes
L-BASELINE,/app/hq/labor/e-card-imports/,legacy multi-relation Count distinct queryset,3,72,2232,702,1,265.355231,Baseline,DIAGNOSED,read-only legacy query measurement
L-AFTER-1,/app/hq/labor/e-card-imports/,current grouped-count list route,3,72,2232,702,8,0.367431,After,PASS,HTTP 200
L-AFTER-2,/app/hq/labor/e-card-imports/,current grouped-count list route,3,72,2232,702,8,0.007535,After,PASS,HTTP 200
L-AFTER-3,/app/hq/labor/e-card-imports/,current grouped-count list route,3,72,2232,702,8,0.007981,After,PASS,HTTP 200

```

## Conclusion
LABPAY list performance is resolved locally. Recheck the route under realistic staging data volume after deployment; safe real-file parsing remains a separate functional verification item.
