from decimal import Decimal
from io import StringIO

import pytest
from django.core.management import call_command
from django.db.models import Count
from openpyxl import Workbook

from apps.cost.models import CostItem, CostItemAlias
from apps.cost.seed_civil_road_cbs import seed_civil_road_cbs
from apps.projects.forms import (
    BUDGET_BASELINE_CATEGORY_CHOICES,
    BudgetItemForm,
    WBSItemForm,
)
from apps.projects.excel_import import parse_budget_summary_sheet
from apps.projects.hq_views import (
    _build_budget_initial_from_import_rows,
    _build_wbs_initial_from_import_rows,
    _canonical_budget_category_for_cost_item,
    _is_weight_sum_valid,
    _make_budget_import_key,
    _normalize_project_budget_categories,
    get_cost_items_for_budget_bucket,
)
from apps.projects.models import BudgetCategory, BudgetItem, Project


REQUIRED_CBS_NAMES = [
    "토공",
    "포장공",
    "아스콘 포장",
    "절삭 포장",
    "차선도색",
    "교통안전시설",
    "폐기물처리",
    "운반비",
    "장비비",
    "노무비",
    "재료비",
    "경비",
    "산업안전보건관리비",
    "일반관리비",
    "이윤",
]


def _asphalt_bucket_row():
    return {
        "code": "1-1-1",
        "row_no": 10,
        "sheet_name": "도급계약내역서",
        "item_name": "아스팔트 포장 절삭후 아스팔트 덧씌우기",
        "spec": "A-Type (1회절삭,2회포장)-야간작업",
        "quantity": 1969,
        "unit": "㎡",
        "unit_price": 6368,
        "amount": 12538592,
        "labor_amount": 7234106,
        "material_amount": 2378552,
        "expense_amount": 2925934,
        "warnings": [],
    }


@pytest.mark.django_db
def test_seed_civil_road_cbs_creates_minimum_cost_items():
    seed_civil_road_cbs()

    for name in REQUIRED_CBS_NAMES:
        item = CostItem.objects.get(name=name)
        assert item.code
        assert item.is_active is True


@pytest.mark.django_db
def test_seed_civil_road_cbs_is_idempotent():
    seed_civil_road_cbs()
    seed_civil_road_cbs()

    duplicate_codes = (
        CostItem.objects.values("code").order_by().annotate(code_count=Count("id"))
    )
    assert not any(row["code_count"] > 1 for row in duplicate_codes)

    duplicate_aliases = (
        CostItemAlias.objects.values("cost_item_id", "alias")
        .order_by()
        .annotate(alias_count=Count("id"))
    )
    assert not any(row["alias_count"] > 1 for row in duplicate_aliases)


@pytest.mark.django_db
def test_seed_civil_road_cbs_management_command():
    out = StringIO()
    call_command("seed_civil_road_cbs", stdout=out)
    call_command("seed_civil_road_cbs", stdout=out)

    output = out.getvalue()
    assert "도로/토목 CBS seed가 완료되었습니다." in output
    for name in REQUIRED_CBS_NAMES:
        assert CostItem.objects.filter(name=name).exists()


@pytest.mark.django_db
def test_build_budget_initial_from_import_rows_skips_section_title_rows_without_warning():
    rows = [
        {"item_name": "국도46호선 호평IC교(상)", "amount": None, "quantity": None, "unit": "", "warnings": []},
        {"item_name": "소 계", "amount": None, "quantity": None, "unit": "", "warnings": []},
    ]

    initial, warnings, stats = _build_budget_initial_from_import_rows(rows)

    assert initial == []
    assert stats["budget_import_unmatched_rows"] == 0
    assert stats["budget_import_skipped_rows"] == 2
    assert not any("CBS 미매칭" in warning for warning in warnings)


@pytest.mark.django_db
def test_build_budget_initial_from_import_rows_matches_asphalt_to_seeded_cbs():
    seed_civil_road_cbs()
    rows = [
        {
            "item_name": "아스팔트 포장 절삭후 아스팔트 덧씌우기",
            "spec": "A-Type (1회절삭,2회포장)-야간작업",
            "amount": 12538592,
            "quantity": 1969,
            "unit": "㎡",
            "warnings": [],
        }
    ]

    initial, warnings, stats = _build_budget_initial_from_import_rows(rows)

    assert warnings == []
    assert len(initial) == 1
    matched = CostItem.objects.get(id=initial[0]["cost_item"])
    assert matched.name in {"아스콘 포장", "포장공"}
    assert initial[0]["planned_amount"] == 12538592
    assert stats["budget_import_unmatched_rows"] == 0


@pytest.mark.django_db
def test_build_budget_initial_from_import_rows_matches_lane_marking_to_seeded_cbs():
    seed_civil_road_cbs()
    rows = [
        {
            "item_name": "차선도색",
            "spec": "융착식",
            "amount": 800000,
            "quantity": 1,
            "unit": "식",
            "warnings": [],
        }
    ]

    initial, warnings, stats = _build_budget_initial_from_import_rows(rows)

    assert warnings == []
    assert len(initial) == 1
    matched = CostItem.objects.get(id=initial[0]["cost_item"])
    assert matched.name == "차선도색"
    assert stats["budget_import_unmatched_rows"] == 0


@pytest.mark.django_db
def test_build_budget_initial_from_import_rows_matches_waste_to_seeded_cbs():
    seed_civil_road_cbs()
    rows = [
        {
            "item_name": "폐기물 운반 및 처리",
            "amount": 500000,
            "quantity": 1,
            "unit": "식",
            "warnings": [],
        }
    ]

    initial, warnings, stats = _build_budget_initial_from_import_rows(rows)

    assert warnings == []
    assert len(initial) == 1
    matched = CostItem.objects.get(id=initial[0]["cost_item"])
    assert matched.name in {"폐기물처리", "운반비"}
    assert stats["budget_import_unmatched_rows"] == 0


@pytest.mark.django_db
def test_unmatched_warning_is_limited_and_summarized():
    rows = [
        {
            "item_name": f"테스트미매칭{idx}",
            "code": f"R-{idx}",
            "amount": 10000,
            "quantity": 1,
            "unit": "식",
            "warnings": [],
        }
        for idx in range(198)
    ]

    initial, warnings, stats = _build_budget_initial_from_import_rows(rows)

    assert initial == []
    assert stats["budget_import_unmatched_rows"] == 198
    assert len(warnings) <= 31
    assert any("198건 중 30건만 표시합니다." in warning for warning in warnings)


@pytest.mark.django_db
def test_build_budget_initial_from_import_rows_uses_alias_when_available():
    cost_item = CostItem.objects.create(code="WASTE-001", name="폐기물처리", category="other")
    CostItemAlias.objects.create(cost_item=cost_item, alias="폐기물 운반", is_primary=True)
    rows = [
        {"item_name": "폐기물 운반 및 처리", "amount": 500000, "quantity": 1, "unit": "식", "warnings": []}
    ]

    initial, warnings, stats = _build_budget_initial_from_import_rows(rows)

    assert warnings == []
    assert len(initial) == 1
    assert initial[0]["cost_item"] == cost_item.id
    assert stats["budget_import_unmatched_rows"] == 0


def test_build_wbs_initial_from_import_rows_quantizes_weights_to_model_precision():
    rows = [
        {"name": "1. 국도46호선 호평IC교(상)", "weight": Decimal("63.3694747566030300"), "plan_start_date": None, "plan_end_date": None, "warnings": []},
        {"name": "2. 국도46호선 신구로(춘천)", "weight": Decimal("36.63052524339696600"), "plan_start_date": None, "plan_end_date": None, "warnings": []},
    ]

    initial, warnings = _build_wbs_initial_from_import_rows(rows)

    assert warnings == []
    assert initial[0]["weight"] == Decimal("63.37")
    assert initial[1]["weight"] == Decimal("36.63")
    total = sum((item["weight"] for item in initial), Decimal("0"))
    assert total == Decimal("100.00")
    assert _is_weight_sum_valid(total)


def test_wbs_item_form_weight_widget_attrs_are_html5_safe():
    form = WBSItemForm()

    attrs = form.fields["weight"].widget.attrs
    assert attrs["step"] == "0.01"
    assert attrs["min"] == "0"
    assert attrs["max"] == "100"
    assert attrs["inputmode"] == "decimal"


@pytest.mark.django_db
def test_build_budget_initial_skips_amount_only_aggregate_rows_without_warning():
    rows = [
        {
            "code": "1",
            "item_name": "국도46호선 호평IC교(상)",
            "quantity": None,
            "unit": "",
            "unit_price": None,
            "amount": 181183936,
            "labor_amount": None,
            "material_amount": None,
            "expense_amount": None,
            "warnings": [],
        }
    ]

    initial, warnings, stats = _build_budget_initial_from_import_rows(rows)

    assert initial == []
    assert stats["budget_import_skipped_rows"] == 1
    assert stats["budget_import_skipped_section_rows"] == 1
    assert stats["budget_import_unmatched_rows"] == 0
    assert not any("CBS" in warning or "자동 매칭" in warning for warning in warnings)


@pytest.mark.django_db
def test_build_budget_initial_skips_amount_only_aggregate_rows_with_dash_values():
    rows = [
        {
            "code": "1-1",
            "item_name": "호평IC교(상)",
            "quantity": "-",
            "unit": "-",
            "unit_price": "",
            "amount": 181183936,
            "warnings": [],
        }
    ]

    initial, warnings, stats = _build_budget_initial_from_import_rows(rows)

    assert initial == []
    assert stats["budget_import_skipped_rows"] == 1
    assert stats["budget_import_skipped_section_rows"] == 1
    assert stats["budget_import_unmatched_rows"] == 0


@pytest.mark.django_db
def test_build_budget_initial_does_not_skip_valid_lump_sum_leaf_row():
    seed_civil_road_cbs()
    rows = [
        {
            "code": "1-2",
            "item_name": "교면난간",
            "quantity": 1,
            "unit": "식",
            "unit_price": 100000,
            "amount": 100000,
            "warnings": [],
        }
    ]

    initial, warnings, stats = _build_budget_initial_from_import_rows(rows)

    assert warnings == []
    assert len(initial) == 1
    matched = CostItem.objects.get(id=initial[0]["cost_item"])
    assert matched.code == "CIVIL-BRIDGE-REPAIR"
    assert stats["budget_import_skipped_rows"] == 0
    assert stats["budget_import_unmatched_rows"] == 0


@pytest.mark.django_db
def test_build_budget_initial_does_not_skip_leaf_with_quantity_unit_and_missing_unit_price():
    seed_civil_road_cbs()
    rows = [
        {
            "code": "1-3",
            "item_name": "차선도색",
            "quantity": 1,
            "unit": "식",
            "unit_price": None,
            "amount": 500000,
            "warnings": [],
        }
    ]

    initial, warnings, stats = _build_budget_initial_from_import_rows(rows)

    assert warnings == []
    assert len(initial) == 1
    matched = CostItem.objects.get(id=initial[0]["cost_item"])
    assert matched.code == "CIVIL-LANE-MARKING"
    assert stats["budget_import_skipped_rows"] == 0


@pytest.mark.django_db
def test_owner_supplied_material_excluded_from_contract_budget():
    seed_civil_road_cbs()
    rows = [
        {"code": "5.", "item_name": "관급자재대", "quantity": "-", "unit": "-", "unit_price": None, "amount": 37700000, "warnings": []},
        {"code": "5-1", "item_name": "호평IC교(상)", "quantity": "-", "unit": "-", "unit_price": None, "amount": 37645120, "warnings": []},
        {"code": "5-1-1", "item_name": "아스콘(관급)-서울", "quantity": 1, "unit": "식", "unit_price": 37645120, "amount": 37645120, "warnings": []},
        {"code": "5-2", "item_name": "단수조정", "quantity": 1, "unit": "식", "unit_price": 54880, "amount": 54880, "warnings": []},
    ]

    initial, warnings, stats = _build_budget_initial_from_import_rows(rows)

    assert initial == []
    assert warnings == []
    assert stats["budget_import_owner_supplied_amount"] == Decimal("37700000")
    assert stats["budget_import_contract_scope_amount"] == Decimal("0")
    assert stats["budget_import_matched_amount"] == Decimal("0")
    assert stats["budget_import_owner_supplied_rows"] >= 4


@pytest.mark.django_db
def test_owner_supplied_child_without_code_is_excluded_until_next_top_level():
    seed_civil_road_cbs()
    rows = [
        {"code": "5.", "item_name": "관급자재대", "quantity": "-", "unit": "-", "unit_price": "-", "amount": 37700000, "warnings": []},
        {"code": "5-1", "item_name": "호평IC교(상)", "quantity": "-", "unit": "-", "unit_price": "-", "amount": 37645120, "warnings": []},
        {"code": "", "item_name": "아스콘(관급)-서울,인천,경기", "spec": "조합공통품목", "quantity": 376, "unit": "톤", "unit_price": 100120, "amount": 37645120, "warnings": []},
        {"code": "6.", "item_name": "다음공종", "quantity": "-", "unit": "-", "unit_price": "-", "amount": 0, "warnings": []},
        {"code": "6-1", "item_name": "아스팔트 포장 절삭후 아스팔트 덧씌우기", "quantity": 1969, "unit": "㎡", "unit_price": 6368, "amount": 12538592, "warnings": []},
    ]

    initial, warnings, stats = _build_budget_initial_from_import_rows(rows)

    assert not any("CBS 미매칭" in warning for warning in warnings)
    assert stats["budget_import_owner_supplied_rows"] >= 3
    assert any(item["planned_amount"] == 12538592 for item in initial)
    assert all("관급" not in (item["note"] or "") for item in initial)


@pytest.mark.django_db
def test_regular_ascon_not_excluded():
    seed_civil_road_cbs()
    rows = [
        {
            "code": "1-1-1",
            "item_name": "아스팔트 포장 절삭후 아스팔트 덧씌우기",
            "quantity": 1969,
            "unit": "㎡",
            "unit_price": 6368,
            "amount": 12538592,
            "warnings": [],
        }
    ]

    initial, warnings, stats = _build_budget_initial_from_import_rows(rows)

    assert warnings == []
    assert len(initial) == 1
    matched = CostItem.objects.get(id=initial[0]["cost_item"])
    assert matched.code == "CIVIL-ASCON-PAVING"
    assert stats["budget_import_owner_supplied_rows"] == 0
    assert stats["budget_import_matched_rows"] == 1


@pytest.mark.django_db
def test_subcontract_payment_guarantee_fee_matches_expense():
    seed_civil_road_cbs()
    rows = [
        {
            "code": "8-1",
            "item_name": "하도급대금지급보증수수료",
            "quantity": Decimal("0.081"),
            "unit": "%",
            "unit_price": None,
            "amount": 261437,
            "expense_amount": 261437,
            "warnings": [],
        }
    ]

    initial, warnings, stats = _build_budget_initial_from_import_rows(rows)

    assert warnings == []
    assert len(initial) == 1
    matched = CostItem.objects.get(id=initial[0]["cost_item"])
    assert matched.code == "CIVIL-EXPENSE"
    assert initial[0]["category"] == BudgetCategory.OTHER
    assert "경비" in initial[0]["name"]
    assert stats["budget_import_generated_expense_amount"] == Decimal("261437")


@pytest.mark.django_db
def test_profit_is_not_auto_matched():
    seed_civil_road_cbs()
    rows = [
        {
            "code": "9-1",
            "item_name": "이윤",
            "quantity": Decimal("14.88"),
            "unit": "%",
            "unit_price": None,
            "amount": 51113990,
            "warnings": [],
        }
    ]

    initial, warnings, stats = _build_budget_initial_from_import_rows(rows)

    assert initial == []
    assert stats["budget_import_unmatched_rows"] == 1
    assert rows[0]["matched_cost_item_id"] is None
    assert rows[0]["requires_manual_profit_mapping"] is True
    assert any("이윤은 수동 매핑" in warning for warning in rows[0]["warnings"] + warnings)


@pytest.mark.django_db
def test_profit_can_be_manually_mapped_to_profit_cbs():
    seed_civil_road_cbs()
    profit_item = CostItem.objects.get(code="CIVIL-PROFIT")
    row = {
        "code": "9-1",
        "row_no": 12,
        "item_name": "이윤",
        "quantity": Decimal("14.88"),
        "unit": "%",
        "unit_price": None,
        "amount": 51113990,
        "expense_amount": 51113990,
        "warnings": [],
    }
    manual_mapping = {_make_budget_import_key(row, 0): str(profit_item.id)}

    initial, warnings, stats = _build_budget_initial_from_import_rows([row], manual_mapping=manual_mapping)

    assert warnings == []
    assert len(initial) == 1
    assert initial[0]["cost_item"] == profit_item.id
    assert initial[0]["planned_amount"] == 51113990
    assert initial[0]["category"] == BudgetCategory.OTHER
    assert stats["budget_import_generated_expense_amount"] == Decimal("51113990")


@pytest.mark.django_db
def test_safety_manager_does_not_match_profit():
    seed_civil_road_cbs()
    rows = [
        {
            "code": "10-1",
            "item_name": "안전관리책임자",
            "quantity": 1,
            "unit": "식",
            "unit_price": 14127540,
            "amount": 14127540,
            "warnings": [],
        }
    ]

    initial, warnings, _stats = _build_budget_initial_from_import_rows(rows)

    assert warnings == []
    assert len(initial) == 1
    matched = CostItem.objects.get(id=initial[0]["cost_item"])
    assert matched.code != "CIVIL-PROFIT"
    assert matched.code in {"CIVIL-LABOR", "LABOR-GENERAL"}


@pytest.mark.django_db
@pytest.mark.parametrize(
    "item_name",
    [
        "간접노무비",
        "산재보험료",
        "건강보험료",
        "연금보험료",
        "노인장기요양보험료",
        "퇴직공제부금비",
        "건설기계대여금지급보증서발급액",
        "산업안전보건관리비",
        "환경보전비",
        "환경보건비",
        "하도급대금지급보증수수료",
        "일반관리비",
    ],
)
def test_indirect_expense_rows_map_to_other_expense_bucket(item_name):
    seed_civil_road_cbs()
    rows = [
        {
            "code": "30-1",
            "item_name": item_name,
            "quantity": 1,
            "unit": "식",
            "unit_price": 1000,
            "amount": 1000,
            "labor_amount": 0,
            "material_amount": 0,
            "expense_amount": 1000,
            "warnings": [],
        }
    ]

    initial, warnings, stats = _build_budget_initial_from_import_rows(rows)

    assert warnings == []
    assert len(initial) == 1
    assert initial[0]["category"] == BudgetCategory.OTHER
    assert initial[0]["planned_amount"] == 1000
    assert stats["budget_import_generated_expense_amount"] == Decimal("1000")
    assert not rows[0].get("is_skipped")


@pytest.mark.django_db
def test_summary_sheet_parses_three_bucket_contract_amounts():
    workbook = Workbook()
    workbook.active.title = "도급계약내역서"
    summary = workbook.create_sheet("내역서총괄표(도급)")
    summary["A1"] = "도급예정액"
    summary["B1"] = 571022700
    summary["A2"] = "노무비"
    summary["B2"] = 218435187
    summary["A3"] = "재료비"
    summary["B3"] = 107322412
    summary["A4"] = "경비"
    summary["B4"] = 245265101
    summary["A5"] = "관급자재대"
    summary["B5"] = 37700000
    summary["A6"] = "총공사비"
    summary["B6"] = 608722700

    payload = parse_budget_summary_sheet(workbook)

    assert payload["contract_expected_amount"] == Decimal("571022700")
    assert payload["contract_labor_amount"] == Decimal("218435187")
    assert payload["contract_material_amount"] == Decimal("107322412")
    assert payload["contract_expense_amount"] == Decimal("245265101")
    assert payload["owner_supplied_amount"] == Decimal("37700000")
    assert payload["total_construction_amount"] == Decimal("608722700")


@pytest.mark.django_db
def test_budget_import_splits_asphalt_row_into_three_bucket_lines():
    seed_civil_road_cbs()
    initial, warnings, stats = _build_budget_initial_from_import_rows([_asphalt_bucket_row()])

    assert warnings == []
    assert len(initial) == 3
    by_category = {row["category"]: row["planned_amount"] for row in initial}
    assert by_category[BudgetCategory.LABOR] == 7234106
    assert by_category[BudgetCategory.MATERIAL] == 2378552
    assert by_category[BudgetCategory.OTHER] == 2925934
    assert sum(row["planned_amount"] for row in initial) == 12538592
    notes = " ".join(row["note"] for row in initial)
    assert "품명:아스팔트 포장 절삭후 아스팔트 덧씌우기" in notes
    assert "버킷:노무비" in notes
    assert "버킷:재료비" in notes
    assert "버킷:경비" in notes
    assert stats["budget_import_generated_labor_amount"] == Decimal("7234106")
    assert stats["budget_import_generated_material_amount"] == Decimal("2378552")
    assert stats["budget_import_generated_expense_amount"] == Decimal("2925934")


@pytest.mark.django_db
def test_budget_import_preserves_cbs_traceability_in_notes():
    seed_civil_road_cbs()
    initial, _, _ = _build_budget_initial_from_import_rows([_asphalt_bucket_row()])
    notes = " ".join(row["note"] for row in initial)
    assert "원본:도급계약내역서:10" in notes
    assert "품명:아스팔트 포장 절삭후 아스팔트 덧씌우기" in notes
    assert "버킷:" in notes


@pytest.mark.django_db
def test_budget_review_rows_are_source_row_bucket_level_not_aggregated():
    seed_civil_road_cbs()
    rows = [
        {
            "code": "L-1",
            "row_no": 1,
            "sheet_name": "도급계약내역서",
            "item_name": "안전관리책임자",
            "quantity": 1,
            "unit": "식",
            "unit_price": 1000,
            "amount": 1000,
            "labor_amount": 1000,
            "material_amount": 0,
            "expense_amount": 0,
            "warnings": [],
        },
        {
            "code": "L-2",
            "row_no": 2,
            "sheet_name": "도급계약내역서",
            "item_name": "신호수",
            "quantity": 1,
            "unit": "식",
            "unit_price": 2000,
            "amount": 2000,
            "labor_amount": 2000,
            "material_amount": 0,
            "expense_amount": 0,
            "warnings": [],
        },
    ]

    initial, warnings, stats = _build_budget_initial_from_import_rows(rows)

    assert warnings == []
    assert len(initial) == 2
    review_rows = [row for row in stats["budget_review_rows"] if row["bucket"] == "LABOR"]
    assert len(review_rows) == 2
    assert "엑셀 합산 2행" not in " ".join(row["note"] for row in initial)
    assert stats["budget_form_initial_count"] == 2


@pytest.mark.django_db
def test_asphalt_row_creates_three_editable_review_rows():
    seed_civil_road_cbs()
    _initial, warnings, stats = _build_budget_initial_from_import_rows([_asphalt_bucket_row()])

    assert warnings == []
    review_rows = stats["budget_review_rows"]
    assert len(review_rows) == 3
    assert {row["bucket"] for row in review_rows} == {"LABOR", "MATERIAL", "EXPENSE"}
    assert len({row["review_key"] for row in review_rows}) == 3
    assert all(row["source_row_no"] == 10 for row in review_rows)
    assert all(row["source_item_name"] == "아스팔트 포장 절삭후 아스팔트 덧씌우기" for row in review_rows)


@pytest.mark.django_db
def test_apply_budget_review_adjustment_changes_category_and_totals():
    seed_civil_road_cbs()
    rows = [
        {
            "code": "L-1",
            "row_no": 1,
            "sheet_name": "도급계약내역서",
            "item_name": "안전관리책임자",
            "quantity": 1,
            "unit": "식",
            "unit_price": 1000,
            "amount": 1000,
            "labor_amount": 1000,
            "material_amount": 0,
            "expense_amount": 0,
            "warnings": [],
        },
    ]

    _initial, _warnings, stats = _build_budget_initial_from_import_rows(rows)
    review_key = stats["budget_review_rows"][0]["review_key"]
    expense_item = CostItem.objects.get(code="CIVIL-EXPENSE")

    adjusted_initial, warnings, adjusted_stats = _build_budget_initial_from_import_rows(
        rows,
        manual_adjustments={
            review_key: {
                "category": BudgetCategory.OTHER,
                "cost_item_id": str(expense_item.id),
                "name": "수동 경비 전환",
                "planned_amount": Decimal("900"),
            }
        },
    )

    assert warnings == []
    assert adjusted_stats["budget_import_generated_labor_amount"] == Decimal("0")
    assert adjusted_stats["budget_import_generated_expense_amount"] == Decimal("900")
    assert adjusted_initial[0]["category"] == BudgetCategory.OTHER
    assert adjusted_initial[0]["planned_amount"] == Decimal("900")
    assert any(candidate.get("difference") == Decimal("100") for candidate in adjusted_stats["budget_reconciliation_candidates"])


@pytest.mark.django_db
def test_apply_budget_review_adjustment_excludes_row():
    seed_civil_road_cbs()
    rows = [_asphalt_bucket_row()]
    _initial, _warnings, stats = _build_budget_initial_from_import_rows(rows)
    labor_review = next(row for row in stats["budget_review_rows"] if row["bucket"] == "LABOR")

    adjusted_initial, warnings, adjusted_stats = _build_budget_initial_from_import_rows(
        rows,
        manual_adjustments={labor_review["review_key"]: {"exclude": True}},
    )

    assert warnings == []
    assert len(adjusted_initial) == 2
    assert adjusted_stats["budget_import_generated_labor_amount"] == Decimal("0")
    assert adjusted_stats["budget_import_excluded_amount"] == Decimal("7234106")
    assert all(row["bucket"] != "LABOR" for row in adjusted_stats["budget_review_rows"] if not row["is_excluded"])


@pytest.mark.django_db
def test_budget_form_category_choices_are_korean_and_limited():
    form = BudgetItemForm()
    choices = form.fields["category"].choices
    assert choices == BUDGET_BASELINE_CATEGORY_CHOICES
    labels = [label for _value, label in choices]
    assert labels == ["재료비", "하도급", "노무비", "경비"]
    values = {value for value, _label in choices}
    assert BudgetCategory.EQUIP not in values
    assert BudgetCategory.OVERHEAD not in values


@pytest.mark.django_db
def test_canonical_category_maps_equip_and_overhead_to_other():
    equip_item = CostItem.objects.create(code="TEST-EQUIP", name="장비 항목", category="equip")
    overhead_item = CostItem.objects.create(code="TEST-OVERHEAD", name="간접 항목", category="other")

    assert _canonical_budget_category_for_cost_item(equip_item) == BudgetCategory.OTHER
    assert _canonical_budget_category_for_cost_item(
        overhead_item,
        current_category=BudgetCategory.OVERHEAD,
    ) == BudgetCategory.OTHER


@pytest.mark.django_db
def test_canonical_category_preserves_explicit_subcontract():
    item = CostItem.objects.create(code="TEST-OTHER-SUBCON", name="기타 CBS", category="other")

    assert (
        _canonical_budget_category_for_cost_item(item, current_category=BudgetCategory.SUBCON)
        == BudgetCategory.SUBCON
    )


@pytest.mark.django_db
def test_normalize_project_budget_categories_does_not_demote_subcontract():
    project = Project.objects.create(code="PRJ-SUBCON-KEEP", name="하도급 유지 공사", project_type="civil", status="draft")
    item = CostItem.objects.create(code="TEST-OTHER-SUBCON-ROW", name="기타 CBS 행", category="other")
    budget_item = BudgetItem.objects.create(
        project=project,
        cost_item=item,
        category=BudgetCategory.SUBCON,
        name="하도급",
        planned_amount=1000,
    )

    _normalize_project_budget_categories(project)

    budget_item.refresh_from_db()
    assert budget_item.category == BudgetCategory.SUBCON


@pytest.mark.django_db
def test_import_never_creates_equip_or_overhead_budget_category():
    seed_civil_road_cbs()
    rows = [
        {
            "code": "14-1",
            "item_name": "장비비",
            "quantity": 1,
            "unit": "식",
            "unit_price": 500000,
            "amount": 500000,
            "warnings": [],
        }
    ]

    initial, warnings, _stats = _build_budget_initial_from_import_rows(rows)

    assert warnings == []
    assert len(initial) == 1
    assert initial[0]["category"] == BudgetCategory.OTHER


@pytest.mark.django_db
def test_get_cost_items_for_budget_bucket_filters_correctly():
    seed_civil_road_cbs()
    labor_codes = set(get_cost_items_for_budget_bucket("LABOR").values_list("code", flat=True))
    material_codes = set(get_cost_items_for_budget_bucket("MATERIAL").values_list("code", flat=True))
    expense_codes = set(get_cost_items_for_budget_bucket("EXPENSE").values_list("code", flat=True))

    assert "CIVIL-LABOR" in labor_codes or "LABOR-GENERAL" in labor_codes
    assert "CIVIL-PROFIT" not in labor_codes
    assert "CIVIL-MATERIAL" in material_codes
    assert "CIVIL-ASCON-PAVING" in material_codes
    assert "CIVIL-EXPENSE" in expense_codes
    assert "CIVIL-PROFIT" in expense_codes
    assert "CIVIL-LABOR" not in expense_codes
    assert "CIVIL-MATERIAL" not in expense_codes


@pytest.mark.django_db
def test_excel_bucket_category_overrides_cost_item_category():
    seed_civil_road_cbs()
    initial, warnings, _stats = _build_budget_initial_from_import_rows([_asphalt_bucket_row()])

    assert warnings == []
    by_category = {row["category"]: row for row in initial}
    assert by_category[BudgetCategory.LABOR]["planned_amount"] == 7234106
    assert by_category[BudgetCategory.MATERIAL]["planned_amount"] == 2378552
    assert by_category[BudgetCategory.OTHER]["planned_amount"] == 2925934


@pytest.mark.django_db
def test_sample_summary_reconciles_generated_bucket_totals():
    seed_civil_road_cbs()
    rows = [
        {
            "code": "1",
            "item_name": "안전관리책임자",
            "quantity": 1,
            "unit": "식",
            "unit_price": 218435187,
            "amount": 218435187,
            "labor_amount": 218435187,
            "material_amount": 0,
            "expense_amount": 0,
            "warnings": [],
        },
        {
            "code": "2",
            "item_name": "아스콘 포장",
            "quantity": 1,
            "unit": "식",
            "unit_price": 107322412,
            "amount": 107322412,
            "labor_amount": 0,
            "material_amount": 107322412,
            "expense_amount": 0,
            "warnings": [],
        },
        {
            "code": "3",
            "item_name": "일반관리비",
            "quantity": 1,
            "unit": "식",
            "unit_price": 245265101,
            "amount": 245265101,
            "labor_amount": 0,
            "material_amount": 0,
            "expense_amount": 245265101,
            "warnings": [],
        },
    ]

    _initial, warnings, stats = _build_budget_initial_from_import_rows(rows)

    assert warnings == []
    assert stats["budget_import_generated_labor_amount"] == Decimal("218435187")
    assert stats["budget_import_generated_material_amount"] == Decimal("107322412")
    assert stats["budget_import_generated_expense_amount"] == Decimal("245265101")
    assert stats["budget_import_generated_contract_amount"] == Decimal("571022700")
    assert stats["budget_import_manual_required_total_amount"] == Decimal("0")
    assert stats["budget_import_unmapped_total_amount"] == Decimal("0")


@pytest.mark.django_db
def test_missing_profit_is_reported_as_manual_required_expense_not_dropped():
    seed_civil_road_cbs()
    row = {
        "code": "9-9",
        "row_no": 99,
        "sheet_name": "도급계약내역서",
        "item_name": "이윤",
        "quantity": Decimal("14.88"),
        "unit": "%",
        "unit_price": None,
        "amount": 1000,
        "labor_amount": 0,
        "material_amount": 0,
        "expense_amount": 1000,
        "warnings": [],
    }

    initial, warnings, stats = _build_budget_initial_from_import_rows([row])

    assert initial == []
    assert stats["budget_import_manual_required_expense_amount"] == Decimal("1000")
    assert stats["budget_import_unmapped_expense_amount"] == Decimal("0")
    assert stats["budget_import_generated_expense_amount"] == Decimal("0")
    assert stats["budget_import_manual_required_rows"] == 1
    assert any("이윤은 수동 매핑" in warning for warning in warnings + row["warnings"])
    assert stats["budget_reconciliation_candidates"]
    candidate = stats["budget_reconciliation_candidates"][0]
    assert candidate["bucket"] == "EXPENSE"
    assert candidate["status"] == "수동 매핑 필요"
