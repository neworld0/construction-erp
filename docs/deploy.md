# Deployment Guide (Production)

This document describes the minimal production deployment steps for `construction-erp`.

## 1) Environment variables

Prepare `.env.prod` using `.env.prod.example` as a base. Required variables:

- `DJANGO_SETTINGS_MODULE=config.settings.prod`
- `DJANGO_SECRET_KEY`
- `DJANGO_ALLOWED_HOSTS`
- `DATABASE_URL`
- `DJANGO_CSRF_TRUSTED_ORIGINS`
- `DJANGO_SECURE_SSL_REDIRECT`
- `DJANGO_SESSION_COOKIE_SECURE`
- `DJANGO_CSRF_COOKIE_SECURE`
- `DJANGO_SECURE_HSTS_SECONDS`
- `DJANGO_LOG_LEVEL`
- `DJANGO_TIME_ZONE`

Notes:
- `.env.prod` is loaded first in `config.settings.prod`, `.env` is a fallback.
- Keep `.env` for local only, use `.env.local` for per-machine overrides.

## 2) Production checks

Run the deploy checks with production settings:

```
python manage.py check --deploy --settings=config.settings.prod
```

Fix any warnings before continuing (especially SECRET_KEY and ALLOWED_HOSTS).

## 3) Migration and static files

Recommended order:

```
python manage.py migrate --settings=config.settings.prod
python manage.py collectstatic --noinput --settings=config.settings.prod
```

## 4) Gunicorn (example)

```
gunicorn config.wsgi:application \
  --bind 0.0.0.0:8000 \
  --workers 3 \
  --log-level ${DJANGO_LOG_LEVEL:-info}
```

## 5) WhiteNoise (optional)

If `whitenoise` is installed, `config.settings.prod` will enable it automatically:
- `WhiteNoiseMiddleware` is inserted into `MIDDLEWARE`
- `STATICFILES_STORAGE` uses `CompressedManifestStaticFilesStorage`

If you do not want WhiteNoise, remove it from dependencies or disable it in prod settings.

## 6) Health check

Confirm readiness endpoint:

```
curl http://127.0.0.1:8000/healthz/
```

Expected JSON:
```
{"status":"ok","service":"construction-erp","time":"...","db":"ok"}
```

## 7) Command quick list

```
python manage.py migrate --settings=config.settings.prod
python manage.py collectstatic --noinput --settings=config.settings.prod
python manage.py createsuperuser --settings=config.settings.prod
python manage.py check --deploy --settings=config.settings.prod
```

## 8) Rollback strategy (minimal)

- If migrations fail, stop the deployment.
- Restore the previous application release.
- Roll back the database to the last known good migration:

```
python manage.py migrate <app_name> <migration_name> --settings=config.settings.prod
```

Keep backups before deploying schema changes.
