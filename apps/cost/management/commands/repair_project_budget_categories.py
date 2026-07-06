from decimal import Decimal

from django.core.management.base import BaseCommand, CommandError
from django.db import transaction
from django.db.models import Sum

from apps.projects.hq_views import _canonical_budget_category_for_cost_item
from apps.projects.models import BudgetCategory, BudgetItem, Project, ProjectContract


def _project_totals(project):
    queryset = BudgetItem.objects.filter(project=project)
    material_total = (
        queryset.filter(category=BudgetCategory.MATERIAL)
        .aggregate(total=Sum("planned_amount"))
        .get("total")
        or Decimal("0")
    )
    subcontract_total = (
        queryset.filter(category=BudgetCategory.SUBCON)
        .aggregate(total=Sum("planned_amount"))
        .get("total")
        or Decimal("0")
    )
    labor_total = (
        queryset.filter(category=BudgetCategory.LABOR)
        .exclude(cost_item__code="CIVIL-PROFIT")
        .aggregate(total=Sum("planned_amount"))
        .get("total")
        or Decimal("0")
    )
    expense_total = (
        queryset.exclude(
            category__in=[
                BudgetCategory.MATERIAL,
                BudgetCategory.SUBCON,
                BudgetCategory.LABOR,
            ]
        )
        .aggregate(total=Sum("planned_amount"))
        .get("total")
        or Decimal("0")
    )
    grand_total = material_total + subcontract_total + labor_total + expense_total
    contract = ProjectContract.objects.filter(project=project).first()
    contract_amount = contract.contract_amount if contract else Decimal("0")
    difference = contract_amount - grand_total
    return {
        "material": material_total,
        "subcon": subcontract_total,
        "labor": labor_total,
        "expense": expense_total,
        "grand": grand_total,
        "contract": contract_amount,
        "difference": difference,
    }


class Command(BaseCommand):
    help = "Repair project budget categories to practical baseline categories."

    def add_arguments(self, parser):
        parser.add_argument("--project-id", type=int, required=True)

    def handle(self, *args, **options):
        project = Project.objects.filter(id=options["project_id"]).first()
        if project is None:
            raise CommandError(f"Project {options['project_id']} not found.")

        before = _project_totals(project)

        with transaction.atomic():
            for item in BudgetItem.objects.filter(project=project).select_related("cost_item"):
                desired_category = _canonical_budget_category_for_cost_item(
                    item.cost_item,
                    current_category=item.category,
                )
                desired_name = item.name
                code = (item.cost_item.code or "").upper()
                if code == "CIVIL-PROFIT":
                    desired_category = BudgetCategory.OTHER
                    if not desired_name or desired_name != "이윤":
                        desired_name = "이윤"
                elif code == "CIVIL-EXPENSE":
                    desired_category = BudgetCategory.OTHER
                    if not desired_name or desired_name != "경비":
                        desired_name = "경비"
                elif code == "CIVIL-EQUIPMENT":
                    desired_category = BudgetCategory.OTHER
                elif code in {"LABOR-GENERAL", "CIVIL-LABOR"}:
                    desired_category = BudgetCategory.LABOR

                update_fields = []
                if item.category != desired_category:
                    item.category = desired_category
                    update_fields.append("category")
                if desired_name != item.name:
                    item.name = desired_name
                    update_fields.append("name")
                if update_fields:
                    update_fields.append("updated_at")
                    item.save(update_fields=update_fields)

        after = _project_totals(project)

        self.stdout.write(f"재료비 합계: {before['material']} -> {after['material']}")
        self.stdout.write(f"하도급 합계: {before['subcon']} -> {after['subcon']}")
        self.stdout.write(f"노무비 합계: {before['labor']} -> {after['labor']}")
        self.stdout.write(f"경비 합계: {before['expense']} -> {after['expense']}")
        self.stdout.write(f"총합계: {before['grand']} -> {after['grand']}")
        self.stdout.write(f"계약금액: {after['contract']}")
        self.stdout.write(f"차이: {after['difference']}")
