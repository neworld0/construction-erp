from django.contrib.auth import get_user_model
from django.core.files.uploadedfile import SimpleUploadedFile

import pytest

from apps.core.rbac.models import UserProfile
from apps.cost.models import CostItem
from apps.projects.hq_views import hq_project_new
from apps.projects.models import Project
from apps.projects.tests.test_project_import_commit import _build_request


@pytest.mark.django_db
def test_hq_project_new_manual_create_generates_project_code():
    user = get_user_model().objects.create_user(username="manual-hq", password="pass")
    UserProfile.objects.create(user=user, role="hq")

    cost_item = CostItem.objects.create(
        code="MANUAL-001",
        name="수동 예산",
        category="labor",
    )

    request = _build_request(
        user,
        {
            "action": "save_project",
            "name": "수동 등록 공사",
            "project_type": "civil",
            "status": "draft",
            "client_name": "발주처",
            "site_address": "현장 주소",
            "start_date": "2026-04-01",
            "end_date": "2026-07-29",
            "contract_amount": "1000000",
            "contract_start_date": "2026-04-01",
            "contract_end_date": "2026-07-29",
            "contract_file": SimpleUploadedFile(
                "contract.pdf",
                b"%PDF-1.4\n",
                content_type="application/pdf",
            ),
            "budget-TOTAL_FORMS": "1",
            "budget-INITIAL_FORMS": "0",
            "budget-MIN_NUM_FORMS": "0",
            "budget-MAX_NUM_FORMS": "1000",
            "budget-0-category": "LABOR",
            "budget-0-cost_item": str(cost_item.id),
            "budget-0-name": "수동 예산",
            "budget-0-planned_amount": "1000000",
            "budget-0-note": "",
            "wbs-TOTAL_FORMS": "1",
            "wbs-INITIAL_FORMS": "0",
            "wbs-MIN_NUM_FORMS": "0",
            "wbs-MAX_NUM_FORMS": "1000",
            "wbs-0-name": "착공 준비",
            "wbs-0-parent": "",
            "wbs-0-weight": "100.00",
            "wbs-0-sort_order": "1",
            "wbs-0-plan_start_date": "2026-04-01",
            "wbs-0-plan_end_date": "2026-07-29",
        },
    )

    response = hq_project_new(request)

    project = Project.objects.get(name="수동 등록 공사")
    assert project.code
    assert project.code.startswith("C-")
    assert response.status_code in (301, 302)


@pytest.mark.django_db
def test_hq_project_new_does_not_duplicate_empty_project_code():
    Project.objects.create(
        code="",
        name="기존 빈 코드 프로젝트",
        project_type="civil",
        status="draft",
    )

    user = get_user_model().objects.create_user(username="manual-hq2", password="pass")
    UserProfile.objects.create(user=user, role="hq")

    cost_item = CostItem.objects.create(
        code="MANUAL-002",
        name="수동 예산2",
        category="labor",
    )

    request = _build_request(
        user,
        {
            "action": "save_project",
            "name": "중복 빈 코드 방지 공사",
            "project_type": "civil",
            "status": "draft",
            "client_name": "발주처",
            "site_address": "현장 주소",
            "start_date": "2026-04-01",
            "end_date": "2026-07-29",
            "contract_amount": "1000000",
            "contract_start_date": "2026-04-01",
            "contract_end_date": "2026-07-29",
            "contract_file": SimpleUploadedFile(
                "contract.pdf",
                b"%PDF-1.4\n",
                content_type="application/pdf",
            ),
            "budget-TOTAL_FORMS": "1",
            "budget-INITIAL_FORMS": "0",
            "budget-MIN_NUM_FORMS": "0",
            "budget-MAX_NUM_FORMS": "1000",
            "budget-0-category": "LABOR",
            "budget-0-cost_item": str(cost_item.id),
            "budget-0-name": "수동 예산2",
            "budget-0-planned_amount": "1000000",
            "budget-0-note": "",
            "wbs-TOTAL_FORMS": "1",
            "wbs-INITIAL_FORMS": "0",
            "wbs-MIN_NUM_FORMS": "0",
            "wbs-MAX_NUM_FORMS": "1000",
            "wbs-0-name": "착공 준비",
            "wbs-0-parent": "",
            "wbs-0-weight": "100.00",
            "wbs-0-sort_order": "1",
            "wbs-0-plan_start_date": "2026-04-01",
            "wbs-0-plan_end_date": "2026-07-29",
        },
    )

    response = hq_project_new(request)

    project = Project.objects.get(name="중복 빈 코드 방지 공사")
    assert project.code
    assert project.code != ""
    assert project.code.startswith("C-")
    assert response.status_code in (301, 302)
