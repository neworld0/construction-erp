from django.core.management.base import BaseCommand, CommandError

from apps.projects.models import BudgetItem, Project


OWNER_SUPPLIED_MARKERS = ("관급", "관급자재", "아스콘(관급)")


class Command(BaseCommand):
    help = "Identify owner-supplied budget items imported into project budget baseline."

    def add_arguments(self, parser):
        parser.add_argument("--project-id", type=int, required=True)
        parser.add_argument("--apply", action="store_true")

    def handle(self, *args, **options):
        project = Project.objects.filter(id=options["project_id"]).first()
        if project is None:
            raise CommandError(f"Project {options['project_id']} not found.")

        candidates = []
        for item in BudgetItem.objects.filter(project=project).select_related("cost_item").order_by("id"):
            note = item.note or ""
            if any(marker in note for marker in OWNER_SUPPLIED_MARKERS):
                candidates.append(item)

        if not candidates:
            self.stdout.write("No owner-supplied budget candidates found.")
            return

        self.stdout.write("Owner-supplied budget candidates:")
        for item in candidates:
            self.stdout.write(f"- BudgetItem #{item.id}")
            self.stdout.write(f"  CBS: {item.cost_item.code} - {item.cost_item.name}")
            self.stdout.write(f"  Amount: {item.planned_amount}")
            self.stdout.write(f"  Note: {item.note}")
            self.stdout.write("  Recommendation: re-import after owner-supplied exclusion patch or manually adjust amount.")

        if not options["apply"]:
            self.stdout.write("Dry-run only. Use --apply to attempt safe cleanup.")
            return

        self.stdout.write("Apply mode is conservative. Mixed aggregated rows are left unchanged to avoid blind deletion.")
