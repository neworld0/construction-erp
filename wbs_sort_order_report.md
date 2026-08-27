# WBS-SORT-ORDER-01 Report

## Result

- Status: PASS
- Root cause: the WBS ModelForm treated `sort_order` as required before the model default or save logic could run.
- Fix: make the form field optional and resolve ordering at every WBS baseline save/import boundary.
- Migration: none.

## Behavior

- Explicit numeric order is preserved.
- A `WBS-<number>` code in the imported code or manual task name becomes `number * 10`.
- Rows without a parseable WBS code use their one-based input row number times 10.
- Existing detail rows without a submitted order retain their stored order.

## Verification

- `python manage.py check`: PASS
- Focused regression suite: 15 passed.
