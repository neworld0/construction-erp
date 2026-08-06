# RELEASE-1 rollback plan

## release abort criteria
Abort before cutover if manage.py check fails, migrations are unexpected, CEO dashboard returns 500, FIELD cannot use an assigned project, RBAC bypass appears, or raw PII/secrets are exposed.

## code rollback
Deploy the previous approved release artifact, restart the service, and re-run health and CEO/FIELD smoke. Do not use an unreviewed local branch as rollback source.

## config rollback
Restore the previous approved environment file from the secure configuration store. Confirm ALLOWED_HOSTS, HTTPS settings, and database endpoint without printing secret values.

## DB rollback
DB rollback requires the verified backup created before migrate. Follow the backup runbook; do not reverse migrations or restore data blindly.

## media rollback
Restore the matching media backup only after confirming file ownership and generated Excel retention requirements.

## static rollback
Re-run approved collectstatic for the restored release or restore the matching static artifact.

## communication and evidence
Classify incidents P0/P1/P2, notify the release owner, preserve AuditLog and server evidence, and record the rollback decision. Audit evidence is not discarded during rollback.
