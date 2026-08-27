from django.core.management.base import BaseCommand

from apps.inventory.models import ItemCategory, ItemMaster, UoM


STANDARD_ITEMS = (
    ("CIV-MAT-SAFETY-SIGN", "안전표지판", "EA", "현장 안전표지"),
    ("CIV-MAT-SAFETY-CONE", "안전콘", "EA", "교통·작업구간 안전콘"),
    ("CIV-MAT-DIESEL", "경유", "L", "장비용 경유"),
    ("CIV-MAT-ASPHALT", "아스콘", "TON", "가열 아스팔트 혼합물"),
    ("CIV-MAT-ROAD-PAINT", "차선도색 페인트", "L", "차선 도색용 페인트"),
    ("CIV-MAT-GLASS-BEAD", "유리알", "KG", "차선 도색용 유리알"),
    ("CIV-MAT-CEMENT", "시멘트", "BAG", "보통 포틀랜드 시멘트"),
    ("CIV-MAT-READY-MIX", "레미콘", "M3", "레디믹스트 콘크리트"),
    ("CIV-MAT-CRUSHED-STONE", "쇄석", "M3", "기층·성토용 쇄석"),
    ("CIV-MAT-SAND", "모래", "M3", "콘크리트·되메우기용 모래"),
    ("CIV-MAT-REBAR", "철근", "KG", "콘크리트 보강 철근"),
    ("CIV-MAT-GEOTEXTILE", "토목섬유", "M2", "분리·보강용 토목섬유"),
    ("CIV-MAT-DRAIN-PIPE", "배수관", "M", "우수·배수용 관"),
    ("CIV-MAT-CURBSTONE", "경계석", "M", "보도·차도 경계석"),
    ("LAND-MAT-BLOCK", "조경블록", "M2", "보도·조경 포장 블록"),
    ("LAND-MAT-TURF", "잔디", "M2", "조경용 잔디"),
    ("LAND-MAT-SEEDLING", "조경수", "EA", "식재용 수목"),
    ("LAND-MAT-PLANTING-SOIL", "식재토", "M3", "조경 식재용 토양"),
    ("LAND-MAT-FERTILIZER", "비료", "KG", "조경 식재용 비료"),
    ("LAND-MAT-STAKE", "지주목", "EA", "수목 고정용 지주목"),
    ("LAND-MAT-LANDSCAPE-STONE", "조경석", "TON", "조경 마감용 자연석"),
    ("LAND-MAT-MULCH", "멀칭재", "BAG", "식재부 보습·잡초방지재"),
)


class Command(BaseCommand):
    help = "토목·조경 FIELD 자재 투입용 표준 품목을 등록하거나 활성화합니다."

    def handle(self, *args, **options):
        category, _ = ItemCategory.objects.get_or_create(
            code="CIV-LAND",
            defaults={"name": "토목·조경 자재", "is_active": True},
        )
        if not category.is_active:
            category.is_active = True
            category.save(update_fields=["is_active", "updated_at"])
        created = updated = 0
        for code, name, uom_code, spec in STANDARD_ITEMS:
            uom, _ = UoM.objects.get_or_create(
                code=uom_code, defaults={"name": uom_code, "is_active": True}
            )
            item, was_created = ItemMaster.objects.get_or_create(
                code=code,
                defaults={
                    "name": name,
                    "category": category,
                    "uom": uom,
                    "spec": spec,
                    "is_active": True,
                },
            )
            if was_created:
                created += 1
                continue
            changed = False
            if not item.is_active:
                item.is_active = True
                changed = True
            if item.category_id is None:
                item.category = category
                changed = True
            if changed:
                item.save(update_fields=["is_active", "category", "updated_at"])
                updated += 1
        self.stdout.write(self.style.SUCCESS(f"토목·조경 표준 품목: 생성 {created}건, 활성화/보정 {updated}건"))
