# LOCAL-OPS Reset Rollback Note

- Database: `construction_erp_demo` on `127.0.0.1`
- Backup: `local_ops_reset_before_20260814_115052.dump`
- Backup type: PostgreSQL custom-format `pg_dump`
- Media files: not touched
- Dry-run manifests: `local_ops_reset_dryrun_*.csv`

Restore command:

```powershell
pg_restore --clean --if-exists --host 127.0.0.1 --username erp_user --dbname construction_erp_demo local_ops_reset_before_20260814_115052.dump
```

The reset deletes local project-scoped operational data. It cannot be rebuilt
without this backup or a deliberate reseed/import.
