from django.core.management.base import BaseCommand
from django.db import transaction

from apps.labor.rate_master import seed_local_ops_labor_rates


class Command(BaseCommand):
    help = "Seed the canonical LOCAL-OPS global daily LaborRole rates idempotently."

    def add_arguments(self, parser):
        parser.add_argument("--dry-run", action="store_true")

    def handle(self, *args, **options):
        with transaction.atomic():
            result = seed_local_ops_labor_rates()
            if options["dry_run"]:
                transaction.set_rollback(True)

        for outcome in ("created", "updated", "unchanged"):
            rates = result[outcome]
            names = ", ".join(rate.labor_role.name for rate in rates) or "-"
            self.stdout.write(f"{outcome}: {len(rates)} ({names})")
        if options["dry_run"]:
            self.stdout.write(self.style.WARNING("Dry run: no changes were saved."))
