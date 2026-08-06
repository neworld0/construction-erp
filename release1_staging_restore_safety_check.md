# Isolated restore safety check

- restore target: `construction_erp_demo_restore_<timestamp>`
- not production: PASS; loopback local demo source only
- isolated: intended new database, never the active source DB
- backup checksum: `960c335505969bd43c83daf0208000eae0b27a9695274ed689e0126ee9c21d1d`
- operator: local release verification session
- Result: HOLD. The PostgreSQL role has no CREATEDB permission, so no restore target was created and no restore command was allowed to run.
