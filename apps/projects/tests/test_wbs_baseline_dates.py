from datetime import date

import pytest
from django.contrib.auth import get_user_model
from django.core.exceptions import ValidationError
from django.core.files.uploadedfile import SimpleUploadedFile

from apps.core.rbac.models import UserProfile
from apps.cost.models import CostItem
from apps.field.web_views import _ensure_progress_tasks_for_project
from apps.projects.hq_views import (
    _build_wbs_initial_from_import_rows,
    hq_project_new,
    resolve_wbs_baseline_dates,
)
from apps.projects.models import Project, WBSItem
from apps.projects.tests.test_project_import_commit import _build_request
from apps.schedule.models import ScheduleTask


def _new_project_payload(cost_item_id, *, start_date="2026-08-14", end_date="2026-09-13"):
    return {
        "action": "save_project",
        "name": "WBS 기준선 날짜 검증 공사",
        "project_type": "civil",
        "status": "draft",
        "client_name": "발주처",
        "site_address": "현장 주소",
        "start_date": start_date,
        "end_date": end_date,
        "contract_amount": "132000000",
        "contract_start_date": start_date,
        "contract_end_date": end_date,
        "contract_file": SimpleUploadedFile("contract.pdf", b"%PDF-1.4\n"),
        "budget-TOTAL_FORMS": "1",
        "budget-INITIAL_FORMS": "0",
        "budget-MIN_NUM_FORMS": "0",
        "budget-MAX_NUM_FORMS": "1000",
        "budget-0-category": "LABOR",
        "budget-0-cost_item": str(cost_item_id),
        "budget-0-name": "현장 준비 노무비",
        "budget-0-planned_amount": "132000000",
        "budget-0-note": "",
        "wbs-TOTAL_FORMS": "2",
        "wbs-INITIAL_FORMS": "0",
        "wbs-MIN_NUM_FORMS": "0",
        "wbs-MAX_NUM_FORMS": "1000",
        "wbs-0-name": "WBS-01 현장 준비 및 안전관리",
        "wbs-0-parent": "",
        "wbs-0-weight": "50.00",
        "wbs-0-sort_order": "1",
        "wbs-0-plan_start_date": "",
        "wbs-0-plan_end_date": "",
        "wbs-1-name": "WBS-02 기존 포장 절삭",
        "wbs-1-parent": "",
        "wbs-1-weight": "50.00",
        "wbs-1-sort_order": "2",
        "wbs-1-plan_start_date": "",
        "wbs-1-plan_end_date": "",
    }


@pytest.mark.django_db
def test_imported_wbs_baseline_defaults_dates_from_project_when_excel_dates_missing():
    user = get_user_model().objects.create_user(username="wbs-date-hq", password="pass")
    UserProfile.objects.create(user=user, role="hq")
    cost_item = CostItem.objects.create(code="WBS-DATE-LABOR", name="노무비", category="labor")

    response = hq_project_new(_build_request(user, _new_project_payload(cost_item.id)))

    assert response.status_code == 302
    project = Project.objects.get(name="WBS 기준선 날짜 검증 공사")
    rows = list(WBSItem.objects.filter(project=project).order_by("sort_order", "id"))
    assert len(rows) == 2
    assert {(row.plan_start_date, row.plan_end_date) for row in rows} == {
        (date(2026, 8, 14), date(2026, 9, 13))
    }
    assert [row.name for row in rows] == [
        "WBS-01 현장 준비 및 안전관리",
        "WBS-02 기존 포장 절삭",
    ]


def test_imported_wbs_baseline_preserves_explicit_wbs_dates():
    project = Project(start_date=date(2026, 8, 14), end_date=date(2026, 9, 13))
    rows = [
        {
            "name": "WBS-01 현장 준비 및 안전관리",
            "weight": "100",
            "plan_start_date": date(2026, 8, 14),
            "plan_end_date": date(2026, 8, 17),
            "warnings": [],
        }
    ]

    initial, warnings = _build_wbs_initial_from_import_rows(rows, project=project)

    assert warnings == []
    assert initial[0]["plan_start_date"] == date(2026, 8, 14)
    assert initial[0]["plan_end_date"] == date(2026, 8, 17)
    assert initial[0]["wbs_date_source"] == "EXCEL"


def test_imported_wbs_without_row_dates_requires_project_dates():
    with pytest.raises(ValidationError, match="WBS 기준선 기간"):
        resolve_wbs_baseline_dates(
            {"plan_start_date": None, "plan_end_date": None}, Project()
        )


@pytest.mark.django_db
def test_project_registration_blocks_undated_wbs_when_project_dates_are_missing():
    user = get_user_model().objects.create_user(username="wbs-date-missing-hq", password="pass")
    UserProfile.objects.create(user=user, role="hq")
    cost_item = CostItem.objects.create(code="WBS-DATE-BLOCK", name="노무비", category="labor")
    payload = _new_project_payload(cost_item.id, start_date="", end_date="")

    response = hq_project_new(_build_request(user, payload))

    assert response.status_code == 200
    assert not Project.objects.filter(name="WBS 기준선 날짜 검증 공사").exists()
    assert "WBS 기준선 기간" in response.content.decode("utf-8")


@pytest.mark.django_db
def test_schedule_tasks_created_from_wbs_have_project_fallback_dates():
    project = Project.objects.create(
        code="WBS-DATE-SCHEDULE-001",
        name="일정 날짜 검증 공사",
        project_type="civil",
        status="draft",
        start_date=date(2026, 8, 14),
        end_date=date(2026, 9, 13),
    )
    WBSItem.objects.create(
        project=project,
        name="아스콘 포장",
        weight="100.00",
        sort_order=1,
        is_baseline=True,
    )

    _, tasks = _ensure_progress_tasks_for_project(project)

    assert len(tasks) == 1
    task = ScheduleTask.objects.get(plan__project=project, name="아스콘 포장")
    assert task.start_date == project.start_date
    assert task.end_date == project.end_date
