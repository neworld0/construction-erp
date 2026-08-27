from decimal import Decimal
from io import BytesIO

import pytest
from openpyxl import Workbook

from apps.cost.models import CostItem, CostItemAlias
from apps.cost.seed_civil_road_cbs import seed_civil_road_cbs
from apps.projects.excel_import import parse_contract_budget_excel
from apps.projects.hq_views import _build_budget_initial_from_import_rows


HEADERS = [
    "원본행번호", "레벨", "공종코드", "WBS코드", "WBS명", "CBS코드", "CBS명",
    "원가구분", "품명", "규격", "수량", "단위", "도급단가", "노무비", "재료비",
    "경비", "도급금액", "비고", "ERP업로드상태",
]

ROWS = [
    [1, 1, "1.", "WBS-01", "현장 준비 및 안전관리", "CIVIL-SAFETY", "안전관리비", "경비", "현장 인수 및 가설 안전시설", "작업구간 인수·안전표지·라바콘", 1, "식", 8000000, 4200000, 2000000, 1800000, 8000000, "2026-08-14 착수", "업로드대상"],
    [2, 2, "1-1", "WBS-01", "현장 준비 및 안전관리", "CIVIL-SAFETY", "안전관리비", "경비", "교통안전시설 설치 및 철거", "차량부분통제·야간안전 포함", 1, "식", 5200000, 1800000, 2400000, 1000000, 5200000, "안전관리 포함", "업로드대상"],
    [3, 1, "2.", "WBS-02", "기존 포장 절삭", "CIVIL-EQUIP", "장비비", "경비", "아스팔트 포장 절삭", "T=5cm, 소규모 보수구간", 500, "㎡", 32000, 6000000, 0, 10000000, 16000000, "절삭 장비 포함", "업로드대상"],
    [4, 2, "2-1", "WBS-02", "기존 포장 절삭", "CIVIL-WASTE", "폐기물처리비", "경비", "폐아스콘 상차 및 운반", "폐아스콘 임시집하·운반", 1, "식", 10400000, 2000000, 400000, 8000000, 10400000, "처리비 별도 정산 가능", "업로드대상"],
    [5, 1, "3.", "WBS-03", "아스콘 포장", "CIVIL-MATERIAL", "재료비", "재료비", "택코팅 및 아스팔트 유제", "RSC-4, 포장 전 처리", 500, "㎡", 6000, 500000, 2300000, 200000, 3000000, "유제 살포", "업로드대상"],
    [6, 2, "3-1", "WBS-03", "아스콘 포장", "CIVIL-ASCON-PAVING", "아스콘 포장", "재료비", "아스콘 포설", "기층·표층 소규모 포장", 500, "㎡", 96000, 15000000, 28000000, 5000000, 48000000, "주요 공정", "업로드대상"],
    [7, 2, "3-2", "WBS-03", "아스콘 포장", "CIVIL-QUALITY", "품질관리비", "경비", "다짐 및 품질관리", "다짐장비·현장시험", 1, "식", 8400000, 3000000, 0, 5400000, 8400000, "다짐·품질시험", "업로드대상"],
    [8, 1, "4.", "WBS-04", "차선도색 및 마감", "CIVIL-LINE-MARKING", "차선도색", "경비", "차선도색", "백색/황색 실선 및 기호", 1, "식", 12000000, 3000000, 6000000, 3000000, 12000000, "부분통제 포함", "업로드대상"],
    [9, 2, "4-1", "WBS-04", "차선도색 및 마감", "CIVIL-FINISH", "마감공사", "경비", "현장정리 및 마감", "시설물 원상복구·마감", 1, "식", 7800000, 4000000, 1000000, 2800000, 7800000, "준공 전 정리", "업로드대상"],
    [10, 1, "5.", "WBS-05", "정리·검측·준공자료", "CIVIL-DOCUMENT", "준공자료", "경비", "검측 및 준공도서 작성", "검측자료·사진대지·준공서류", 1, "식", 8000000, 5000000, 0, 3000000, 8000000, "준공자료", "업로드대상"],
    [11, 2, "5-1", "WBS-05", "정리·검측·준공자료", "CIVIL-CLEANUP", "현장정리", "경비", "준공청소 및 폐기물 정리", "잔재물 정리·청소", 1, "식", 5200000, 2000000, 700000, 2500000, 5200000, "마무리", "업로드대상"],
]


def _parsed_rows():
    workbook = Workbook()
    worksheet = workbook.active
    worksheet.title = "도급계약내역서"
    worksheet.append(HEADERS)
    for row in ROWS:
        worksheet.append(row)
    payload = BytesIO()
    workbook.save(payload)
    payload.seek(0)
    return parse_contract_budget_excel(payload)["rows"]


def _row(rows, source_row_no):
    return next(row for row in rows if row["source_row_no"] == str(source_row_no))


def test_contract_statement_parser_keeps_all_11_upload_target_rows():
    rows = _parsed_rows()

    assert len(rows) == 11
    assert [row["source_row_no"] for row in rows] == [str(number) for number in range(1, 12)]
    assert [_row(rows, number)["cbs_code"] for number in (7, 9, 10)] == [
        "CIVIL-QUALITY", "CIVIL-FINISH", "CIVIL-DOCUMENT",
    ]
    assert sum(row["amount"] for row in rows) == Decimal("132000000")
    assert sum(row["labor_amount"] for row in rows) == Decimal("46500000")
    assert sum(row["material_amount"] for row in rows) == Decimal("42800000")
    assert sum(row["expense_amount"] for row in rows) == Decimal("42700000")


@pytest.mark.django_db
def test_missing_cbs_rows_are_reported_as_unmatched_not_dropped():
    seed_civil_road_cbs()
    CostItem.objects.filter(code__in=["CIVIL-QUALITY", "CIVIL-FINISH", "CIVIL-DOCUMENT"]).delete()
    rows = _parsed_rows()

    initial, _warnings, stats = _build_budget_initial_from_import_rows(rows)

    assert initial
    assert stats["budget_import_unmatched_rows"] == 3
    assert stats["budget_import_unmatched_amount"] == Decimal("24200000")
    assert stats["budget_import_matched_amount"] == Decimal("107800000")
    assert [row["match_status"] for row in (_row(rows, 7), _row(rows, 9), _row(rows, 10))] == [
        "UNMATCHED_CBS", "UNMATCHED_CBS", "UNMATCHED_CBS",
    ]
    assert [item["source_row_no"] for item in stats["budget_import_unmatched_details"]] == ["7", "9", "10"]


@pytest.mark.django_db
def test_all_rows_import_when_exact_cbs_masters_exist():
    seed_civil_road_cbs()
    rows = _parsed_rows()

    initial, _warnings, stats = _build_budget_initial_from_import_rows(rows)

    assert stats["budget_import_unmatched_rows"] == 0
    assert stats["budget_import_generated_labor_amount"] == Decimal("46500000")
    assert stats["budget_import_generated_material_amount"] == Decimal("42800000")
    assert stats["budget_import_generated_expense_amount"] == Decimal("42700000")
    assert sum(Decimal(str(item["planned_amount"])) for item in initial) == Decimal("132000000")
    assert [_row(rows, number)["match_status"] for number in (7, 9, 10)] == [
        "EXACT_CODE", "EXACT_CODE", "EXACT_CODE",
    ]
    assert all("원본행번호:" in item["note"] for item in initial)


@pytest.mark.django_db
def test_cbs_name_alias_fallback_is_auditable():
    seed_civil_road_cbs()
    CostItem.objects.filter(code="CIVIL-QUALITY").delete()
    rows = [_row(_parsed_rows(), 7)]
    bridge_item = CostItem.objects.get(code="CIVIL-BRIDGE-REPAIR")
    CostItemAlias.objects.create(
        cost_item=bridge_item,
        alias="품질관리비 대체",
        is_primary=False,
    )
    rows[0]["cbs_name"] = "품질관리비 대체"

    _initial, _warnings, stats = _build_budget_initial_from_import_rows(rows)

    assert stats["budget_import_unmatched_rows"] == 0
    assert rows[0]["match_status"] == "ALIAS"
    assert "대체 매칭" in rows[0]["match_reason"]
