# RELEASE-1-FIX staging Gunicorn configuration

## Staging command
```bash
cd <PROJECT_ROOT>
export DJANGO_SETTINGS_MODULE=config.settings.prod
gunicorn config.wsgi:application \
  --bind 127.0.0.1:8000 \
  --workers 3 \
  --timeout 120 \
  --access-logfile <LOG_DIR>/gunicorn-access.log \
  --error-logfile <LOG_DIR>/gunicorn-error.log
```

Set `DJANGO_SECRET_KEY`, `DJANGO_ALLOWED_HOSTS`, `DATABASE_URL`, `DJANGO_CSRF_TRUSTED_ORIGINS`, HTTPS cookie flags, and log level in the secure staging environment. Never put values in this file.

## systemd template
```ini
[Service]
WorkingDirectory=<PROJECT_ROOT>
Environment=DJANGO_SETTINGS_MODULE=config.settings.prod
EnvironmentFile=<SECURE_ENV_FILE>
ExecStart=<VENV>/bin/gunicorn config.wsgi:application --bind <GUNICORN_BIND> --workers 3 --timeout 120 --access-logfile <LOG_DIR>/gunicorn-access.log --error-logfile <LOG_DIR>/gunicorn-error.log
Restart=on-failure
```

Nginx owns public static/media delivery; Gunicorn serves Django only. Start with 2-3 workers, use timeout 120 seconds for controlled Excel/LABPAY operations, and validate with `python -c "import config.wsgi; print('WSGI_IMPORT_OK')"` plus a local Nginx health request. Windows local is not a Gunicorn validation host.
