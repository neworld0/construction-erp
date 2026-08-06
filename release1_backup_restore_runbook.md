# RELEASE-1 backup and restore runbook

## backup purpose
Take a verified backup before staging migrate, destructive cleanup, or release cutover. A backup is the only reliable DB rollback path.

## backup templates
```powershell
pg_dump --format=custom --file <BACKUP_DIR>/erp_<DATE>.dump <DATABASE_NAME>
Compress-Archive -Path <MEDIA_ROOT> -DestinationPath <BACKUP_DIR>/media_<DATE>.zip
```
Use protected credentials outside this document. Do not paste connection passwords into tickets or logs.

## restore templates
```powershell
pg_restore --clean --if-exists --dbname <DATABASE_NAME> <BACKUP_FILE>
Expand-Archive <MEDIA_BACKUP_FILE> -DestinationPath <MEDIA_ROOT>
```
Restore only to an approved isolated target. Do not run a blind restore over an active production database.

## restore verification
1. Confirm migration version and health endpoint.
2. Confirm CEO dashboard, FIELD assigned progress, and login/RBAC smoke.
3. Confirm media and generated Excel files are readable.
4. Confirm AuditLog remains preserved and masked.

## principles
AuditLog is retained as evidence. Backup before destructive cleanup and before staging migration. Record operator, time, backup ID, and verification result without storing secrets.
