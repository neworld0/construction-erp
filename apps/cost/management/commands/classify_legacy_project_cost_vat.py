from decimal import Decimal, ROUND_HALF_UP

from django.contrib.auth import get_user_model
from django.core.management.base import BaseCommand, CommandError
from django.db import transaction

from apps.audit.services.logger import log_action
from apps.cost.models import CostActualLine, CostVATTreatment
from apps.projects.models import Project


VAT_DIVISOR = Decimal("1.10")
MONEY = Decimal("0.01")
AUDIT_ACTION = "LEGACY_COST_VAT_CLASSIFIED"


def _as_audit(values):
    return {key: f"{value:.2f}" if isinstance(value, Decimal) else value for key, value in values.items()}


class Command(BaseCommand):
    help = "Classify a project's legacy cost lines using the approved VAT policy. Dry run is the default."

    def add_arguments(self, parser):
        parser.add_argument("--project-id", type=int, required=True)
        parser.add_argument("--actor-username", required=True)
        parser.add_argument("--apply", action="store_true")

    def handle(self, *args, **options):
        try:
            project = Project.objects.get(pk=options["project_id"])
            actor = get_user_model().objects.get(username=options["actor_username"])
        except Project.DoesNotExist as exc:
            raise CommandError("대상 프로젝트를 찾을 수 없습니다.") from exc
        except get_user_model().DoesNotExist as exc:
            raise CommandError("감사 이력에 기록할 사용자를 찾을 수 없습니다.") from exc

        lines = list(
            CostActualLine.objects.filter(
                cost_actual__project=project,
                vat_treatment=CostVATTreatment.LEGACY_UNCLASSIFIED,
            ).select_related("cost_item").order_by("id")
        )
        if not lines:
            raise CommandError("정정할 기존 VAT 미분류 원가가 없습니다.")

        plan = []
        for line in lines:
            is_labor = (line.cost_item.category or "").upper() == "LABOR"
            treatment = CostVATTreatment.EXEMPT if is_labor else CostVATTreatment.DEDUCTIBLE
            gross = Decimal(line.amount)
            supply = gross if is_labor else (gross / VAT_DIVISOR).quantize(MONEY, rounding=ROUND_HALF_UP)
            vat = Decimal("0") if is_labor else gross - supply
            plan.append((line, treatment, supply, vat))
            self.stdout.write(
                f"#{line.pk} {line.cost_item.code}: {gross:,.2f} → 손익원가 {supply:,.2f} / VAT {vat:,.2f}"
            )

        if not options["apply"]:
            self.stdout.write(self.style.WARNING("검증만 완료했습니다. 저장하려면 --apply 옵션을 사용하세요."))
            return

        with transaction.atomic():
            locked = {
                line.pk: line
                for line in CostActualLine.objects.select_for_update().filter(pk__in=[line.pk for line, *_ in plan])
            }
            for original, treatment, supply, vat in plan:
                line = locked[original.pk]
                before = _as_audit({
                    "vat_treatment": line.vat_treatment,
                    "supply_amount": Decimal(line.supply_amount),
                    "vat_amount": Decimal(line.vat_amount),
                    "accounting_cost_amount": Decimal(line.accounting_cost_amount),
                })
                after = {
                    "vat_treatment": treatment,
                    "supply_amount": supply,
                    "vat_amount": vat,
                    "accounting_cost_amount": supply,
                }
                CostActualLine.objects.filter(pk=line.pk).update(**after)
                log_action(
                    actor=actor,
                    action=AUDIT_ACTION,
                    object_type="CostActualLine",
                    object_id=line.pk,
                    project=project,
                    before=before,
                    after=_as_audit(after),
                    meta={"basis": "project VAT policy: labor unchanged, all other legacy cost gross amounts treated as deductible VAT", "vat_rate": "10%"},
                )

        self.stdout.write(self.style.SUCCESS("기존 원가 VAT 분류·손익 원가 정정과 감사 이력 기록을 완료했습니다."))
