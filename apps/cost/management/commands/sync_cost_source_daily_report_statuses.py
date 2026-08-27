from django.core.management.base import BaseCommand
from django.db import transaction

from apps.audit.services.logger import log_action
from apps.cost.models import CostActual, CostActualStatus
from apps.field.models import DailyReportStatus


class Command(BaseCommand):
    help = (
        "Synchronize legacy DailyReport statuses from their linked CostActual "
        "without changing financial values. Defaults to a dry run."
    )

    def add_arguments(self, parser):
        parser.add_argument(
            "--apply",
            action="store_true",
            help="Apply the status repair and create one audit record per repaired source report.",
        )

    def handle(self, *args, **options):
        target_statuses = {
            CostActualStatus.APPROVED: DailyReportStatus.APPROVED,
            CostActualStatus.REJECTED: DailyReportStatus.REJECTED,
        }
        candidates = list(
            CostActual.objects.select_related("project", "source_daily_report")
            .exclude(source_daily_report__isnull=True)
            .filter(status__in=target_statuses)
            .order_by("id")
        )
        repairs = [
            cost
            for cost in candidates
            if cost.source_daily_report.status != target_statuses[cost.status]
        ]
        self.stdout.write(f"candidates={len(candidates)} repairs={len(repairs)}")
        for cost in repairs:
            self.stdout.write(
                f"cost={cost.id} project={cost.project_id} "
                f"{cost.source_daily_report.status}->{target_statuses[cost.status]}"
            )

        if not options["apply"]:
            self.stdout.write(self.style.WARNING("Dry run only. Re-run with --apply to repair."))
            return

        with transaction.atomic():
            for cost in repairs:
                report = cost.source_daily_report
                before_status = report.status
                report.status = target_statuses[cost.status]
                report.save(update_fields=["status", "updated_at"])
                log_action(
                    actor=None,
                    action="COST_SOURCE_DAILY_REPORT_STATUS_SYNC",
                    object_type="DailyReport",
                    object_id=report.id,
                    project=cost.project,
                    before={"status": before_status},
                    after={"status": report.status},
                    meta={"cost_actual_id": cost.id, "source": "management_command"},
                )
        self.stdout.write(self.style.SUCCESS(f"repaired={len(repairs)}"))
