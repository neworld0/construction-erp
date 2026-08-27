from decimal import Decimal

import pytest

from apps.cost.models import CostActual, CostActualLine, CostActualStatus, CostItem, CostVATTreatment
from apps.cost.services.accrual_cost import get_accrual_cost_by_project
from apps.projects.models import Project


@pytest.mark.django_db
def test_deductible_vat_cost_keeps_gross_input_but_uses_supply_amount_for_profit():
    project = Project.objects.create(code="VAT-COST-01", name="VAT 원가 검증")
    item = CostItem.objects.create(code="VAT-MAT-01", name="아스콘", category="MATERIAL")
    actual = CostActual.objects.create(project=project, report_date="2026-08-20", status=CostActualStatus.APPROVED)
    line = CostActualLine.objects.create(
        cost_actual=actual,
        cost_item=item,
        quantity=Decimal("1"),
        unit_price=Decimal("110000"),
        vat_treatment=CostVATTreatment.DEDUCTIBLE,
    )

    line.refresh_from_db()
    assert line.amount == Decimal("110000.00")
    assert line.supply_amount == Decimal("100000.00")
    assert line.vat_amount == Decimal("10000.00")
    assert line.accounting_cost_amount == Decimal("100000.00")
    assert get_accrual_cost_by_project(project)["total_cost"] == Decimal("100000.00")


@pytest.mark.django_db
def test_non_vat_labor_cost_is_not_converted():
    project = Project.objects.create(code="VAT-COST-02", name="노무비 검증")
    item = CostItem.objects.create(code="VAT-LAB-01", name="개인 노무비", category="LABOR")
    actual = CostActual.objects.create(project=project, report_date="2026-08-20", status=CostActualStatus.APPROVED)
    line = CostActualLine.objects.create(
        cost_actual=actual,
        cost_item=item,
        quantity=Decimal("1"),
        unit_price=Decimal("100000"),
        vat_treatment=CostVATTreatment.EXEMPT,
    )

    assert line.amount == Decimal("100000.00")
    assert line.vat_amount == Decimal("0")
    assert line.accounting_cost_amount == Decimal("100000.00")
