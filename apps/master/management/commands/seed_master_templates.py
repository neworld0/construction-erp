from decimal import Decimal

from django.core.management.base import BaseCommand
from django.db import transaction

from apps.cost.models import CostItem
from apps.master.models import (
    MasterBudgetTemplateItem,
    MasterTemplate,
    MasterTemplateCategory,
    MasterTemplateDomain,
    MasterWBSTemplateItem,
)


LANDSCAPE_WBS = [
    ("착공 준비/가설", Decimal("5")),
    ("현장 정리/가설 울타리", Decimal("5")),
    ("토공/기초 정지(성토·절토)", Decimal("12")),
    ("배수/관수 기반(배관·맨홀)", Decimal("10")),
    ("경계석/보도블록/포장", Decimal("10")),
    ("옹벽/계단/경사면 정리", Decimal("8")),
    ("식재 기반토/토양개량", Decimal("8")),
    ("교목 식재", Decimal("12")),
    ("관목·초화류 식재", Decimal("10")),
    ("잔디/지피 식재", Decimal("8")),
    ("시설물(벤치·휀스·조명 등)", Decimal("7")),
    ("마감/정리/준공서류", Decimal("5")),
]

LANDSCAPE_BUDGET = [
    ("착공/가설/안전시설", ["가설", "안전", "울타리"]),
    ("현장정리/폐기물 처리", ["현장정리", "폐기물", "반출"]),
    ("토공(정지/성토/절토)", ["토공", "정지", "성토", "절토"]),
    ("배수/관수 배관", ["배수", "관수", "배관", "맨홀"]),
    ("경계석/블록/포장", ["경계석", "보도블록", "포장"]),
    ("경사면/옹벽/계단", ["옹벽", "계단", "경사면"]),
    ("토양개량/식재기반토", ["토양개량", "식재기반", "상토"]),
    ("교목(수목)", ["교목", "수목", "수목식재"]),
    ("관목", ["관목", "관목식재"]),
    ("초화류/지피", ["초화", "지피", "초화류"]),
    ("잔디", ["잔디", "잔디식재"]),
    ("비료/멀칭/지주/보호재", ["비료", "멀칭", "지주", "보호재"]),
    ("시설물(벤치/휀스/데크 등)", ["벤치", "휀스", "데크", "시설물"]),
    ("조명/전기", ["조명", "전기", "분전"]),
    ("인건비-현장관리/작업자", ["인건비", "노무", "작업자", "현장관리"]),
    ("준공/정리/서류", ["준공", "정리", "서류"]),
]

CIVIL_WBS = [
    ("착공 준비/가설", Decimal("6")),
    ("측량/현장 정리", Decimal("6")),
    ("토공/흙막이", Decimal("15")),
    ("배수/상하수 관로", Decimal("12")),
    ("기초/구조물 시공", Decimal("12")),
    ("콘크리트 타설", Decimal("12")),
    ("포장/아스팔트", Decimal("10")),
    ("보도/경계석", Decimal("6")),
    ("전기/통신 관로", Decimal("6")),
    ("안전/품질관리", Decimal("5")),
    ("마감/정리/준공", Decimal("10")),
]

CIVIL_BUDGET = [
    ("가설/안전시설", ["가설", "안전", "울타리"]),
    ("측량/현장 정리", ["측량", "현장정리", "정리"]),
    ("토공/흙막이", ["토공", "절토", "성토", "흙막이"]),
    ("배수/상하수 관로", ["배수", "상하수", "관로", "맨홀"]),
    ("기초/구조물", ["기초", "구조물", "옹벽"]),
    ("콘크리트/철근", ["콘크리트", "철근", "거푸집"]),
    ("포장/아스팔트", ["포장", "아스팔트"]),
    ("보도/경계석", ["보도", "경계석", "블록"]),
    ("전기/통신", ["전기", "통신", "관로"]),
    ("품질/안전관리", ["품질", "안전관리"]),
    ("준공/정리", ["준공", "정리", "서류"]),
]

BUILDING_WBS = [
    ("착공 준비/가설", Decimal("6")),
    ("터파기/흙막이", Decimal("10")),
    ("기초/지하", Decimal("12")),
    ("골조/구조체", Decimal("18")),
    ("외장/방수", Decimal("10")),
    ("창호/유리", Decimal("6")),
    ("전기 설비", Decimal("8")),
    ("기계/설비", Decimal("8")),
    ("내장/마감", Decimal("12")),
    ("조경/부대", Decimal("4")),
    ("준공/정리", Decimal("6")),
]

BUILDING_BUDGET = [
    ("가설/안전시설", ["가설", "안전", "울타리"]),
    ("터파기/흙막이", ["터파기", "흙막이", "토공"]),
    ("기초/지하", ["기초", "지하", "파일"]),
    ("골조/구조체", ["골조", "철골", "철근", "콘크리트"]),
    ("외장/방수", ["외장", "방수", "석재"]),
    ("창호/유리", ["창호", "유리"]),
    ("전기 설비", ["전기", "분전", "조명"]),
    ("기계/설비", ["기계", "설비", "배관"]),
    ("내장/마감", ["내장", "마감", "도장"]),
    ("조경/부대", ["조경", "부대"]),
    ("준공/정리", ["준공", "정리", "서류"]),
]

DOMAIN_TEMPLATES = {
    MasterTemplateDomain.LANDSCAPE: {
        "name": ("조경 표준 WBS", "조경 표준 예산"),
        "wbs": LANDSCAPE_WBS,
        "budget": LANDSCAPE_BUDGET,
    },
    MasterTemplateDomain.CIVIL: {
        "name": ("토목 기본 WBS", "토목 기본 예산"),
        "wbs": CIVIL_WBS,
        "budget": CIVIL_BUDGET,
    },
    MasterTemplateDomain.BUILDING: {
        "name": ("건축 기본 WBS", "건축 기본 예산"),
        "wbs": BUILDING_WBS,
        "budget": BUILDING_BUDGET,
    },
}


class Command(BaseCommand):
    help = "Seed master templates for WBS/Budget."

    def handle(self, *args, **options):
        with transaction.atomic():
            items = list(
                CostItem.objects.all().values("id", "name", "is_active", "code")
            )
            for domain, payload in DOMAIN_TEMPLATES.items():
                wbs_name, budget_name = payload["name"]
                wbs_rows = payload["wbs"]
                budget_rows = payload["budget"]
                wbs_template, wbs_created = MasterTemplate.objects.get_or_create(
                    category=MasterTemplateCategory.WBS,
                    domain=domain,
                    version=1,
                    defaults={
                        "name": wbs_name,
                        "is_active": True,
                    },
                )
                wbs_items = []
                for idx, (name, weight) in enumerate(wbs_rows, start=1):
                    wbs_items.append(
                        MasterWBSTemplateItem(
                            template=wbs_template,
                            order=idx,
                            task_name=name,
                            weight=weight,
                        )
                    )
                # Keep seed deterministic for v1 templates.
                MasterWBSTemplateItem.objects.filter(template=wbs_template).delete()
                MasterWBSTemplateItem.objects.bulk_create(wbs_items)

                budget_template, budget_created = MasterTemplate.objects.get_or_create(
                    category=MasterTemplateCategory.BUDGET,
                    domain=domain,
                    version=1,
                    defaults={
                        "name": budget_name,
                        "is_active": True,
                    },
                )
                budget_items = []
                for idx, (label, keywords) in enumerate(budget_rows, start=1):
                    matches = [
                        item
                        for item in items
                        if any(keyword in item["name"] for keyword in keywords)
                    ]
                    matches_active = [item for item in matches if item.get("is_active")]
                    pick = None
                    if matches_active:
                        pick = sorted(matches_active, key=lambda x: len(x["name"]))[0]
                    elif matches:
                        pick = sorted(matches, key=lambda x: len(x["name"]))[0]
                    budget_items.append(
                        MasterBudgetTemplateItem(
                            template=budget_template,
                            order=idx,
                            cost_item_id=pick["id"] if pick else None,
                            cost_item_code_snapshot=pick["code"] if pick else "",
                            label=label,
                            is_labor="인건비" in label,
                        )
                    )
                # Keep seed deterministic for v1 templates.
                MasterBudgetTemplateItem.objects.filter(
                    template=budget_template
                ).delete()
                MasterBudgetTemplateItem.objects.bulk_create(budget_items)

        self.stdout.write("MasterTemplate seeded: domains=3 (WBS/BUDGET)")
