# Gunicorn verification

- WSGI_IMPORT_OK: PASS on local Django environment.
- Gunicorn: NOT_EXECUTED; module is unavailable on Windows local.
- workers: staging template specifies 2-3 workers.
- timeout: staging template specifies 120 seconds.
- bind/log/env file: template-only placeholders; no staging service is reachable.
- Result: HOLD. Verify `gunicorn config.wsgi:application --check-config` and service status on Linux staging.
