from decimal import Decimal

import pytest
from django.contrib.auth import get_user_model
from django.contrib.messages import get_messages
from django.contrib.messages.storage.fallback import FallbackStorage
from django.contrib.sessions.middleware import SessionMiddleware
from django.test import RequestFactory

from apps.core.rbac.models import UserProfile
from apps.cost.models import CostItem
from apps.cost.seed_civil_road_cbs import seed_civil_road_cbs
from apps.projects.hq_views import hq_project_detail
from apps.projects.models import (
    BudgetCategory,
    BudgetItem,
    Project,
    ProjectContract,
    ProjectStatus,
    WBSItem,
)


def _build_request(user, path, data=None, method="post"):
    factory = RequestFactory()
    request = getattr(factory, method.lower())(path, data or {})
    SessionMiddleware(lambda req: None).process_request(request)
    request.session.save()
    setattr(request, "_messages", FallbackStorage(request))
    request.user = user
    return request


def _messages_text(request):
    return [str(message) for message in get_messages(request)]


def _create_project(name="예산 저장 테스트 공사"):
    project = Project.objects.create(
        code="PRJ-BUDGET-SAVE-001",
        name=name,
        project_type="civil",
        status=ProjectStatus.DRAFT,
        start_date="2026-05-01",
        end_date="2026-05-31",
    )
    ProjectContract.objects.create(
        project=project,
        contract_amount=Decimal("10000"),
        contract_start_date="2026-05-01",
        contract_end_date="2026-05-31",
        status="approved",
    )
    return project


def _hq_user(username="budget-save-hq"):
    user = get_user_model().objects.create_user(username=username, password="pass")
    UserProfile.objects.create(user=user, role="hq")
    return user


def _detail_path(project):
    return f"/app/hq/projects/{project.id}/"


@pytest.mark.django_db
def test_hq_project_detail_displays_persisted_project_code():
    user = _hq_user("project-code-display-hq")
    project = _create_project("프로젝트 코드 표시 공사")
    project.code = "LOCAL-OPS-20260814-001"
    project.save(update_fields=["code"])

    request = _build_request(user, _detail_path(project), method="get")
    response = hq_project_detail(request, project.id)
    content = response.content.decode("utf-8")

    assert response.status_code == 200
    assert "프로젝트 코드" in content
    assert project.code in content


@pytest.mark.django_db
def test_budget_save_invalid_form_does_not_fall_through_to_wbs_save():
    seed_civil_road_cbs()
    user = _hq_user("budget-invalid-hq")
    project = _create_project("예산 오류 확인 공사")
    expense_cbs = CostItem.objects.get(code="CIVIL-EXPENSE")
    expense_item = BudgetItem.objects.create(
        project=project,
        cost_item=expense_cbs,
        category=BudgetCategory.OTHER,
        name="경비",
        planned_amount=1000,
    )
    wbs = WBSItem.objects.create(
        project=project,
        name="기존 WBS",
        weight=Decimal("100.00"),
        sort_order=1,
    )

    data = {
        "action": "save_budget",
        "budget-TOTAL_FORMS": "1",
        "budget-INITIAL_FORMS": "1",
        "budget-MIN_NUM_FORMS": "0",
        "budget-MAX_NUM_FORMS": "1000",
        "budget-0-id": str(expense_item.id),
        "budget-0-category": "OTHER",
        "budget-0-cost_item": "",
        "budget-0-name": "잘못된 예산",
        "budget-0-planned_amount": "9999",
        "budget-0-note": "",
        "labor-TOTAL_FORMS": "0",
        "labor-INITIAL_FORMS": "0",
        "labor-MIN_NUM_FORMS": "0",
        "labor-MAX_NUM_FORMS": "1000",
        "wbs-TOTAL_FORMS": "1",
        "wbs-INITIAL_FORMS": "1",
        "wbs-MIN_NUM_FORMS": "0",
        "wbs-MAX_NUM_FORMS": "1000",
        "wbs-0-id": str(wbs.id),
        "wbs-0-name": "변경된 WBS",
        "wbs-0-parent": "",
        "wbs-0-weight": "100.00",
        "wbs-0-sort_order": "1",
        "wbs-0-plan_start_date": "",
        "wbs-0-plan_end_date": "",
    }
    request = _build_request(user, _detail_path(project), data=data)
    response = hq_project_detail(request, project.id)
    content = response.content.decode("utf-8")

    expense_item.refresh_from_db()
    wbs.refresh_from_db()

    assert response.status_code == 200
    assert expense_item.planned_amount == 1000
    assert wbs.name == "기존 WBS"
    assert "예산 기준선 저장에 실패했습니다" in content
    assert "cost_item" in content
    assert "WBS 기준선을 저장했습니다." not in content


@pytest.mark.django_db
def test_budget_delete_checked_row_is_persisted():
    seed_civil_road_cbs()
    user = _hq_user("budget-delete-hq")
    project = _create_project("예산 삭제 공사")
    expense_cbs = CostItem.objects.get(code="CIVIL-EXPENSE")
    expense_item = BudgetItem.objects.create(
        project=project,
        cost_item=expense_cbs,
        category=BudgetCategory.OTHER,
        name="삭제 대상",
        planned_amount=1000,
    )

    data = {
        "action": "save_budget",
        "budget-TOTAL_FORMS": "1",
        "budget-INITIAL_FORMS": "1",
        "budget-MIN_NUM_FORMS": "0",
        "budget-MAX_NUM_FORMS": "1000",
        "budget-0-id": str(expense_item.id),
        "budget-0-category": "OTHER",
        "budget-0-cost_item": str(expense_cbs.id),
        "budget-0-name": "삭제 대상",
        "budget-0-planned_amount": "1000",
        "budget-0-note": "",
        "budget-0-DELETE": "on",
        "labor-TOTAL_FORMS": "0",
        "labor-INITIAL_FORMS": "0",
        "labor-MIN_NUM_FORMS": "0",
        "labor-MAX_NUM_FORMS": "1000",
    }
    request = _build_request(user, _detail_path(project), data=data)
    response = hq_project_detail(request, project.id)

    assert response.status_code in (301, 302)
    assert not BudgetItem.objects.filter(id=expense_item.id).exists()


@pytest.mark.django_db
def test_budget_edit_existing_row_is_persisted():
    seed_civil_road_cbs()
    user = _hq_user("budget-edit-hq")
    project = _create_project("예산 수정 공사")

    expense = CostItem.objects.get(code="CIVIL-EXPENSE")
    item = BudgetItem.objects.create(
        project=project,
        cost_item=expense,
        category=BudgetCategory.OTHER,
        name="경비",
        planned_amount=1000,
    )

    data = {
        "action": "save_budget",
        "budget-TOTAL_FORMS": "1",
        "budget-INITIAL_FORMS": "1",
        "budget-MIN_NUM_FORMS": "0",
        "budget-MAX_NUM_FORMS": "1000",
        "budget-0-id": str(item.id),
        "budget-0-category": "OTHER",
        "budget-0-cost_item": str(expense.id),
        "budget-0-name": "경비",
        "budget-0-planned_amount": "2000",
        "budget-0-note": "",
        "labor-TOTAL_FORMS": "0",
        "labor-INITIAL_FORMS": "0",
        "labor-MIN_NUM_FORMS": "0",
        "labor-MAX_NUM_FORMS": "1000",
    }
    save_request = _build_request(user, _detail_path(project), data=data)
    save_response = hq_project_detail(save_request, project.id)
    get_request = _build_request(user, _detail_path(project), method="get")
    get_response = hq_project_detail(get_request, project.id)
    content = get_response.content.decode("utf-8")

    item.refresh_from_db()
    assert save_response.status_code in (301, 302)
    assert item.planned_amount == 2000
    assert "2,000" in content


@pytest.mark.django_db
def test_budget_delete_and_add_corrected_row():
    seed_civil_road_cbs()
    user = _hq_user("budget-correct-hq")
    project = _create_project("예산 정정 공사")

    expense = CostItem.objects.get(code="CIVIL-EXPENSE")
    labor = CostItem.objects.get(code="CIVIL-LABOR")
    old_item = BudgetItem.objects.create(
        project=project,
        cost_item=expense,
        category=BudgetCategory.OTHER,
        name="경비",
        planned_amount=1000,
    )

    data = {
        "action": "save_budget",
        "budget-TOTAL_FORMS": "2",
        "budget-INITIAL_FORMS": "1",
        "budget-MIN_NUM_FORMS": "0",
        "budget-MAX_NUM_FORMS": "1000",
        "budget-0-id": str(old_item.id),
        "budget-0-category": "OTHER",
        "budget-0-cost_item": str(expense.id),
        "budget-0-name": "경비",
        "budget-0-planned_amount": "1000",
        "budget-0-note": "",
        "budget-0-DELETE": "on",
        "budget-1-category": "LABOR",
        "budget-1-cost_item": str(labor.id),
        "budget-1-name": "정정 노무비",
        "budget-1-planned_amount": "2500",
        "budget-1-note": "",
        "labor-TOTAL_FORMS": "0",
        "labor-INITIAL_FORMS": "0",
        "labor-MIN_NUM_FORMS": "0",
        "labor-MAX_NUM_FORMS": "1000",
    }
    response = hq_project_detail(_build_request(user, _detail_path(project), data=data), project.id)

    assert response.status_code in (301, 302)
    assert not BudgetItem.objects.filter(id=old_item.id).exists()
    corrected = BudgetItem.objects.get(project=project, name="정정 노무비")
    assert corrected.planned_amount == 2500


@pytest.mark.django_db
def test_detail_template_renders_hidden_ids_for_budget_formsets():
    seed_civil_road_cbs()
    user = _hq_user("budget-hidden-hq")
    project = _create_project("예산 히든 필드 공사")

    expense = CostItem.objects.get(code="CIVIL-EXPENSE")
    labor = CostItem.objects.get(code="CIVIL-LABOR")
    BudgetItem.objects.create(
        project=project,
        cost_item=expense,
        category=BudgetCategory.OTHER,
        name="경비",
        planned_amount=1000,
    )
    BudgetItem.objects.create(
        project=project,
        cost_item=labor,
        category=BudgetCategory.LABOR,
        name="노무비",
        planned_amount=2000,
    )

    response = hq_project_detail(
        _build_request(user, _detail_path(project), method="get"),
        project.id,
    )
    content = response.content.decode("utf-8")

    assert 'name="budget-0-id"' in content
    assert 'name="labor-0-id"' in content


@pytest.mark.django_db
def test_budget_save_invalid_post_shows_bound_values_but_no_db_change():
    seed_civil_road_cbs()
    user = _hq_user("budget-bound-hq")
    project = _create_project("예산 바운드 공사")

    expense = CostItem.objects.get(code="CIVIL-EXPENSE")
    item = BudgetItem.objects.create(
        project=project,
        cost_item=expense,
        category=BudgetCategory.OTHER,
        name="경비",
        planned_amount=1000,
    )

    data = {
        "action": "save_budget",
        "budget-TOTAL_FORMS": "1",
        "budget-INITIAL_FORMS": "1",
        "budget-MIN_NUM_FORMS": "0",
        "budget-MAX_NUM_FORMS": "1000",
        "budget-0-id": str(item.id),
        "budget-0-category": "OTHER",
        "budget-0-cost_item": "",
        "budget-0-name": "경비",
        "budget-0-planned_amount": "9999",
        "budget-0-note": "",
        "labor-TOTAL_FORMS": "0",
        "labor-INITIAL_FORMS": "0",
        "labor-MIN_NUM_FORMS": "0",
        "labor-MAX_NUM_FORMS": "1000",
    }
    request = _build_request(user, _detail_path(project), data=data)
    response = hq_project_detail(request, project.id)
    content = response.content.decode("utf-8")
    item.refresh_from_db()

    assert response.status_code == 200
    assert "value=\"9999\"" in content
    assert item.planned_amount == 1000
    assert "예산 기준선 저장에 실패했습니다" in content
