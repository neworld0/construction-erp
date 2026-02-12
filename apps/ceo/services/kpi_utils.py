from __future__ import annotations

import calendar
from dataclasses import dataclass
from datetime import date, timedelta
from decimal import Decimal
from typing import Optional


@dataclass(frozen=True)
class TrendResult:
    current: Optional[Decimal]
    previous: Optional[Decimal]
    delta: Optional[Decimal]
    delta_pct: Optional[Decimal]
    trend: str
    has_data: bool


def previous_month_equivalent(base_date: date) -> date:
    year = base_date.year
    month = base_date.month - 1
    if month == 0:
        month = 12
        year -= 1
    last_day = calendar.monthrange(year, month)[1]
    day = min(base_date.day, last_day)
    return date(year, month, day)


def compare_windows(base_date: date, compare_mode: str) -> tuple[date, date, date, date]:
    mode = (compare_mode or "month").lower()
    if mode == "week":
        current_end = base_date
        current_start = base_date - timedelta(days=6)
        previous_end = base_date - timedelta(days=7)
        previous_start = previous_end - timedelta(days=6)
        return current_start, current_end, previous_start, previous_end

    current_end = base_date
    current_start = base_date.replace(day=1)
    previous_end = previous_month_equivalent(base_date)
    previous_start = previous_end.replace(day=1)
    return current_start, current_end, previous_start, previous_end


def build_trend(
    current: Optional[Decimal],
    previous: Optional[Decimal] = None,
) -> TrendResult:
    if current is None or previous is None:
        return TrendResult(
            current=current,
            previous=previous,
            delta=None,
            delta_pct=None,
            trend="flat",
            has_data=False,
        )

    delta = current - previous
    if delta > 0:
        trend = "up"
    elif delta < 0:
        trend = "down"
    else:
        trend = "flat"

    denom = abs(previous)
    if denom == 0:
        delta_pct = None
    else:
        delta_pct = (delta / denom) * Decimal("100")

    return TrendResult(
        current=current,
        previous=previous,
        delta=delta,
        delta_pct=delta_pct,
        trend=trend,
        has_data=True,
    )


def project_elapsed_percent(project, base_date: date) -> Optional[Decimal]:
    contract = getattr(project, "contract", None)
    start = None
    end = None
    if contract is not None:
        start = getattr(contract, "start_date", None) or getattr(contract, "contract_start_date", None)
        end = getattr(contract, "end_date", None) or getattr(contract, "contract_end_date", None)
    start = start or getattr(project, "start_date", None)
    end = end or getattr(project, "end_date", None)

    if not start or not end or end <= start:
        return None

    total_days = (end - start).days
    elapsed_days = (base_date - start).days
    if elapsed_days <= 0:
        return Decimal("0")
    if elapsed_days >= total_days:
        return Decimal("100")
    ratio = Decimal(elapsed_days) / Decimal(total_days)
    return ratio * Decimal("100")


def schedule_status(avg_progress: Decimal, elapsed_percent: Optional[Decimal]) -> dict:
    if elapsed_percent is None:
        return {
            "elapsed_percent": None,
            "gap_percent": None,
            "status_code": "UNKNOWN",
            "status_label": "-",
            "status_emoji": "",
            "status_class": "quality-unknown",
        }

    gap = avg_progress - elapsed_percent
    if gap <= Decimal("-15"):
        return {
            "elapsed_percent": elapsed_percent,
            "gap_percent": gap,
            "status_code": "RISK",
            "status_label": "\uC704\uD5D8",
            "status_emoji": "🔴",
            "status_class": "quality-estimated",
        }
    if gap < Decimal("-5"):
        return {
            "elapsed_percent": elapsed_percent,
            "gap_percent": gap,
            "status_code": "DELAY",
            "status_label": "\uC9C0\uC5F0",
            "status_emoji": "🟠",
            "status_class": "quality-unknown",
        }
    return {
        "elapsed_percent": elapsed_percent,
        "gap_percent": gap,
        "status_code": "NORMAL",
        "status_label": "\uC815\uC0C1",
        "status_emoji": "🟢",
        "status_class": "quality-ok",
    }
