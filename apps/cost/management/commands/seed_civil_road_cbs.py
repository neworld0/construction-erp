from django.core.management.base import BaseCommand

from apps.cost.seed_civil_road_cbs import seed_civil_road_cbs


class Command(BaseCommand):
    help = "Seed minimum road/civil CBS master items and aliases for contract budget import."

    def handle(self, *args, **options):
        summary = seed_civil_road_cbs()
        self.stdout.write(
            "seed_civil_road_cbs done: "
            f"cost_items_created={summary['cost_items_created']} "
            f"cost_items_updated={summary['cost_items_updated']} "
            f"aliases_created={summary['aliases_created']} "
            f"aliases_existing={summary['aliases_existing']}"
        )
        self.stdout.write("도로/토목 CBS seed가 완료되었습니다.")
