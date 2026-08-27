"""Create a non-destructive local restore database and verify it without PII output."""

from __future__ import annotations

import hashlib
import json
import os
import subprocess
import sys
from datetime import datetime
from pathlib import Path
from urllib.parse import quote

os.environ.setdefault("DJANGO_SETTINGS_MODULE", "config.settings.local")

import django

django.setup()

from django.db import connection


ROOT = Path(__file__).resolve().parent


def run(command: list[str], environment: dict[str, str]) -> subprocess.CompletedProcess:
    return subprocess.run(command, env=environment, capture_output=True, text=True)


def main() -> int:
    config = connection.settings_dict
    source_name = str(config.get("NAME") or "")
    host = str(config.get("HOST") or "")
    safe_source = (
        connection.vendor == "postgresql"
        and host in {"127.0.0.1", "localhost", ""}
        and "demo" in source_name.lower()
    )
    backup_files = sorted((ROOT / "release1_fix_backups").glob("*.dump"))
    if not safe_source or not backup_files:
        result = {
            "status": "RESTORE_BLOCKED_UNSAFE_TARGET",
            "restore_executed": False,
            "reason": "Source must be loopback local demo PostgreSQL and a backup archive must exist.",
        }
        (ROOT / "release1_staging_restore_result.json").write_text(
            json.dumps(result, ensure_ascii=False, indent=2), encoding="utf-8"
        )
        return 2

    backup_path = backup_files[-1]
    timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
    restore_name = f"construction_erp_demo_restore_{timestamp}"
    environment = os.environ.copy()
    if config.get("PASSWORD"):
        environment["PGPASSWORD"] = str(config["PASSWORD"])
    host_value = host or "localhost"
    port = str(config.get("PORT") or 5432)
    user = str(config.get("USER") or "")

    created = run(
        [
            "createdb",
            "--host",
            host_value,
            "--port",
            port,
            "--username",
            user,
            restore_name,
        ],
        environment,
    )
    if created.returncode:
        result = {
            "status": "RESTORE_CREATE_DB_FAILED",
            "restore_executed": False,
            "restore_target": restore_name,
            "reason": "createdb returned a non-zero exit code; stderr is not persisted to avoid secrets.",
        }
        (ROOT / "release1_staging_restore_result.json").write_text(
            json.dumps(result, ensure_ascii=False, indent=2), encoding="utf-8"
        )
        return created.returncode

    restored = run(
        [
            "pg_restore",
            "--no-owner",
            "--no-privileges",
            "--dbname",
            restore_name,
            str(backup_path),
        ],
        environment,
    )
    if restored.returncode:
        result = {
            "status": "RESTORE_FAILED_ISOLATED_DB_RETAINED",
            "restore_executed": False,
            "restore_target": restore_name,
            "reason": "pg_restore returned a non-zero exit code; isolated DB was retained for investigation.",
        }
        (ROOT / "release1_staging_restore_result.json").write_text(
            json.dumps(result, ensure_ascii=False, indent=2), encoding="utf-8"
        )
        return restored.returncode

    database_url = "postgresql://{}:{}@{}:{}/{}".format(
        quote(user, safe=""),
        quote(str(config.get("PASSWORD") or ""), safe=""),
        host_value,
        port,
        restore_name,
    )
    restore_environment = environment.copy()
    restore_environment["DATABASE_URL"] = database_url
    check = run([sys.executable, "manage.py", "check"], restore_environment)
    migrations = run([sys.executable, "manage.py", "showmigrations"], restore_environment)
    health = run(
        [
            sys.executable,
            "-c",
            "import os; os.environ.setdefault('DJANGO_SETTINGS_MODULE','config.settings.local'); import django; django.setup(); from django.test import Client; response=Client(HTTP_HOST='localhost').get('/healthz/', HTTP_HOST='localhost'); print(response.status_code)",
        ],
        restore_environment,
    )
    import psycopg

    with psycopg.connect(database_url) as restore_connection:
        with restore_connection.cursor() as cursor:
            cursor.execute("SELECT COUNT(*) FROM projects_project")
            project_count = cursor.fetchone()[0]
            cursor.execute("SELECT COUNT(*) FROM audit_auditlog")
            audit_count = cursor.fetchone()[0]
            cursor.execute("SELECT COUNT(*) FROM django_migrations")
            migration_count = cursor.fetchone()[0]

    result = {
        "status": "ISOLATED_RESTORE_EXECUTED",
        "restore_executed": True,
        "restore_target": restore_name,
        "target_classification": "LOCAL_DEMO_ISOLATED",
        "backup_filename": backup_path.name,
        "backup_sha256": hashlib.sha256(backup_path.read_bytes()).hexdigest(),
        "restore_command_class": "createdb + pg_restore --no-owner --no-privileges",
        "django_check_pass": check.returncode == 0,
        "migration_command_pass": migrations.returncode == 0,
        "health_status": health.stdout.strip(),
        "project_count": project_count,
        "auditlog_count": audit_count,
        "migration_count": migration_count,
        "cleanup_performed": False,
        "raw_pii_printed": False,
    }
    (ROOT / "release1_staging_restore_result.json").write_text(
        json.dumps(result, ensure_ascii=False, indent=2), encoding="utf-8"
    )
    (ROOT / "release1_staging_actual_restore_log.txt").write_text(
        "\n".join(
            [
                "RESTORE_TARGET_CLASS=LOCAL_DEMO_ISOLATED",
                f"RESTORE_TARGET={restore_name}",
                "CREATEDB=PASS",
                "PG_RESTORE=PASS",
                f"DJANGO_CHECK={'PASS' if check.returncode == 0 else 'FAIL'}",
                f"SHOWMIGRATIONS={'PASS' if migrations.returncode == 0 else 'FAIL'}",
                f"HEALTHZ_STATUS={health.stdout.strip()}",
                f"PROJECT_COUNT={project_count}",
                f"AUDITLOG_COUNT={audit_count}",
                f"MIGRATION_COUNT={migration_count}",
                "CLEANUP_PERFORMED=NO",
                "RAW_PII_PRINTED=NO",
            ]
        )
        + "\n",
        encoding="utf-8",
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
