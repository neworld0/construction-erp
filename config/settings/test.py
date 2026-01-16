"""Test settings.

Use SQLite to avoid external DB dependencies during pytest runs.
"""

from .base import *  # noqa: F403

ENV_NAME = "test"
DEBUG = False

DATABASES = {
    "default": {
        "ENGINE": "django.db.backends.sqlite3",
        "NAME": BASE_DIR / "db_test.sqlite3",  # noqa: F405
    }
}
