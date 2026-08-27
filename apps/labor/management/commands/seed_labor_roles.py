from django.core.management.base import BaseCommand
from django.db import transaction

from apps.labor.role_master import seed_local_ops_labor_roles


class Command(BaseCommand):
    help = "Seed the canonical LOCAL-OPS LaborRole master entries idempotently."

    def add_arguments(self, parser):
        parser.add_argument("--dry-run", action="store_true")

    def handle(self, *args, **options):
        with transaction.atomic():
            result = seed_local_ops_labor_roles()
            if options["dry_run"]:
                transaction.set_rollback(True)

        for outcome in ("created", "updated", "unchanged"):
            roles = result[outcome]
            codes = ", ".join(role.code for role in roles) or "-"
            self.stdout.write(f"{outcome}: {len(roles)} ({codes})")
        if options["dry_run"]:
            self.stdout.write(self.style.WARNING("Dry run: no changes were saved."))
