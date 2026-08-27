from __future__ import annotations

from dataclasses import dataclass
from datetime import date, timedelta

from django.core.cache import cache
from django.utils import timezone

from apps.closing.services import is_month_closed

from .services import compute_project_kpi


@dataclass(frozen=True)
class Period:
    key: str
    start: date
    end: date


def _month_start(target: date) -> date:
    return date(target.year, target.month, 1)


def _month_end(target: date) -> date:
    if target.month == 12:
        return date(target.year, 12, 31)
    return date(target.year, target.month + 1, 1) - timedelta(days=1)


def _iter_months(start: date, end: date):
    cursor = _month_start(start)
    while cursor <= end:
        yield cursor
        if cursor.month == 12:
            cursor = date(cursor.year + 1, 1, 1)
        else:
            cursor = date(cursor.year, cursor.month + 1, 1)


def _iter_weeks(start: date, end: date):
    cursor = start - timedelta(days=start.isoweekday() - 1)
    while cursor <= end:
        yield cursor
        cursor = cursor + timedelta(days=7)


def build_periods(start: date, end: date, granularity: str) -> list[Period]:
    if granularity not in ("month", "week"):
        raise ValueError("granularity must be month or week")
    periods = []
    if granularity == "month":
        for month_start in _iter_months(start, end):
            month_end = _month_end(month_start)
            if month_end < start:
                continue
            if month_start > end:
                break
            periods.append(
                Period(
                    key=f"{month_start.year}-{month_start.month:02d}",
                    start=month_start,
                    end=min(month_end, end),
                )
            )
    else:
        for week_start in _iter_weeks(start, end):
            week_end = week_start + timedelta(days=6)
            if week_end < start:
                continue
            if week_start > end:
                break
            iso_year, iso_week, _ = week_start.isocalendar()
            periods.append(
                Period(
                    key=f"{iso_year}-W{iso_week:02d}",
                    start=week_start,
                    end=min(week_end, end),
                )
            )
    return periods


def _default_start(project, end: date) -> date:
    if getattr(project, "start_date", None):
        return project.start_date
    return end - timedelta(days=365)


def _normalize_metrics(metrics_param: str | None) -> list[str]:
    if not metrics_param:
        return [
            "contract_amount",
            "budget_total",
            "actual_cost",
            "labor_cost",
            "profit",
            "margin_pct",
        ]
    items = [item.strip() for item in metrics_param.split(",")]
    return [item for item in items if item]


def _metric_definitions() -> dict:
    return {
        "contract_amount": "Contract baseline amount",
        "budget_total": "Budget baseline total",
        "actual_cost": "Approved actual cost (with adjustments)",
        "labor_cost": "Approved labor cost",
        "profit": "Contract - actual cost",
        "margin_pct": "Profit / contract amount",
        "progress_pct": "Progress percent (not available)",
    }


def _calc_metrics(snapshot: dict, metrics: list[str]) -> dict:
    actual_cost = snapshot.get("actual", {}).get("submitted")
    labor_cost = snapshot.get("labor", {}).get("total")
    contract_amount = snapshot.get("contract", {}).get("amount")
    budget_total = snapshot.get("budget", {}).get("amount")
    gross_margin = snapshot.get("metrics", {}).get("gross_margin_est")
    gross_margin_rate = snapshot.get("metrics", {}).get("gross_margin_rate_est")

    result = {}
    for metric in metrics:
        if metric == "contract_amount":
            result[metric] = contract_amount
        elif metric == "budget_total":
            result[metric] = budget_total
        elif metric == "actual_cost":
            result[metric] = actual_cost
        elif metric == "labor_cost":
            result[metric] = labor_cost
        elif metric == "profit":
            result[metric] = gross_margin
        elif metric == "margin_pct":
            if gross_margin_rate is None:
                result[metric] = None
            else:
                result[metric] = round(gross_margin_rate * 100, 2)
        elif metric == "progress_pct":
            result[metric] = None
    return result


def _quality_label(
    snapshot_quality: dict,
    labor_quality: str | None,
    period_end: date,
    *,
    legal_entity,
) -> tuple[bool, str]:
    estimated = snapshot_quality.get("confidence") in ("LOW", "MEDIUM")
    if labor_quality == "ESTIMATED":
        estimated = True
    is_closed = is_month_closed(period_end, legal_entity=legal_entity)
    if labor_quality == "UNSURE" and not estimated:
        return False, "UNSURE"
    if estimated:
        return is_closed, "ESTIMATED"
    if is_closed:
        return True, "OK"
    return False, "UNSURE"


def build_timeline(project, *, granularity="month", start=None, end=None, metrics=None):
    end_date = end or timezone.localdate()
    start_date = start or _default_start(project, end_date)
    periods = build_periods(start_date, end_date, granularity)
    metrics = _normalize_metrics(metrics)

    version = getattr(project, "current_wbs_version", None)
    cache_key = (
        f"kpi:timeline:v1:{project.id}:{granularity}:{start_date}:{end_date}:"
        f"{','.join(metrics)}:{version}"
    )
    cached = cache.get(cache_key)
    if cached:
        return cached

    series = []
    for period in periods:
        snapshot = compute_project_kpi(
            project.id, as_of_date=period.end, include_submitted=False
        )
        quality = snapshot.get("data_quality", {})
        labor_quality = snapshot.get("labor", {}).get("data_quality")
        is_closed, quality_label = _quality_label(
            quality,
            labor_quality,
            period.end,
            legal_entity=project.legal_entity,
        )
        series.append(
            {
                "period_key": period.key,
                "period_start": period.start.isoformat(),
                "period_end": period.end.isoformat(),
                "is_closed": is_closed,
                "data_quality": quality_label,
                "metrics": _calc_metrics(snapshot, metrics),
            }
        )

    payload = {
        "project_id": project.id,
        "granularity": granularity,
        "start": start_date.isoformat(),
        "end": end_date.isoformat(),
        "series": series,
        "meta": {
            "metric_definitions": _metric_definitions(),
            "generated_at": timezone.now().isoformat(),
        },
    }

    ttl = 900
    if series and all(point["is_closed"] for point in series):
        ttl = 86400
    cache.set(cache_key, payload, ttl)
    return payload
