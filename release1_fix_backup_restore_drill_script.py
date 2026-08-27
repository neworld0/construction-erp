"""Safe local-demo PostgreSQL backup drill; never restores into an active DB."""

from __future__ import annotations

import hashlib
import json
import os
import subprocess
from datetime import datetime
from pathlib import Path

os.environ.setdefault("DJANGO_SETTINGS_MODULE", "config.settings.local")

import django

django.setup()

from django.conf import settings
from django.db import connection


ROOT = Path(__file__).resolve().parent
BACKUP_DIR = ROOT / "release1_fix_backups"


def main() -> int:
    config = connection.settings_dict
    name = str(config.get("NAME") or "")
    host = str(config.get("HOST") or "")
    vendor = connection.vendor
    safe_host = host in {"127.0.0.1", "localhost", ""}
    safe_name = any(token in name.lower() for token in ("demo", "local", "staging"))
    if vendor != "postgresql" or not safe_host or not safe_name:
        payload = {
            "status": "BACKUP_DRILL_BLOCKED_UNSAFE_TARGET",
            "vendor": vendor,
            "database_name": name,
            "host_classification": "LOCAL" if safe_host else "NON_LOCAL",
            "backup_executed": False,
            "restore_executed": False,
        }
        (ROOT / "release1_fix_backup_restore_result.json").write_text(
            json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8"
        )
        return 2

    BACKUP_DIR.mkdir(exist_ok=True)
    timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
    backup_path = BACKUP_DIR / f"construction_erp_demo_{timestamp}.dump"
    environment = os.environ.copy()
    if config.get("PASSWORD"):
        environment["PGPASSWORD"] = str(config["PASSWORD"])
    command = [
        "pg_dump",
        "--format=custom",
        "--no-owner",
        "--no-privileges",
        "--host",
        host or "localhost",
        "--port",
        str(config.get("PORT") or 5432),
        "--username",
        str(config.get("USER") or ""),
        "--file",
        str(backup_path),
        name,
    ]
    backup = subprocess.run(command, env=environment, capture_output=True, text=True)
    if backup.returncode:
        payload = {
            "status": "BACKUP_FAILED",
            "vendor": vendor,
            "database_name": name,
            "host_classification": "LOCAL_DEMO",
            "backup_executed": False,
            "restore_executed": False,
            "error": "pg_dump returned a non-zero exit code; stderr is not persisted to avoid secrets.",
        }
        (ROOT / "release1_fix_backup_restore_result.json").write_text(
            json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8"
        )
        return backup.returncode

    archive_list = subprocess.run(
        ["pg_restore", "--list", str(backup_path)],
        env=environment,
        capture_output=True,
        text=True,
    )
    checksum = hashlib.sha256(backup_path.read_bytes()).hexdigest()
    payload = {
        "status": "LOGICAL_BACKUP_EXECUTED_RESTORE_COMMAND_VERIFIED",
        "vendor": vendor,
        "database_name": name,
        "host_classification": "LOCAL_DEMO",
        "backup_executed": True,
        "backup_filename": backup_path.name,
        "backup_size_bytes": backup_path.stat().st_size,
        "backup_sha256": checksum,
        "restore_executed": False,
        "restore_command_verified": archive_list.returncode == 0,
        "restore_verification": "pg_restore --list completed; no active database restore was attempted.",
        "media_backup": "NOT_EXECUTED_SENSITIVE_UPLOAD_REVIEW_REQUIRED",
        "media_root_exists": settings.MEDIA_ROOT.exists(),
    }
    (ROOT / "release1_fix_backup_restore_result.json").write_text(
        json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8"
    )
    (ROOT / "release1_fix_backup_restore_archive_list.txt").write_text(
        archive_list.stdout, encoding="utf-8"
    )
    return 0 if archive_list.returncode == 0 else archive_list.returncode


if __name__ == "__main__":
    raise SystemExit(main())
