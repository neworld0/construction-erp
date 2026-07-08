import json
from datetime import date
from decimal import Decimal

import pytest
from django.contrib.auth import get_user_model
from django.test import Client
from django.utils import timezone

from apps.audit.constants import DRAFT_SAVE, SUBMIT
from apps.audit.models import AuditLog
from apps.closing.models import ProjectClose, ProjectCloseStatus
from apps.closing.services import close_month
from apps.core.models import ApprovalRequest, ApprovalStatus
from apps.core.rbac.models import ProjectAssignment, Role, UserProfile
from apps.cost.models import CostItem, CostItemCategory
from apps.projects.models import BudgetCategory, BudgetItem, Project, WBSItem
from apps.schedule.models import DailyProgress, SchedulePlan, ScheduleTask


@pytest.fixture(autouse=True)
def _disable_two_factor_enforce(settings):
    settings.MIDDLEWARE = [
        middleware
        for middleware in settings.MIDDLEWARE
        if middleware != "apps.core.middleware.two_factor_enforce.TwoFactorEnforceMiddleware"
    ]


def _user(role, username):
    user = get_user_model().objects.create_user(username=username, password="pass")
    UserProfile.objects.create(user=user, role=role)
    return user


def _client(user):
    client = Client()
    client.force_login(user)
    return client


def _project(code="AUDIT7-PROJ", name="AUDIT7 실제 현장"):
    return Project.objects.create(
        code=code,
        name=name,
        project_type="civil",
        status="active",
    )


def _assign_field_to_project(field_user, project):
    return ProjectAssignment.objects.create(user=field_user, project=project, is_active=True)


def _create_cbs_budget(project, *, code="AUDIT7-CBS-PAVING", name="포장 CBS"):
    cost_item = CostItem.objects.create(
        code=code,
        name=name,
        category=CostItemCategory.LABOR,
        cost_type="L",
        work_type="08",
        is_direct=True,
        is_active=True,
    )
    budget_item = BudgetItem.objects.create(
        project=project,
        cost_item=cost_item,
        category=BudgetCategory.LABOR,
        name=f"{name} 예산",
        planned_amount=1000000,
        note="AUDIT7 진행률 E2E 예산",
    )
    return cost_item, budget_item


def _create_wbs_item(
    project,
    *,
    name="포장공사",
    weight=Decimal("63.37"),
    sort_order=1,
    is_baseline=True,
    start=None,
    end=None,
):
    return WBSItem.objects.create(
        project=project,
        name=name,
        weight=weight,
        sort_order=sort_order,
        plan_start_date=start,
        plan_end_date=end,
        is_baseline=is_baseline,
    )


def _configured_project(*, field_user, code="AUDIT7-PROJ", wbs_name="포장공사"):
    project = _project(code=code)
    _assign_field_to_project(field_user, project)
    _create_cbs_budget(project, code=f"{code}-CBS")
    wbs = _create_wbs_item(project, name=wbs_name)
    return project, wbs


def _progress_url(project):
    return f"/app/field/?tab=progress&project_id={project.id}"


def _draft_payload(project, task, *, progress_percent="12.5", note="현장 진행률 메모"):
    return {
        "tab": "progress",
        "project_id": str(project.id),
        "action": "draft",
        "task_id": str(task.id),
        "report_date": timezone.localdate().isoformat(),
        "progress_percent": progress_percent,
        "note": note,
    }


def _submit_payload(project, progress):
    return {
        "tab": "progress",
        "project_id": str(project.id),
        "action": "submit",
        "progress_id": str(progress.id),
    }


def _prepare_progress_task(client, project, wbs_name):
    response = client.get(_progress_url(project))
    assert response.status_code == 200
    plan = SchedulePlan.objects.get(project=project, is_active=True)
    task = ScheduleTask.objects.get(plan=plan, name=wbs_name)
    return response, plan, task


def _audit_payload():
    rows = list(
        AuditLog.objects.filter(object_type="DAILY_PROGRESS")
        .values("action", "object_type", "object_id", "before_json", "after_json", "meta_json")
        .order_by("id")
    )
    return json.dumps(rows, ensure_ascii=False, default=str)


def _assert_no_mojibake(text):
    bad_tokens = [chr(code) for code in (0xFFFD, 0x7644, 0x71C1, 0x6C83, 0x7344, 0x4EA6, 0x6930, 0x8881, 0x91AB, 0x5360)]
    for token in bad_tokens:
        assert token not in text


@pytest.mark.django_db
def test_audit7_project_wbs_work_items_are_available_in_field_progress_dropdown():
    field_user = _user(Role.FIELD, "audit7-field-dropdown")
    project, wbs = _configured_project(field_user=field_user, code="AUDIT7-DROPDOWN")
    client = _client(field_user)

    response, plan, task = _prepare_progress_task(client, project, wbs.name)
    content = response.content.decode("utf-8")

    assert "오늘 진행률 입력" in content
    assert 'id="task_id"' in content
    assert f'value="{task.id}"' in content
    assert "포장공사 / 63.370%" in content
    assert "선택 가능한 작업이 없습니다" not in content
    assert task.plan == plan
    assert task.name == wbs.name
    assert task.weight_percent == Decimal("63.370")
    _assert_no_mojibake(content)


@pytest.mark.django_db
def test_audit7_field_can_save_draft_progress_for_project_work_item():
    field_user = _user(Role.FIELD, "audit7-field-draft")
    project, wbs = _configured_project(field_user=field_user, code="AUDIT7-DRAFT")
    client = _client(field_user)
    _response, plan, task = _prepare_progress_task(client, project, wbs.name)

    response = client.post("/app/field/", _draft_payload(project, task))

    assert response.status_code == 302
    progress = DailyProgress.objects.get(project=project, task=task, reporter=field_user)
    assert progress.plan == plan
    assert progress.status == "draft"
    assert progress.progress_percent == Decimal("12.500")
    assert progress.note == "현장 진행률 메모"
    assert AuditLog.objects.filter(
        action=DRAFT_SAVE,
        object_type="DAILY_PROGRESS",
        object_id=progress.id,
        project=project,
        actor=field_user,
    ).exists()


@pytest.mark.django_db
def test_audit7_field_can_submit_progress_for_project_work_item():
    hq_user = _user(Role.HQ, "audit7-hq-progress-view")
    field_user = _user(Role.FIELD, "audit7-field-submit")
    project, wbs = _configured_project(field_user=field_user, code="AUDIT7-SUBMIT")
    field_client = _client(field_user)
    _response, _plan, task = _prepare_progress_task(field_client, project, wbs.name)
    field_client.post("/app/field/", _draft_payload(project, task, progress_percent="25.0"))
    progress = DailyProgress.objects.get(project=project, task=task, reporter=field_user)

    response = field_client.post("/app/field/", _submit_payload(project, progress))

    assert response.status_code == 302
    progress.refresh_from_db()
    assert progress.status == "submitted"
    assert progress.project == project
    assert progress.task == task
    assert ApprovalRequest.objects.filter(
        object_type="DAILY_PROGRESS",
        object_id=progress.id,
        status=ApprovalStatus.SUBMITTED,
        submitted_by=field_user,
    ).exists()
    assert AuditLog.objects.filter(
        action=SUBMIT,
        object_type="DAILY_PROGRESS",
        object_id=progress.id,
        project=project,
        actor=field_user,
    ).exists()

    hq_response = _client(hq_user).get(f"/app/hq/progress/{progress.id}/")
    assert hq_response.status_code == 200
    hq_content = hq_response.content.decode("utf-8")
    assert "포장공사" in hq_content
    assert "25.0%" in hq_content


@pytest.mark.django_db
def test_audit7_field_progress_without_project_work_items_shows_clear_no_work_items_state():
    field_user = _user(Role.FIELD, "audit7-field-no-work")
    project = _project(code="AUDIT7-NO-WBS")
    _assign_field_to_project(field_user, project)
    client = _client(field_user)

    response = client.get(_progress_url(project))

    assert response.status_code == 200
    content = response.content.decode("utf-8")
    assert "WBS 기준선 작업이 없습니다" in content
    assert "선택 가능한 작업이 없습니다" in content
    assert 'id="progress_draft_btn" disabled' in content
    assert 'id="progress_submit_btn" disabled' in content


@pytest.mark.django_db
def test_audit7_field_cannot_post_progress_with_work_item_from_other_project():
    field_user = _user(Role.FIELD, "audit7-field-cross-task")
    project_a, wbs_a = _configured_project(field_user=field_user, code="AUDIT7-CROSS-A")
    project_b = _project(code="AUDIT7-CROSS-B", name="AUDIT7 다른 현장")
    _create_wbs_item(project_b, name="타 현장 작업")
    client = _client(field_user)
    _prepare_progress_task(client, project_a, wbs_a.name)
    other_plan = SchedulePlan.objects.create(project=project_b, version_no=1, name="Other", is_active=True)
    other_task = ScheduleTask.objects.create(
        plan=other_plan,
        name="타 현장 작업",
        weight_percent=Decimal("10.000"),
        sort_order=1,
        is_active=True,
    )

    response = client.post("/app/field/", _draft_payload(project_a, other_task))

    assert response.status_code == 200
    content = response.content.decode("utf-8")
    assert "작업을 찾을 수 없습니다" in content
    assert DailyProgress.objects.filter(project=project_a, reporter=field_user).count() == 0
    assert not AuditLog.objects.filter(action=DRAFT_SAVE, object_type="DAILY_PROGRESS").exists()


@pytest.mark.django_db
def test_audit7_field_cannot_access_unassigned_project_progress():
    field_user = _user(Role.FIELD, "audit7-field-unassigned")
    assigned_project, _assigned_wbs = _configured_project(
        field_user=field_user,
        code="AUDIT7-ASSIGNED",
        wbs_name="접근 가능 작업",
    )
    unassigned_project = _project(code="AUDIT7-UNASSIGNED", name="AUDIT7 비공개 현장")
    _create_wbs_item(unassigned_project, name="비공개 작업")
    client = _client(field_user)

    response = client.get(_progress_url(unassigned_project))

    assert response.status_code == 200
    content = response.content.decode("utf-8")
    assert "선택한 프로젝트 접근 권한이 없어" in content
    assert "비공개 작업" not in content
    assert "접근 가능 작업" in content
    assert SchedulePlan.objects.filter(project=assigned_project).exists()
    assert not SchedulePlan.objects.filter(project=unassigned_project).exists()


@pytest.mark.django_db
def test_audit7_field_cannot_save_or_submit_progress_in_closed_month():
    hq_user = _user(Role.HQ, "audit7-hq-close-month")
    field_user = _user(Role.FIELD, "audit7-field-closed-month")
    project, wbs = _configured_project(field_user=field_user, code="AUDIT7-CLOSED-MONTH")
    client = _client(field_user)
    _response, _plan, task = _prepare_progress_task(client, project, wbs.name)
    today = timezone.localdate()
    close_month(today.year, today.month, hq_user, note="AUDIT7 closed month")

    response = client.post("/app/field/", _draft_payload(project, task, progress_percent="10.0"))

    assert response.status_code == 200
    content = response.content.decode("utf-8")
    assert "마감되었습니다" in content
    assert DailyProgress.objects.filter(project=project, reporter=field_user).count() == 0


@pytest.mark.django_db
def test_audit7_field_cannot_modify_progress_after_project_closed():
    field_user = _user(Role.FIELD, "audit7-field-closed-project")
    project, wbs = _configured_project(field_user=field_user, code="AUDIT7-CLOSED-PROJECT")
    client = _client(field_user)
    _response, _plan, task = _prepare_progress_task(client, project, wbs.name)
    client.post("/app/field/", _draft_payload(project, task, progress_percent="10.0"))
    progress = DailyProgress.objects.get(project=project, task=task, reporter=field_user)
    ProjectClose.objects.create(project=project, status=ProjectCloseStatus.CLOSED)

    response = client.post("/app/field/", _submit_payload(project, progress))

    assert response.status_code == 200
    progress.refresh_from_db()
    assert progress.status == "draft"
    assert "프로젝트가 마감되었습니다" in response.content.decode("utf-8")


@pytest.mark.django_db
def test_audit7_progress_audit_logs_are_recorded_without_sensitive_or_mojibake_payload():
    field_user = _user(Role.FIELD, "audit7-field-audit")
    project, wbs = _configured_project(
        field_user=field_user,
        code="AUDIT7-AUDIT",
        wbs_name="흙터파기",
    )
    client = _client(field_user)
    _response, _plan, task = _prepare_progress_task(client, project, wbs.name)
    client.post("/app/field/", _draft_payload(project, task, progress_percent="15.0", note="흙터파기 진행"))
    progress = DailyProgress.objects.get(project=project, task=task, reporter=field_user)
    client.post("/app/field/", _submit_payload(project, progress))

    payload = _audit_payload()
    assert DRAFT_SAVE in payload
    assert SUBMIT in payload
    assert "흙터파기" not in payload
    assert "enc1:" not in payload
    _assert_no_mojibake(payload)


@pytest.mark.django_db
def test_audit7_korean_project_and_work_item_names_render_without_mojibake():
    field_user = _user(Role.FIELD, "audit7-field-korean")
    project = _project(code="AUDIT7-KOREAN", name="AUDIT7 한글 현장")
    _assign_field_to_project(field_user, project)
    _create_cbs_budget(project, code="AUDIT7-KOREAN-CBS", name="되메우기 CBS")
    _create_wbs_item(project, name="되메우기", weight=Decimal("20.00"))
    client = _client(field_user)

    response = client.get(_progress_url(project))

    assert response.status_code == 200
    content = response.content.decode("utf-8")
    assert "AUDIT7 한글 현장" in content
    assert "되메우기" in content
    _assert_no_mojibake(content)
