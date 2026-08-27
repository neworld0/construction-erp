from apps.cost.models import CostItem, CostItemAlias, CostItemCategory


CIVIL_ROAD_CBS_SPECS = [
    {
        "code": "CIVIL-EARTHWORK",
        "name": "토공",
        "category": CostItemCategory.OTHER,
        "cost_type": "D",
        "work_type": "07",
        "is_direct": True,
        "sort_order": 110,
        "aliases": [
            "토공",
            "토사",
            "절토",
            "성토",
            "터파기",
            "되메우기",
            "노상",
            "노체",
            "흙깎기",
            "흙쌓기",
            "정지작업",
        ],
    },
    {
        "code": "CIVIL-PAVING",
        "name": "포장공",
        "category": CostItemCategory.MATERIAL,
        "cost_type": "D",
        "work_type": "08",
        "is_direct": True,
        "sort_order": 120,
        "aliases": [
            "포장",
            "도로포장",
            "포장공",
            "포장보수",
            "포장복구",
            "포장절삭",
            "덧씌우기",
        ],
    },
    {
        "code": "CIVIL-ASCON-PAVING",
        "name": "아스콘 포장",
        "category": CostItemCategory.MATERIAL,
        "cost_type": "D",
        "work_type": "08",
        "is_direct": True,
        "sort_order": 121,
        "aliases": [
            "아스콘",
            "아스팔트",
            "아스팔트포장",
            "아스콘포장",
            "표층",
            "기층",
            "중간층",
            "아스팔트 덧씌우기",
            "아스콘 덧씌우기",
        ],
    },
    {
        "code": "CIVIL-MILLING-PAVING",
        "name": "절삭 포장",
        "category": CostItemCategory.EQUIP,
        "cost_type": "D",
        "work_type": "08",
        "is_direct": True,
        "sort_order": 122,
        "aliases": [
            "절삭",
            "포장절삭",
            "노면절삭",
            "절삭후 포장",
            "절삭후 덧씌우기",
            "절삭 덧씌우기",
            "표면절삭",
        ],
    },
    {
        "code": "CIVIL-LANE-MARKING",
        "name": "차선도색",
        "category": CostItemCategory.MATERIAL,
        "cost_type": "D",
        "work_type": "08",
        "is_direct": True,
        "sort_order": 130,
        "aliases": [
            "차선",
            "도색",
            "차선도색",
            "노면표시",
            "융착식",
            "상온식",
            "문자도색",
            "기호도색",
        ],
    },
    {
        "code": "CIVIL-TRAFFIC-SAFETY",
        "name": "교통안전시설",
        "category": CostItemCategory.OTHER,
        "cost_type": "D",
        "work_type": "11",
        "is_direct": True,
        "sort_order": 140,
        "aliases": [
            "교통안전",
            "안전시설",
            "표지판",
            "교통표지",
            "로봇신호수",
            "로봇신호수 설치",
            "로봇신호수 설치 및 철거",
            "신호수",
            "교통안전관리비",
            "교통관리",
            "안전시설 설치",
            "안전시설 철거",
            "라바콘",
            "PE드럼",
            "안전휀스",
            "차단시설",
            "교통처리",
            "교통소통대책",
        ],
    },
    {
        "code": "CIVIL-BRIDGE-REPAIR",
        "name": "교량보수",
        "category": CostItemCategory.OTHER,
        "cost_type": "D",
        "work_type": "09",
        "is_direct": True,
        "sort_order": 145,
        "aliases": [
            "교량보수",
            "교면보수",
            "교면방수",
            "교면포장",
            "교면난간",
            "표면보수",
            "균열보수",
            "콘크리트 균열보수",
            "단면복구",
            "교대",
            "교각",
            "받침",
            "신축이음",
            "난간",
            "방호벽",
        ],
    },
    {
        "code": "CIVIL-WASTE",
        "name": "폐기물처리",
        "category": CostItemCategory.OTHER,
        "cost_type": "D",
        "work_type": "12",
        "is_direct": True,
        "sort_order": 150,
        "aliases": [
            "폐기물",
            "건설폐기물",
            "폐아스콘",
            "폐콘크리트",
            "폐기물처리",
            "폐기물 운반 및 처리",
            "폐기물 운반",
            "폐기물 상차",
            "폐기물 반출",
            "순환골재",
        ],
    },
    {
        "code": "CIVIL-TRANSPORT",
        "name": "운반비",
        "category": CostItemCategory.OTHER,
        "cost_type": "D",
        "work_type": "12",
        "is_direct": True,
        "sort_order": 160,
        "aliases": [
            "운반",
            "운반비",
            "반출",
            "상차",
            "하차",
            "사토운반",
            "자재운반",
        ],
    },
    {
        "code": "CIVIL-EQUIPMENT",
        "name": "장비비",
        "category": CostItemCategory.EQUIP,
        "cost_type": "D",
        "work_type": "12",
        "is_direct": True,
        "sort_order": 170,
        "aliases": [
            "장비",
            "장비비",
            "굴삭기",
            "백호",
            "로더",
            "롤러",
            "타이어롤러",
            "콤비롤러",
            "피니셔",
            "살수차",
            "덤프트럭",
            "크레인",
            "스카이",
        ],
    },
    {
        "code": "CIVIL-LABOR",
        "name": "노무비",
        "category": CostItemCategory.LABOR,
        "cost_type": "L",
        "work_type": "",
        "is_direct": True,
        "sort_order": 180,
        "aliases": [
            "노무",
            "노무비",
            "인건비",
            "작업자",
            "보통인부",
            "특별인부",
            "포장공",
            "장비운전원",
            "안전관리책임자",
            "안전관리자",
            "현장대리인",
            "인부",
            "신호수",
        ],
    },
    {
        "code": "CIVIL-MATERIAL",
        "name": "재료비",
        "category": CostItemCategory.MATERIAL,
        "cost_type": "M",
        "work_type": "",
        "is_direct": True,
        "sort_order": 190,
        "aliases": [
            "재료",
            "재료비",
            "자재",
            "자재비",
            "아스콘재료",
            "도료",
            "프라이머",
            "택코트",
            "아스팔트유제",
        ],
    },
    {
        "code": "CIVIL-QUALITY",
        "name": "품질관리비",
        "category": CostItemCategory.OTHER,
        "cost_type": "E",
        "work_type": "99",
        "is_direct": True,
        "sort_order": 195,
        "aliases": [
            "품질관리비",
            "다짐 및 품질관리",
            "다짐장비",
            "현장시험",
        ],
    },
    {
        "code": "CIVIL-FINISH",
        "name": "마감공사",
        "category": CostItemCategory.OTHER,
        "cost_type": "E",
        "work_type": "99",
        "is_direct": True,
        "sort_order": 196,
        "aliases": [
            "마감공사",
            "현장정리 및 마감",
            "원상복구",
            "마감",
        ],
    },
    {
        "code": "CIVIL-DOCUMENT",
        "name": "준공자료",
        "category": CostItemCategory.OTHER,
        "cost_type": "E",
        "work_type": "99",
        "is_direct": True,
        "sort_order": 197,
        "aliases": [
            "준공자료",
            "검측 및 준공도서 작성",
            "검측자료",
            "준공도서",
        ],
    },
    {
        "code": "CIVIL-CLEANUP",
        "name": "현장정리",
        "category": CostItemCategory.OTHER,
        "cost_type": "E",
        "work_type": "99",
        "is_direct": True,
        "sort_order": 198,
        "aliases": [
            "현장정리",
            "준공청소",
            "폐기물 정리",
        ],
    },
    {
        "code": "CIVIL-EXPENSE",
        "name": "경비",
        "category": CostItemCategory.OTHER,
        "cost_type": "E",
        "work_type": "",
        "is_direct": True,
        "sort_order": 200,
        "aliases": [
            "경비",
            "기타경비",
            "잡비",
            "제경비",
            "보험료",
            "수수료",
            "시험비",
            "품질시험",
            "품질시험비",
            "품질관리비",
            "공사손해보험료",
            "손해보험료",
            "산재보험료",
            "고용보험료",
            "건강보험료",
            "연금보험료",
            "노인장기요양보험료",
            "간접노무비",
            "퇴직공제부금비",
            "건설기계대여금지급보증서발급액",
            "건설기계대여금지급보증 발급액",
            "지급보증",
            "보증수수료",
            "지급보증수수료",
            "하도급대금지급보증수수료",
            "하도급대금지급보증",
            "발급액",
            "산업안전보건관리비",
            "환경보전비",
            "환경보건비",
        ],
    },
    {
        "code": "CIVIL-SAFETY-HEALTH",
        "name": "산업안전보건관리비",
        "category": CostItemCategory.OTHER,
        "cost_type": "I",
        "work_type": "",
        "is_direct": False,
        "sort_order": 300,
        "aliases": [
            "산업안전보건관리비",
            "안전보건관리비",
            "산업안전",
            "안전관리비",
            "보건관리비",
        ],
    },
    {
        "code": "CIVIL-GENERAL-ADMIN",
        "name": "일반관리비",
        "category": CostItemCategory.OTHER,
        "cost_type": "I",
        "work_type": "",
        "is_direct": False,
        "sort_order": 310,
        "aliases": [
            "일반관리비",
            "관리비",
            "본사관리비",
            "일반관리",
            "순공사원가",
            "총원가",
            "공급가액",
            "부가세",
        ],
    },
    {
        "code": "CIVIL-PROFIT",
        "name": "이윤",
        "category": CostItemCategory.OTHER,
        "cost_type": "I",
        "work_type": "",
        "is_direct": False,
        "sort_order": 320,
        "aliases": [
            "이윤",
            "이익",
            "공사이윤",
        ],
    },
]


def _looks_broken_text(value):
    text = str(value or "")
    broken_markers = ("?", "�", "袁", "怨", "獄", "筌", "嚥")
    return any(marker in text for marker in broken_markers)


def _find_cost_item(spec):
    # The CIVIL-* code is the stable master-data identifier used by imports,
    # budget mappings, and FIELD cost entry.  A demo or legacy item may have
    # the same display name (for example, "장비비"), but must not satisfy a
    # missing canonical CBS code.
    return CostItem.objects.filter(code=spec["code"]).first()


def _ensure_cost_item(spec):
    item = _find_cost_item(spec)
    if item is None:
        item = CostItem.objects.create(
            code=spec["code"],
            name=spec["name"],
            category=spec["category"],
            cost_type=spec["cost_type"],
            work_type=spec["work_type"],
            is_direct=spec["is_direct"],
            is_active=True,
            sort_order=spec["sort_order"],
            unit="",
        )
        return item, True, False

    update_fields = []
    if not item.code:
        item.code = spec["code"]
        update_fields.append("code")
    if not item.name or (item.code == spec["code"] and _looks_broken_text(item.name)):
        item.name = spec["name"]
        update_fields.append("name")
    if not item.category:
        item.category = spec["category"]
        update_fields.append("category")
    if not item.cost_type:
        item.cost_type = spec["cost_type"]
        update_fields.append("cost_type")
    if not item.work_type and spec["work_type"]:
        item.work_type = spec["work_type"]
        update_fields.append("work_type")
    if item.sort_order in (None, 0):
        item.sort_order = spec["sort_order"]
        update_fields.append("sort_order")
    if item.code == spec["code"] and not item.is_active:
        item.is_active = True
        update_fields.append("is_active")

    if update_fields:
        item.save(update_fields=sorted(set(update_fields)))
        return item, False, True
    return item, False, False


def _ensure_aliases(item, aliases, *, created_by=None):
    created_count = 0
    existing_count = 0
    primary_exists = item.aliases.filter(is_primary=True).exclude(alias="").exists()
    for index, alias in enumerate(dict.fromkeys(aliases)):
        defaults = {
            "is_primary": index == 0 and not primary_exists,
            "note": "seed_civil_road_cbs",
            "created_by": created_by,
        }
        alias_obj, created = CostItemAlias.objects.get_or_create(
            cost_item=item,
            alias=alias,
            defaults=defaults,
        )
        if created:
            created_count += 1
            if alias_obj.is_primary:
                primary_exists = True
        else:
            existing_count += 1
    return created_count, existing_count


def seed_civil_road_cbs(*, created_by=None):
    summary = {
        "cost_items_created": 0,
        "cost_items_updated": 0,
        "aliases_created": 0,
        "aliases_existing": 0,
    }
    for spec in CIVIL_ROAD_CBS_SPECS:
        item, created, updated = _ensure_cost_item(spec)
        if created:
            summary["cost_items_created"] += 1
        elif updated:
            summary["cost_items_updated"] += 1

        created_count, existing_count = _ensure_aliases(
            item,
            spec["aliases"],
            created_by=created_by,
        )
        summary["aliases_created"] += created_count
        summary["aliases_existing"] += existing_count
    return summary
