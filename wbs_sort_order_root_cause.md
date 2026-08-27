# WBS Sort Order Root Cause

`WBSItem.sort_order` has a model default of `0`, but it is an `IntegerField` without `blank=True`.
Therefore Django's `WBSItemForm` marks it required by default. The HQ project detail template does not render a sort-order control, so a valid WBS edit posted without the technical field failed form validation before `WBSItem.save()` could apply the model default.

The fix keeps the model field and its ordering index intact while assigning a deterministic value in the form/save/import flow.
