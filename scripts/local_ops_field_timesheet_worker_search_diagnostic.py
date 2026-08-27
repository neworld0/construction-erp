"""Write a safe, read-only candidate snapshot for FIELD worker search."""

import csv
import os
import sys
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
os.environ.setdefault("DJANGO_SETTINGS_MODULE", "config.settings.local")

import django

django.setup()

from apps.labor.models import WorkerMaster


OUTPUT_PATH = ROOT / "field_timesheet_worker_search_candidate_snapshot.csv"


def main():
    fields = [
        "worker_id",
        "worker_name",
        "default_labor_role_code",
        "default_labor_role_name",
        "active",
        "search_visible",
        "note",
    ]
    workers = WorkerMaster.objects.select_related("default_labor_role").order_by("name", "id")
    with OUTPUT_PATH.open("w", encoding="utf-8-sig", newline="") as output:
        writer = csv.DictWriter(output, fieldnames=fields)
        writer.writeheader()
        for worker in workers:
            role = worker.default_labor_role
            writer.writerow(
                {
                    "worker_id": worker.id,
                    "worker_name": worker.name,
                    "default_labor_role_code": role.code if role else "",
                    "default_labor_role_name": role.name if role else "",
                    "active": worker.active,
                    "search_visible": worker.active,
                    "note": "주민등록번호, 연락처, 계좌번호는 포함하지 않습니다.",
                }
            )

    print(f"ACTIVE_WORKER_COUNT={workers.filter(active=True).count()}")
    print(f"CANDIDATE_SNAPSHOT={OUTPUT_PATH.name}")


if __name__ == "__main__":
    main()
