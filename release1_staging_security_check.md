# Security / secret / PII check

- DEBUG: local value is development-only; staging DEBUG is NOT_VERIFIED and must be false.
- SECRET_KEY: status is PRESENT in local configuration; value not printed.
- ALLOWED_HOSTS: local wildcard is development-only; staging allowlist is NOT_VERIFIED.
- CSRF: staging CSRF_TRUSTED_ORIGINS is NOT_VERIFIED.
- SESSION_COOKIE_SECURE and CSRF cookie security: must be enabled for HTTPS staging; NOT_VERIFIED on host.
- DATABASE_URL: status is PRESENT locally; value not printed.
- PII: generated staging artifacts contain no raw RRN, phone, account number, or names from upload data.
- AuditLog masking: no policy change made.
- Result: HOLD pending actual staging production-like settings check.
