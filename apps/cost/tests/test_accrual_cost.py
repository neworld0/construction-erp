from decimal import Decimal

import pytest

from apps.cost.models import CostActual, CostActualLine, CostActualStatus, CostItem
from apps.cost.services.accrual_cost import (
    get_accrual_cost_by_project,
    get_accrual_cost_by_snapshot,
)
from apps.projects.models import Project


@pytest.fixture
def project(db):
    return Project.objects.create(code="PRJ-AC-001", name="Accrual Project")


@pytest.fixture
def cost_items(db):
    return {
        "labor": CostItem.objects.create(
            code="COST-AC-LAB",
            name="Labor",
            category="labor",
            unit="hour",
            is_direct=True,
            sort_order=1,
            is_active=True,
        ),
        "material": CostItem.objects.create(
            code="COST-AC-MAT",
            name="Material",
            category="material",
            unit="kg",
            is_direct=True,
            sort_order=2,
            is_active=True,
        ),
        "equip": CostItem.objects.create(
            code="COST-AC-EQP",
            name="Equipment",
            category="equip",
            unit="day",
            is_direct=True,
            sort_order=3,
            is_active=True,
        ),
    }


def _create_cost_actual(project, status, lines):
    cost_actual = CostActual.objects.create(
        project=project,
        report_date="2024-01-01",
        status=status,
    )
    for line in lines:
        CostActualLine.objects.create(
            cost_actual=cost_actual,
            cost_item=line["cost_item"],
            quantity=line["quantity"],
            unit_price=line["unit_price"],
        )
    return cost_actual


def test_draft_cost_actual_excluded(project, cost_items):
    _create_cost_actual(
        project,
        CostActualStatus.DRAFT,
        [{"cost_item": cost_items["labor"], "quantity": 1, "unit_price": 100}],
    )
    _create_cost_actual(
        project,
        CostActualStatus.APPROVED,
        [{"cost_item": cost_items["labor"], "quantity": 2, "unit_price": 100}],
    )

    summary = get_accrual_cost_by_project(project)

    assert summary["total_cost"] == Decimal("200")


def test_approved_cost_actual_included(project, cost_items):
    _create_cost_actual(
        project,
        CostActualStatus.APPROVED,
        [{"cost_item": cost_items["material"], "quantity": 3, "unit_price": 50}],
    )

    summary = get_accrual_cost_by_project(project)

    assert summary["total_cost"] == Decimal("150")


def test_closed_cost_actual_included(project, cost_items):
    _create_cost_actual(
        project,
        CostActualStatus.CLOSED,
        [{"cost_item": cost_items["equip"], "quantity": 1, "unit_price": 75}],
    )

    summary = get_accrual_cost_by_project(project)

    assert summary["total_cost"] == Decimal("75")


def test_category_totals(project, cost_items):
    _create_cost_actual(
        project,
        CostActualStatus.APPROVED,
        [
            {"cost_item": cost_items["labor"], "quantity": 2, "unit_price": 100},
            {"cost_item": cost_items["material"], "quantity": 1, "unit_price": 40},
            {"cost_item": cost_items["equip"], "quantity": 3, "unit_price": 10},
        ],
    )

    summary = get_accrual_cost_by_project(project)

    assert summary["by_category"]["LABOR"] == Decimal("200")
    assert summary["by_category"]["MATERIAL"] == Decimal("40")
    assert summary["by_category"]["EQUIP"] == Decimal("30")


def test_snapshot_and_project_match(project, cost_items):
    dummy_snapshot = object()
    project.active_contract_snapshot = dummy_snapshot

    _create_cost_actual(
        project,
        CostActualStatus.APPROVED,
        [{"cost_item": cost_items["labor"], "quantity": 2, "unit_price": 100}],
    )
    _create_cost_actual(
        project,
        CostActualStatus.CLOSED,
        [{"cost_item": cost_items["material"], "quantity": 1, "unit_price": 40}],
    )

    by_project = get_accrual_cost_by_project(project)
    by_snapshot = get_accrual_cost_by_snapshot(dummy_snapshot)

    assert by_project["total_cost"] == by_snapshot["total_cost"]
    assert by_project["by_category"] == by_snapshot["by_category"]
