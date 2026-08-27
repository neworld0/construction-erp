# Root Cause

1. The parser retained only the work-code column and did not preserve source `CBS코드`, `CBS명`, WBS metadata, or source row number.
2. Matching therefore fell back to item-text heuristics. It could not perform exact `CostItem.code` matching for `CIVIL-QUALITY`, `CIVIL-FINISH`, or `CIVIL-DOCUMENT`.
3. These CBS masters were absent from the civil-road seed set.
4. The previous workflow exposed unmatched lines but permitted a checkbox-based partial import.

The patch preserves source metadata, prefers exact active CBS code, reports `UNMATCHED_CBS` without generic-expense fallback, and blocks commit until HQ resolves every valid unmatched row.
