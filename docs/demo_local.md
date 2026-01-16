# Demo Local Run (Prod Settings)

This guide runs the demo locally using production settings and `.env.demo`.

## 1) Demo DB
Example with PostgreSQL:

```
psql -U postgres
CREATE USER erp_user WITH PASSWORD 'erp_pass';
CREATE DATABASE construction_erp_demo OWNER erp_user;
GRANT ALL PRIVILEGES ON DATABASE construction_erp_demo TO erp_user;
```

## 2) Prepare .env.demo
Create `C:\projects\construction-erp\.env.demo` with demo-safe values.
Example keys:

```
DJANGO_SECRET_KEY=replace-with-long-random-value
DJANGO_DEBUG=true
DJANGO_ALLOWED_HOSTS=localhost,127.0.0.1
DATABASE_URL=postgres://erp_user:erp_pass@127.0.0.1:5432/construction_erp_demo
DJANGO_CSRF_TRUSTED_ORIGINS=http://127.0.0.1:8000
DJANGO_SECURE_SSL_REDIRECT=false
DJANGO_SESSION_COOKIE_SECURE=false
DJANGO_CSRF_COOKIE_SECURE=false
DJANGO_SECURE_HSTS_SECONDS=0
DJANGO_LOG_LEVEL=INFO
DJANGO_TIME_ZONE=Asia/Seoul
```

Note: `config.settings.prod` loads `.env.demo` with override, so you do not need to copy it to `.env`.

## 3) Migrate + collectstatic

```
$env:DJANGO_SETTINGS_MODULE="config.settings.prod"
python manage.py migrate
python manage.py collectstatic --noinput
```

## 4) Seed data

```
python manage.py seed_initial
python manage.py seed_demo_flow
```

## 5) Run server

```
python manage.py runserver --settings=config.settings.prod
```

## 6) Demo accounts (examples)
- ceo / example-password
- hq / example-password
- field1 / example-password

## 7) Health check

```
Invoke-WebRequest http://127.0.0.1:8000/healthz/ -UseBasicParsing
```
