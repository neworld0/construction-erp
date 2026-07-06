from io import StringIO
from pathlib import Path

import pytest
from django.core.management import call_command
from django.core.management.base import CommandError

from apps.cost.models import CostItem, CostItemCategory


def _write_csv(path: Path, content: str, *, encoding="utf-8-sig"):
    path.write_text(content, encoding=encoding, newline="")


@pytest.mark.django_db
def test_import_cbs_costitems_creates_korean_names_from_utf8_sig(tmp_path):
    csv_path = tmp_path / "cbs.csv"
    _write_csv(
        csv_path,
        "code,name,cost_type,work_type\n"
        "CB-L-99-001,현장 잡부/정리 인건비,L,99\n"
        "CB-M-07-001,토사(일반),M,07\n",
    )
    stdout = StringIO()

    call_command("import_cbs_costitems", path=str(csv_path), stdout=stdout)

    labor = CostItem.objects.get(code="CB-L-99-001")
    material = CostItem.objects.get(code="CB-M-07-001")
    assert labor.name == "현장 잡부/정리 인건비"
    assert labor.category == CostItemCategory.LABOR
    assert material.name == "토사(일반)"
    assert material.category == CostItemCategory.MATERIAL
    output = stdout.getvalue()
    assert "encoding: utf-8-sig" in output
    assert "sample names: 현장 잡부/정리 인건비, 토사(일반)" in output


@pytest.mark.django_db
def test_import_cbs_costitems_is_idempotent_without_duplicates(tmp_path):
    csv_path = tmp_path / "cbs.csv"
    _write_csv(
        csv_path,
        "code,name,cost_type,work_type\n"
        "CB-E-99-001,운반비(공통),E,99\n",
    )

    call_command("import_cbs_costitems", path=str(csv_path))
    call_command("import_cbs_costitems", path=str(csv_path))

    assert CostItem.objects.filter(code="CB-E-99-001").count() == 1


@pytest.mark.django_db
def test_import_cbs_costitems_skips_existing_without_update_flag(tmp_path):
    CostItem.objects.create(
        code="CB-S-04-001",
        name="기존 하도급",
        category=CostItemCategory.SUBCON,
        cost_type="S",
        work_type="04",
    )
    csv_path = tmp_path / "cbs.csv"
    _write_csv(
        csv_path,
        "code,name,cost_type,work_type\n"
        "CB-S-04-001,포장 공사 하도급,S,04\n",
    )

    call_command("import_cbs_costitems", path=str(csv_path))

    item = CostItem.objects.get(code="CB-S-04-001")
    assert item.name == "기존 하도급"


@pytest.mark.django_db
def test_import_cbs_costitems_requires_code_and_name_headers(tmp_path):
    csv_path = tmp_path / "cbs.csv"
    _write_csv(
        csv_path,
        "cost_type,work_type\n"
        "L,99\n",
    )

    with pytest.raises(CommandError) as exc:
        call_command("import_cbs_costitems", path=str(csv_path))

    assert "필수 헤더가 누락되었습니다" in str(exc.value)
