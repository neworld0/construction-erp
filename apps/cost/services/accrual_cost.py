from decimal import Decimal
from typing import Optional

from django.db.models import Sum

from apps.cost.models import CostActual, CostActualLine, CostActualStatus, CostItemCategory


def _get_active_snapshot(project):
    if project is None:
        return None

    for attr in ("active_contract_snapshot", "contract_snapshot", "current_snapshot"):
        snapshot = getattr(project, attr, None)
        if snapshot:
            return snapshot

    for related_name in ("contract_snapshots", "contractsnapshot_set", "contract_snapshots_set"):
        manager = getattr(project, related_name, None)
        if manager is None:
            continue
        try:
            return manager.filter(is_active=True).first()
        except Exception:
            continue

    return None


def _apply_snapshot_filter(queryset, snapshot):
    if snapshot is None:
        return queryset

    if hasattr(CostActual, "contract_snapshot"):
        return queryset.filter(contract_snapshot=snapshot)

    return queryset


def _empty_summary():
    return {
        "total_cost": Decimal("0"),
        "by_category": {choice.value.upper(): Decimal("0") for choice in CostItemCategory},
    }


def _build_summary(lines_queryset):
    summary = _empty_summary()
    total = lines_queryset.aggregate(total=Sum("amount"))["total"] or Decimal("0")
    summary["total_cost"] = total

    by_category = (
        lines_queryset.values("cost_item__category")
        .annotate(total=Sum("amount"))
        .order_by()
    )
    for row in by_category:
        category = (row["cost_item__category"] or "").upper()
        summary["by_category"][category] = row["total"] or Decimal("0")
    return summary


def get_accrual_cost_by_snapshot(snapshot):
    # Change Order 승인 후 Snapshot 기준 전환
    queryset = CostActual.objects.filter(
        status__in=[CostActualStatus.APPROVED, CostActualStatus.CLOSED]
    )
    queryset = _apply_snapshot_filter(queryset, snapshot)
    lines = CostActualLine.objects.filter(cost_actual__in=queryset)
    return _build_summary(lines)


def get_accrual_cost_by_project(project):
    # 과거 Snapshot 소급 금지 (Risk Engine 연계)
    snapshot = _get_active_snapshot(project)
    queryset = CostActual.objects.filter(
        project=project,
        status__in=[CostActualStatus.APPROVED, CostActualStatus.CLOSED],
    )
    queryset = _apply_snapshot_filter(queryset, snapshot)
    lines = CostActualLine.objects.filter(cost_actual__in=queryset)
    return _build_summary(lines)
