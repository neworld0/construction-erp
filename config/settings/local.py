"""Local settings.

Load environment variables from the project root .env file.
"""

import os
import sys
from urllib.parse import urlparse

from dotenv import load_dotenv

from .base import *  # noqa: F403


load_dotenv(BASE_DIR / ".env")
load_dotenv(BASE_DIR / ".env.local")


def _env_bool(name: str, default: bool) -> bool:
    value = os.getenv(name)
    if value is None:
        return default
    return value.strip().lower() in ("1", "true", "yes", "on")


def _env_list(name: str, default: list[str] | None = None) -> list[str]:
    raw = os.getenv(name)
    if not raw:
        return default or []
    return [item.strip() for item in raw.split(",") if item.strip()]


def _database_from_url(url: str | None):
    if not url:
        return None
    parsed = urlparse(url)
    if parsed.scheme not in ("postgres", "postgresql"):
        return None
    return {
        "ENGINE": "django.db.backends.postgresql",
        "NAME": parsed.path.lstrip("/"),
        "USER": parsed.username or "",
        "PASSWORD": parsed.password or "",
        "HOST": parsed.hostname or "",
        "PORT": str(parsed.port or ""),
    }


SECRET_KEY = os.getenv("DJANGO_SECRET_KEY", "change-me")
DEBUG = _env_bool("DJANGO_DEBUG", True)

ALLOWED_HOSTS = _env_list("DJANGO_ALLOWED_HOSTS", ["*"])
CSRF_TRUSTED_ORIGINS = _env_list("DJANGO_CSRF_TRUSTED_ORIGINS", [])
CORS_ALLOWED_ORIGINS = _env_list("DJANGO_CORS_ALLOWED_ORIGINS", [])

DATABASES = {"default": _database_from_url(os.getenv("DATABASE_URL"))}
if not DATABASES["default"]:
    DATABASES["default"] = {
        "ENGINE": "django.db.backends.postgresql",
        "NAME": os.getenv("DB_NAME", "erp_local"),
        "USER": os.getenv("DB_USER", "erp_user"),
        "PASSWORD": os.getenv("DB_PASSWORD", "erp_pass"),
        "HOST": os.getenv("DB_HOST", "127.0.0.1"),
        "PORT": os.getenv("DB_PORT", "5432"),
    }

_is_pytest = "pytest" in sys.modules or "pytest" in sys.argv[0].lower()
if _is_pytest or os.getenv("PYTEST_CURRENT_TEST"):
    DATABASES = {
        "default": {
            "ENGINE": "django.db.backends.sqlite3",
            "NAME": BASE_DIR / "db_test.sqlite3",
        }
    }


# Ensure request/server/app logs are always visible in local runserver consoles.
LOGGING = LOGGING.copy()  # noqa: F405
LOGGING["disable_existing_loggers"] = False
LOGGING["handlers"] = LOGGING.get("handlers", {}).copy()
LOGGING["handlers"]["console"] = {
    "class": "logging.StreamHandler",
    "formatter": "standard",
    # Use stdout so request logs are visible in terminals/IDEs that hide stderr.
    "stream": sys.stdout,
}

_default_level = os.getenv("DJANGO_LOG_LEVEL", "INFO").upper()
LOGGING["loggers"] = LOGGING.get("loggers", {}).copy()
for _name, _level in (
    ("django", _default_level),
    ("django.server", "INFO"),
    ("django.request", "INFO"),
    ("django.db.backends", os.getenv("DJANGO_SQL_LOG_LEVEL", "WARNING").upper()),
    ("apps", _default_level),
):
    _logger_cfg = LOGGING["loggers"].get(_name, {}).copy()
    _logger_cfg["handlers"] = ["console"]
    _logger_cfg["level"] = _level
    _logger_cfg["propagate"] = False
    LOGGING["loggers"][_name] = _logger_cfg

LOGGING["root"] = {
    "handlers": ["console"],
    "level": _default_level,
}

DATA_UPLOAD_MAX_NUMBER_FIELDS = 10000
