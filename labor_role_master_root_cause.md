# Root Cause

The worker registration dropdown was populated directly from the local `LaborRole` table. That table had only six active operational roles and there was no canonical, idempotent seed path for the LOCAL-OPS role codes. Consequently `장비공`, `다짐공`, and `도색공` could not be selected.

The form also did not restrict a new registration to active roles. The correction seeds the required master rows by stable code and uses active roles for the new-worker dropdown. Existing rows and their code references remain untouched.
