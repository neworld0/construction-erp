# Isolated restore drill report

- restore executed: NO
- backup file: `construction_erp_demo_20260805_135828.dump`
- backup checksum: `960c335505969bd43c83daf0208000eae0b27a9695274ed689e0126ee9c21d1d`
- restore command class: createdb + pg_restore --no-owner --no-privileges
- migration verification: NOT_EXECUTED because restore target creation was denied
- AuditLog presence check: NOT_EXECUTED in restore target; source backup policy preserves AuditLog
- raw PII printed: NO
- cleanup performed: NO
- media backup policy: MEDIA_BACKUP_POLICY_PENDING
- Result: HOLD. `erp_user` has no CREATEDB privilege; perform the same command on an approved isolated staging restore target.
