from collections import defaultdict

from django.core.management.base import BaseCommand, CommandError
from django.db import transaction

from apps.cost.models import CostItem
from apps.projects.models import BudgetCategory, BudgetItem, Project


FORCED_EXPENSE_TERMS = (
    "간접노무비",
    "산재보험료",
    "고용보험료",
    "건강보험료",
    "연금보험료",
    "노인장기요양보험료",
    "퇴직공제부금비",
    "건설기계대여금지급보증서발급액",
    "건설기계대여금지급보증 발급액",
    "산업안전보건관리비",
    "환경보전비",
    "환경보건비",
    "하도급대금지급보증수수료",
    "보험료",
    "수수료",
    "지급보증",
    "발급액",
)


def _pick_cost_item(*codes, category=None, name=None):
    for code in codes:
        if not code:
            continue
        item = CostItem.objects.filter(code=code, is_active=True).first()
        if item:
            return item
    if name:
        item = CostItem.objects.filter(name=name, is_active=True).first()
        if item:
            return item
    if category:
        return CostItem.objects.filter(category=category, is_active=True).order_by("sort_order", "id").first()
    return None


def _merge_notes(*notes):
    merged = []
    seen = set()
    for note in notes:
        text = (note or "").strip()
        if not text or text in seen:
            continue
        seen.add(text)
        merged.append(text)
    return "\n".join(merged)


def _collect_totals(project):
    totals = defaultdict(int)
    for item in BudgetItem.objects.filter(project=project).select_related("cost_item"):
        key = f"{item.cost_item.code} - {item.cost_item.name}"
        totals[key] += int(item.planned_amount or 0)
    return dict(sorted(totals.items()))


def _looks_like_forced_expense(item):
    text = f"{item.name} {item.note}".strip()
    return any(term in text for term in FORCED_EXPENSE_TERMS)


class Command(BaseCommand):
    help = "Repair project budget CBS grouping for labor/expense/profit rows."

    def add_arguments(self, parser):
        parser.add_argument("--project-id", type=int, required=True)

    def handle(self, *args, **options):
        project_id = options["project_id"]
        project = Project.objects.filter(id=project_id).first()
        if project is None:
            raise CommandError(f"Project {project_id} not found.")

        labor_item = _pick_cost_item("LABOR-GENERAL", "CIVIL-LABOR", category="labor")
        expense_item = _pick_cost_item("CIVIL-EXPENSE", name="경비", category="other")
        profit_item = _pick_cost_item("CIVIL-PROFIT")
        if labor_item is None or expense_item is None or profit_item is None:
            raise CommandError("Required CBS master data is missing. Run seed_civil_road_cbs first.")

        before_totals = _collect_totals(project)

        with transaction.atomic():
            items = list(BudgetItem.objects.filter(project=project).select_related("cost_item").order_by("id"))
            for item in items:
                target_item = None
                target_category = item.category
                target_name = item.name or item.cost_item.name

                if item.cost_item_id == profit_item.id and "안전관리책임자" in (item.note or ""):
                    target_item = labor_item
                    target_category = BudgetCategory.LABOR
                    target_name = labor_item.name
                elif _looks_like_forced_expense(item):
                    target_item = expense_item
                    target_category = BudgetCategory.OTHER
                    target_name = "경비"

                if target_item is None:
                    continue

                existing = (
                    BudgetItem.objects.filter(project=project, cost_item=target_item)
                    .exclude(id=item.id)
                    .first()
                )
                if existing:
                    existing.planned_amount = int(existing.planned_amount or 0) + int(item.planned_amount or 0)
                    existing.category = target_category
                    existing.name = target_name
                    existing.note = _merge_notes(existing.note, item.note)
                    existing.save(update_fields=["planned_amount", "category", "name", "note", "updated_at"])
                    item.delete()
                    continue

                item.cost_item = target_item
                item.category = target_category
                item.name = target_name
                item.note = _merge_notes(item.note)
                item.save(update_fields=["cost_item", "category", "name", "note", "updated_at"])

        after_totals = _collect_totals(project)

        self.stdout.write("Before totals:")
        for label, amount in before_totals.items():
            self.stdout.write(f"  {label}: {amount}")
        self.stdout.write("After totals:")
        for label, amount in after_totals.items():
            self.stdout.write(f"  {label}: {amount}")
        self.stdout.write(self.style.SUCCESS(f"Project {project_id} budget CBS repair completed."))
