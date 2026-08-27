# Security check

- DEBUG: NOT_VERIFIED on staging
- SECRET_KEY: status NOT_VERIFIED; value not printed
- ALLOWED_HOSTS: NOT_VERIFIED on staging
- CSRF: NOT_VERIFIED on staging
- SESSION_COOKIE_SECURE: NOT_VERIFIED on staging
- raw PII: NO raw PII printed in rerun artifacts
- secret exposure: NO secret values printed
- Result: HOLD until secure environment status is provided and checked on host.
