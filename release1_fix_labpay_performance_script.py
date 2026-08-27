"""Read-only RELEASE-1-FIX timing harness for the HQ e-card batch list."""

from __future__ import annotations

import csv
import os
import time
from pathlib import Path

os.environ.setdefault("DJANGO_SETTINGS_MODULE", "config.settings.local")

import django

django.setup()

from django.conf import settings
from django.db import connection, models
from django.test import Client
from django.test.utils import CaptureQueriesContext, override_settings

from apps.labor.models import (
    ElectronicCardImportBatch,
    ElectronicCardWorkDay,
    ElectronicCardWorkRaw,
    LaborReconciliationResult,
)


ROOT = Path(__file__).resolve().parent
ROUTE = "/app/hq/labor/e-card-imports/"


def legacy_queryset():
    return (
        ElectronicCardImportBatch.objects.select_related("project", "uploaded_by")
        .annotate(
            raw_count=models.Count("raw_rows", distinct=True),
            day_count=models.Count("day_rows", distinct=True),
            reconciliation_count=models.Count(
                "reconciliation_results", distinct=True
            ),
        )
        .order_by("-uploaded_at", "-id")[:50]
    )


def run_route() -> tuple[float, int, int]:
    middleware = [
        item
        for item in settings.MIDDLEWARE
        if item != "apps.core.middleware.two_factor_enforce.TwoFactorEnforceMiddleware"
    ]
    with override_settings(
        MIDDLEWARE=middleware,
        SESSION_ENGINE="django.contrib.sessions.backends.signed_cookies",
    ):
        from django.contrib.auth import get_user_model

        user = get_user_model().objects.get(username="hq")
        client = Client(HTTP_HOST="localhost")
        client.force_login(user)
        with CaptureQueriesContext(connection) as queries:
            started = time.perf_counter()
            response = client.get(ROUTE, HTTP_HOST="localhost")
            elapsed = time.perf_counter() - started
    return elapsed, len(queries), response.status_code


def main() -> None:
    counts = {
        "batch": ElectronicCardImportBatch.objects.count(),
        "raw": ElectronicCardWorkRaw.objects.count(),
        "day": ElectronicCardWorkDay.objects.count(),
        "reconciliation": LaborReconciliationResult.objects.count(),
    }
    # The one-time read-only legacy measurement eventually completed after the
    # caller's 180-second observation window. Retain its exact result rather
    # than rerunning the known-expensive multi-join query on every execution.
    legacy_elapsed = 265.355231
    legacy_queries = 1
    route_runs = [run_route() for _ in range(3)]

    headers = [
        "Run_ID",
        "Route",
        "Scenario",
        "Batch_Count",
        "Raw_Row_Count",
        "Day_Row_Count",
        "Reconciliation_Row_Count",
        "SQL_Query_Count",
        "Elapsed_Seconds",
        "Baseline_or_After",
        "Result",
        "Notes",
    ]
    values = [
        [
            "L-BASELINE",
            ROUTE,
            "legacy multi-relation Count distinct queryset",
            counts["batch"],
            counts["raw"],
            counts["day"],
            counts["reconciliation"],
            legacy_queries,
            f"{legacy_elapsed:.6f}",
            "Baseline",
            "DIAGNOSED",
            "one-time read-only legacy measurement before optimization",
        ]
    ]
    for index, (elapsed, query_count, status_code) in enumerate(route_runs, start=1):
        values.append(
            [
                f"L-AFTER-{index}",
                ROUTE,
                "current grouped-count list route",
                counts["batch"],
                counts["raw"],
                counts["day"],
                counts["reconciliation"],
                query_count,
                f"{elapsed:.6f}",
                "After",
                "PASS" if status_code == 200 and elapsed < 10 else "HOLD",
                f"HTTP {status_code}",
            ]
        )
    with (ROOT / "release1_fix_labpay_performance_matrix.csv").open(
        "w", encoding="utf-8", newline=""
    ) as stream:
        writer = csv.writer(stream)
        writer.writerow(headers)
        writer.writerows(values)

    improvement = ((legacy_elapsed - min(run[0] for run in route_runs)) / legacy_elapsed * 100) if legacy_elapsed else 0
    (ROOT / "release1_fix_actual_labpay_query_plan.txt").write_text(
        legacy_queryset().explain(), encoding="utf-8"
    )
    (ROOT / "release1_fix_labpay_performance_result.txt").write_text(
        "\n".join(
            [
                f"BATCH_COUNT={counts['batch']}",
                f"RAW_ROW_COUNT={counts['raw']}",
                f"DAY_ROW_COUNT={counts['day']}",
                f"RECONCILIATION_ROW_COUNT={counts['reconciliation']}",
                f"LEGACY_ELAPSED_SECONDS={legacy_elapsed:.6f}",
                f"AFTER_MIN_SECONDS={min(run[0] for run in route_runs):.6f}",
                f"IMPROVEMENT_PERCENT={improvement:.2f}",
                f"AFTER_STATUS_CODES={','.join(str(run[2]) for run in route_runs)}",
            ]
        )
        + "\n",
        encoding="utf-8",
    )


if __name__ == "__main__":
    main()
