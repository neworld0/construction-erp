from decimal import Decimal, ROUND_HALF_UP

from django.contrib.auth import get_user_model
from django.core.management.base import BaseCommand, CommandError
from django.db import transaction

from apps.audit.services.logger import log_action
from apps.cost.models import RevenueRecognition, RevenueRecognitionClose
from apps.projects.models import Project


VAT_DIVISOR = Decimal("1.10")
MONEY = Decimal("0.01")
AUDIT_ACTION = "VAT_INCLUSIVE_REVENUE_NORMALIZED"


def _net(amount):
    return (Decimal(amount) / VAT_DIVISOR).quantize(MONEY, rounding=ROUND_HALF_UP)


def _audit_amounts(values):
    """Audit JSON must use primitive values; retain exact money as text."""
    return {key: f"{value:.2f}" for key, value in values.items()}


class Command(BaseCommand):
    help = (
        "Convert one project's legacy revenue-recognition snapshots from VAT-inclusive "
        "to VAT-exclusive values. A dry run is the default."
    )

    def add_arguments(self, parser):
        parser.add_argument("--project-id", type=int, required=True)
        parser.add_argument("--actor-username", required=True)
        parser.add_argument(
            "--apply",
            action="store_true",
            help="Persist the conversion. Without this option only the proposed values are displayed.",
        )

    def handle(self, *args, **options):
        try:
            project = Project.objects.get(pk=options["project_id"])
        except Project.DoesNotExist as exc:
            raise CommandError("대상 프로젝트를 찾을 수 없습니다.") from exc

        try:
            actor = get_user_model().objects.get(username=options["actor_username"])
        except get_user_model().DoesNotExist as exc:
            raise CommandError("감사 이력에 기록할 사용자를 찾을 수 없습니다.") from exc

        existing_audit = project.audit_logs.filter(action=AUDIT_ACTION).exists()
        if existing_audit:
            raise CommandError("이 프로젝트의 VAT 매출 정정은 이미 실행되었습니다. 중복 실행하지 않습니다.")

        recognitions = list(
            RevenueRecognition.objects.filter(project=project)
            .order_by("as_of_date", "id")
        )
        if not recognitions:
            raise CommandError("정정할 매출 인식 스냅샷이 없습니다.")

        previous = Decimal("0")
        plan = []
        for recognition in recognitions:
            recognized = _net(recognition.recognized_revenue)
            delta = recognized - previous
            plan.append((recognition, recognized, delta))
            previous = recognized

        self.stdout.write(f"프로젝트: {project.code} / {project.name}")
        for recognition, recognized, delta in plan:
            self.stdout.write(
                f"- 매출 인식 #{recognition.pk} {recognition.as_of_date}: "
                f"{recognition.recognized_revenue:,.2f} → {recognized:,.2f}, "
                f"증감 {recognition.delta_revenue:,.2f} → {delta:,.2f}"
            )

        if not options["apply"]:
            self.stdout.write(self.style.WARNING("검증만 완료했습니다. 저장하려면 --apply 옵션을 사용하세요."))
            return

        with transaction.atomic():
            locked_recognitions = {
                record.pk: record
                for record in RevenueRecognition.objects.select_for_update()
                .filter(pk__in=[recognition.pk for recognition, _, _ in plan])
            }
            close_by_recognition_id = {
                close.revenue_recognition_id: close
                for close in RevenueRecognitionClose.objects.select_for_update()
                .filter(project=project, revenue_recognition_id__in=locked_recognitions)
            }

            for original, recognized, delta in plan:
                recognition = locked_recognitions[original.pk]
                before = _audit_amounts({
                    "recognized_revenue": recognition.recognized_revenue,
                    "delta_revenue": recognition.delta_revenue,
                })
                RevenueRecognition.objects.filter(pk=recognition.pk).update(
                    recognized_revenue=recognized,
                    delta_revenue=delta,
                )
                log_action(
                    actor=actor,
                    action=AUDIT_ACTION,
                    object_type="RevenueRecognition",
                    object_id=recognition.pk,
                    project=project,
                    before=before,
                    after=_audit_amounts({"recognized_revenue": recognized, "delta_revenue": delta}),
                    meta={"basis": "legacy contract/project amount was VAT-inclusive", "vat_rate": "10%"},
                )

                close = close_by_recognition_id.get(recognition.pk)
                if close is None:
                    continue
                previous_amount = recognized - delta
                close_before = _audit_amounts({
                    "contract_amount_snapshot": close.contract_amount_snapshot,
                    "cumulative_earned_revenue": close.cumulative_earned_revenue,
                    "previously_recognized_revenue": close.previously_recognized_revenue,
                    "recognized_revenue_amount": close.recognized_revenue_amount,
                })
                close_after = {
                    "contract_amount_snapshot": _net(close.contract_amount_snapshot),
                    "cumulative_earned_revenue": recognized,
                    "previously_recognized_revenue": previous_amount,
                    "recognized_revenue_amount": delta,
                }
                # These snapshots are immutable through model.save(). This command is the
                # approved, audited correction path for legacy VAT-inclusive snapshots.
                RevenueRecognitionClose.objects.filter(pk=close.pk).update(**close_after)
                log_action(
                    actor=actor,
                    action=AUDIT_ACTION,
                    object_type="RevenueRecognitionClose",
                    object_id=close.pk,
                    project=project,
                    before=close_before,
                    after=_audit_amounts(close_after),
                    meta={"basis": "legacy contract/project amount was VAT-inclusive", "vat_rate": "10%"},
                )

        self.stdout.write(self.style.SUCCESS("VAT 별도 매출 스냅샷 정정과 감사 이력 기록을 완료했습니다."))
