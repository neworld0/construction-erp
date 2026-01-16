from decimal import Decimal
from typing import Optional

from django.db import models

from apps.cost.models import RevenueRecognition, _get_active_snapshot
from apps.cost.services.accrual_cost import (
    get_accrual_cost_by_project,
    get_accrual_cost_by_snapshot,
)
from apps.projects.models import Project


def _empty_result(project_id=None, snapshot_id=None):
    return {
        "snapshot_id": snapshot_id,
        "project_id": project_id,
        "as_of_date": None,
        "recognized_revenue": Decimal("0"),
        "accrual_cost": Decimal("0"),
        "profit": Decimal("0"),
        "margin_percent": Decimal("0"),
        "cost_by_category": {},
    }


def _get_snapshot_record(snapshot_id):
    snapshot_field = RevenueRecognition._meta.get_field("contract_snapshot")
    if isinstance(snapshot_field, models.ForeignKey):
        return snapshot_field.remote_field.model.objects.filter(id=snapshot_id).first()
    return None


def _latest_revenue_record(project_id=None, snapshot_id=None, snapshot=None):
    queryset = RevenueRecognition.objects.all()
    snapshot_field = RevenueRecognition._meta.get_field("contract_snapshot")

    if snapshot_id is not None:
        if isinstance(snapshot_field, models.ForeignKey):
            queryset = queryset.filter(contract_snapshot_id=snapshot_id)
        else:
            queryset = queryset.filter(contract_snapshot=snapshot_id)
    if snapshot is not None and isinstance(snapshot_field, models.ForeignKey):
        queryset = queryset.filter(contract_snapshot=snapshot)
    if project_id is not None:
        queryset = queryset.filter(project_id=project_id)

    return queryset.order_by("-as_of_date", "-id").first()


def _calculate_margin(revenue, profit):
    if revenue and revenue > 0:
        return (profit / revenue) * Decimal("100")
    return Decimal("0")


def get_profit_loss_by_snapshot(snapshot_id):
    snapshot = _get_snapshot_record(snapshot_id)
    latest = _latest_revenue_record(snapshot_id=snapshot_id, snapshot=snapshot)

    project_id = latest.project_id if latest else None
    accrual = get_accrual_cost_by_snapshot(snapshot) if snapshot is not None else _empty_cost()
    revenue = latest.recognized_revenue if latest else Decimal("0")
    profit = revenue - accrual["total_cost"]
    margin = _calculate_margin(revenue, profit)

    return {
        "snapshot_id": snapshot_id,
        "project_id": project_id,
        "as_of_date": latest.as_of_date if latest else None,
        "recognized_revenue": revenue,
        "accrual_cost": accrual["total_cost"],
        "profit": profit,
        "margin_percent": margin,
        "cost_by_category": accrual["by_category"],
    }


def get_profit_loss_by_project(project_id):
    project = Project.objects.filter(id=project_id).first()
    if project is None:
        return _empty_result(project_id=project_id)

    snapshot = _get_active_snapshot(project)
    snapshot_id = getattr(snapshot, "id", None) if snapshot else None

    latest = _latest_revenue_record(
        project_id=project.id,
        snapshot_id=snapshot_id,
        snapshot=snapshot,
    )
    accrual = (
        get_accrual_cost_by_project(project)
        if project is not None
        else _empty_cost()
    )
    revenue = latest.recognized_revenue if latest else Decimal("0")
    profit = revenue - accrual["total_cost"]
    margin = _calculate_margin(revenue, profit)

    return {
        "snapshot_id": snapshot_id,
        "project_id": project.id,
        "as_of_date": latest.as_of_date if latest else None,
        "recognized_revenue": revenue,
        "accrual_cost": accrual["total_cost"],
        "profit": profit,
        "margin_percent": margin,
        "cost_by_category": accrual["by_category"],
    }


def _empty_cost():
    return {"total_cost": Decimal("0"), "by_category": {}}
