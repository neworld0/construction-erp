# RELEASE-1-STAGING-SMOKE-RERUN command plan

1. Validate host identity, non-production DB class, branch/commit, and secure env status.
2. Run WSGI import, Gunicorn import/service status, Nginx nginx -t, then HTTPS healthz.
3. Verify static/media policy without reading sensitive file contents.
4. Create or use approved isolated restore DB; verify archive checksum; restore without touching active DB; run migration/health/count-only AuditLog checks.
5. Run CEO/HQ/FIELD/LABPAY route and RBAC smoke with staging-safe test accounts.
6. Scan evidence for UTF-8, secrets, and raw PII; request limited staging pilot approval only if P0 is zero.
