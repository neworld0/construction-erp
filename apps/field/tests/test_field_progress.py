from datetime import date
from decimal import Decimal

import pytest
from django.contrib.auth import get_user_model
from django.test import Client
from django.utils import timezone

from apps.core.rbac.models import LegalEntity, LegalEntityAccessScope, ProjectAssignment, UserLegalEntityMembership, UserProfile
from apps.projects.models import Project, WBSItem
from apps.schedule.models import DailyProgress, SchedulePlan, ScheduleTask


def _field_client(username="field1"):
    user = get_user_model().objects.create_user(username=username, password="pass")
    UserProfile.objects.create(user=user, role="field")
    UserLegalEntityMembership.objects.create(
        user=user,
        legal_entity=LegalEntity.objects.get(code="ASAN"),
        access_scope=LegalEntityAccessScope.FIELD,
    )
    client = Client()
    client.force_login(user)
    return client, user


def _assigned_project(user, code="PRJ-FIELD-001", name="현장 진행 공사"):
    project = Project.objects.create(
        code=code,
        name=name,
        project_type="civil",
        status="draft",
    )
    ProjectAssignment.objects.create(project=project, user=user, is_active=True)
    return project


@pytest.mark.django_db
def test_field_progress_task_dropdown_shows_project_wbs_items():
    client, user = _field_client()
    project = _assigned_project(user)
    WBSItem.objects.create(
        project=project,
        name="포장공",
        weight="63.37",
        sort_order=1,
        is_baseline=True,
    )

    response = client.get(f"/app/field/?tab=progress&project_id={project.id}")

    assert response.status_code == 200
    content = response.content.decode("utf-8")
    assert "오늘 진행률 입력" in content
    assert 'id="task_id"' in content
    assert "포장공" in content
    assert SchedulePlan.objects.filter(project=project, is_active=True).exists()
    assert ScheduleTask.objects.filter(plan__project=project, name="포장공").exists()


@pytest.mark.django_db
def test_field_progress_does_not_filter_out_wbs_with_blank_dates():
    client, user = _field_client("field-blank-dates")
    project = _assigned_project(user, code="PRJ-FIELD-002")
    WBSItem.objects.create(
        project=project,
        name="교통안전시설",
        weight="10.00",
        sort_order=1,
        plan_start_date=None,
        plan_end_date=None,
        is_baseline=True,
    )

    response = client.get(f"/app/field/?tab=progress&project_id={project.id}")

    assert response.status_code == 200
    assert "교통안전시설" in response.content.decode("utf-8")


@pytest.mark.django_db
def test_field_progress_does_not_filter_out_wbs_outside_today():
    client, user = _field_client("field-outside-dates")
    project = _assigned_project(user, code="PRJ-FIELD-003")
    WBSItem.objects.create(
        project=project,
        name="차선도색",
        weight="12.50",
        sort_order=1,
        plan_start_date=date(2026, 1, 1),
        plan_end_date=date(2026, 1, 31),
        is_baseline=True,
    )

    response = client.get(f"/app/field/?tab=progress&project_id={project.id}")

    assert response.status_code == 200
    assert "차선도색" in response.content.decode("utf-8")


@pytest.mark.django_db
def test_field_progress_no_wbs_shows_clear_message_and_disables_submit():
    client, user = _field_client("field-no-wbs")
    project = _assigned_project(user, code="PRJ-FIELD-004")

    response = client.get(f"/app/field/?tab=progress&project_id={project.id}")

    assert response.status_code == 200
    content = response.content.decode("utf-8")
    assert "WBS 기준선 작업이 없습니다" in content
    assert 'id="progress_draft_btn" disabled' in content
    assert 'id="progress_submit_btn" disabled' in content


@pytest.mark.django_db
def test_field_progress_post_requires_wbs_item():
    client, user = _field_client("field-post-no-task")
    project = _assigned_project(user, code="PRJ-FIELD-005")
    WBSItem.objects.create(
        project=project,
        name="포장공",
        weight="63.37",
        sort_order=1,
        is_baseline=True,
    )

    response = client.post(
        "/app/field/",
        {
            "tab": "progress",
            "project_id": str(project.id),
            "action": "draft",
            "report_date": timezone.localdate().isoformat(),
            "progress_percent": "10.0",
        },
    )

    assert response.status_code == 200
    content = response.content.decode("utf-8")
    assert "작업을 선택해 주세요." in content
    assert DailyProgress.objects.filter(project=project, reporter=user).count() == 0


@pytest.mark.django_db
def test_field_progress_project_access_still_enforced():
    client, _user = _field_client("field-no-access")
    project = Project.objects.create(
        code="PRJ-FIELD-006",
        name="비공개 현장 공사",
        project_type="civil",
        status="draft",
    )
    WBSItem.objects.create(
        project=project,
        name="비공개 작업",
        weight="20.00",
        sort_order=1,
        is_baseline=True,
    )

    response = client.get(f"/app/field/?tab=progress&project_id={project.id}")

    assert response.status_code == 200
    content = response.content.decode("utf-8")
    assert "선택한 프로젝트 접근 권한이 없어 접근 가능한 프로젝트로 전환했습니다." in content
    assert "비공개 작업" not in content


@pytest.mark.django_db
def test_field_progress_accepts_long_note_without_500():
    client, user = _field_client("field-long-note")
    project = _assigned_project(user, code="PRJ-FIELD-007")
    WBSItem.objects.create(
        project=project,
        name="포장공",
        weight="63.37",
        sort_order=1,
        is_baseline=True,
    )
    client.get(f"/app/field/?tab=progress&project_id={project.id}")
    task = ScheduleTask.objects.get(plan__project=project, name="포장공")
    note = "가" * 1000

    response = client.post(
        "/app/field/",
        {
            "tab": "progress",
            "project_id": str(project.id),
            "action": "draft",
            "task_id": str(task.id),
            "report_date": timezone.localdate().isoformat(),
            "progress_percent": "10.0",
            "note": note,
        },
    )

    assert response.status_code in (200, 302)
    progress = DailyProgress.objects.get(project=project, reporter=user, task=task)
    assert progress.note == note


@pytest.mark.django_db
def test_field_progress_rejects_extremely_long_note_gracefully():
    client, user = _field_client("field-too-long-note")
    project = _assigned_project(user, code="PRJ-FIELD-008")
    WBSItem.objects.create(
        project=project,
        name="차선도색",
        weight="12.50",
        sort_order=1,
        is_baseline=True,
    )
    client.get(f"/app/field/?tab=progress&project_id={project.id}")
    task = ScheduleTask.objects.get(plan__project=project, name="차선도색")

    response = client.post(
        "/app/field/",
        {
            "tab": "progress",
            "project_id": str(project.id),
            "action": "draft",
            "task_id": str(task.id),
            "report_date": timezone.localdate().isoformat(),
            "progress_percent": "10.0",
            "note": "가" * 5001,
        },
    )

    assert response.status_code == 200
    content = response.content.decode("utf-8")
    assert "메모는 5,000자 이내로 입력해 주세요." in content
    assert DailyProgress.objects.filter(project=project, reporter=user, task=task).count() == 0


@pytest.mark.django_db
def test_field_progress_submit_existing_draft_with_long_note():
    client, user = _field_client("field-submit-long-note")
    project = _assigned_project(user, code="PRJ-FIELD-009")
    WBSItem.objects.create(
        project=project,
        name="교통안전시설",
        weight="10.00",
        sort_order=1,
        is_baseline=True,
    )
    client.get(f"/app/field/?tab=progress&project_id={project.id}")
    task = ScheduleTask.objects.get(plan__project=project, name="교통안전시설")
    progress = DailyProgress.objects.create(
        project=project,
        task=task,
        report_date=timezone.localdate(),
        progress_percent=Decimal("10.0"),
        status="draft",
        reporter=user,
        note="",
    )

    response = client.post(
        "/app/field/",
        {
            "tab": "progress",
            "project_id": str(project.id),
            "action": "draft",
            "progress_id": str(progress.id),
            "task_id": str(task.id),
            "report_date": timezone.localdate().isoformat(),
            "progress_percent": "15.0",
            "note": "가" * 1000,
        },
    )

    assert response.status_code in (200, 302)
    progress.refresh_from_db()
    assert progress.note == ("가" * 1000)
