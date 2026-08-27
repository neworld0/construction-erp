from datetime import timedelta

import pytest
from django.contrib.auth import get_user_model
from django.core.exceptions import ValidationError
from django.test import Client
from django.utils import timezone

from apps.audit.models import AuditLog
from apps.core.rbac.models import ProjectAssignment, UserProfile
from apps.field.models import RetroactiveEntryRequest, RetroactiveEntryRequestStatus
from apps.field.retro_progress import (
    approve_retroactive_progress_request,
    require_approved_retroactive_progress_request,
)
from apps.projects.models import Project, WBSItem
from apps.schedule.models import DailyProgress, ScheduleTask


def _user(username, role):
    user = get_user_model().objects.create_user(username=username, password="pass")
    UserProfile.objects.create(user=user, role=role)
    return user


def _project_for(user, code="RETRO-PROGRESS-001"):
    project = Project.objects.create(
        code=code,
        name="소급 진행률 현장",
        project_type="civil",
        status="draft",
    )
    ProjectAssignment.objects.create(project=project, user=user, is_active=True)
    WBSItem.objects.create(
        project=project,
        name="포장공",
        weight="100.00",
        sort_order=1,
        is_baseline=True,
    )
    return project


def _client(user):
    client = Client()
    client.force_login(user)
    return client


def _task(client, project):
    client.get(f"/app/field/?tab=progress&project_id={project.id}")
    return ScheduleTask.objects.get(plan__project=project, name="포장공")


@pytest.mark.django_db
def test_normal_today_and_yesterday_progress_do_not_require_retro_request():
    field_user = _user("retro-field-normal", "field")
    project = _project_for(field_user)
    client = _client(field_user)
    task = _task(client, project)

    for index, target_date in enumerate((timezone.localdate() - timedelta(days=1), timezone.localdate())):
        response = client.post(
            "/app/field/",
            {
                "tab": "progress",
                "project_id": project.id,
                "action": "draft",
                "task_id": task.id,
                "report_date": target_date.isoformat(),
                "progress_percent": str(10 + index),
                "note": "정상 입력",
            },
        )
        assert response.status_code == 302

    assert DailyProgress.objects.filter(project=project, reporter=field_user).count() == 2
    assert RetroactiveEntryRequest.objects.filter(project=project).count() == 0


@pytest.mark.django_db
def test_retro_progress_requires_exact_hq_approval_then_consumes_it_on_submit():
    field_user = _user("retro-field", "field")
    hq_user = _user("retro-hq", "hq")
    project = _project_for(field_user, code="RETRO-PROGRESS-002")
    field_client = _client(field_user)
    task = _task(field_client, project)
    target_date = timezone.localdate() - timedelta(days=4)

    blocked = field_client.post(
        "/app/field/",
        {
            "tab": "progress",
            "project_id": project.id,
            "action": "draft",
            "task_id": task.id,
            "report_date": target_date.isoformat(),
            "progress_percent": "10.0",
            "note": "소급 입력",
        },
    )
    assert blocked.status_code == 200
    assert "HQ 승인을 요청해 주세요" in blocked.content.decode("utf-8")
    assert DailyProgress.objects.filter(project=project, reporter=field_user).count() == 0

    request_payload = {
        "tab": "progress",
        "project_id": project.id,
        "action": "retro_request",
        "retro_target_date": target_date.isoformat(),
        "retro_reason": "우천으로 현장 입력이 지연되었습니다.",
    }
    assert field_client.post("/app/field/", request_payload).status_code == 302
    assert field_client.post("/app/field/", request_payload).status_code == 302
    retro_request = RetroactiveEntryRequest.objects.get(project=project, requested_by=field_user)
    assert RetroactiveEntryRequest.objects.filter(project=project, requested_by=field_user).count() == 1
    assert retro_request.status == RetroactiveEntryRequestStatus.PENDING

    self_approve = field_client.post(
        "/app/hq/progress/retro-requests/",
        {"request_id": retro_request.id, "action": "approve"},
    )
    assert self_approve.status_code == 403
    retro_request.refresh_from_db()
    assert retro_request.status == RetroactiveEntryRequestStatus.PENDING

    hq_client = _client(hq_user)
    assert hq_client.get("/app/hq/progress/retro-requests/").status_code == 200
    approve_retroactive_progress_request(
        retro_request=retro_request,
        actor=hq_user,
        review_comment="현장 사유 확인",
    )
    retro_request.refresh_from_db()
    assert retro_request.status == RetroactiveEntryRequestStatus.APPROVED
    assert retro_request.reviewed_by == hq_user

    assert field_client.post(
        "/app/field/",
        {
            "tab": "progress",
            "project_id": project.id,
            "action": "draft",
            "task_id": task.id,
            "report_date": target_date.isoformat(),
            "progress_percent": "10.0",
            "note": "승인된 소급 입력",
        },
    ).status_code == 302
    progress = DailyProgress.objects.get(project=project, reporter=field_user, task=task, report_date=target_date)
    assert progress.status == "draft"
    retro_request.refresh_from_db()
    assert retro_request.status == RetroactiveEntryRequestStatus.APPROVED

    submitted = field_client.post(
        "/app/field/",
        {
            "tab": "progress",
            "project_id": project.id,
            "action": "submit",
            "progress_id": progress.id,
        },
    )
    assert submitted.status_code == 302
    progress.refresh_from_db()
    retro_request.refresh_from_db()
    assert progress.status == "submitted"
    assert retro_request.status == RetroactiveEntryRequestStatus.USED
    assert AuditLog.objects.filter(action="RETRO_PROGRESS_REQUEST_CREATED", object_id=retro_request.id).exists()
    assert AuditLog.objects.filter(action="RETRO_PROGRESS_REQUEST_APPROVED", object_id=retro_request.id).exists()
    assert AuditLog.objects.filter(action="RETRO_PROGRESS_AUTHORIZATION_CONSUMED", object_id=retro_request.id).exists()
    assert AuditLog.objects.filter(action="RETRO_PROGRESS_SUBMITTED", object_id=progress.id).exists()


@pytest.mark.django_db
def test_retro_approval_cannot_be_used_for_another_user_project_or_date():
    field_user = _user("retro-scope-owner", "field")
    other_field_user = _user("retro-scope-other", "field")
    hq_user = _user("retro-scope-hq", "hq")
    project = _project_for(field_user, code="RETRO-PROGRESS-003")
    other_project = _project_for(other_field_user, code="RETRO-PROGRESS-004")
    target_date = timezone.localdate() - timedelta(days=4)
    client = _client(field_user)
    client.post(
        "/app/field/",
        {
            "tab": "progress",
            "project_id": project.id,
            "action": "retro_request",
            "retro_target_date": target_date.isoformat(),
            "retro_reason": "입력 지연",
        },
    )
    retro_request = RetroactiveEntryRequest.objects.get(project=project, requested_by=field_user)
    approve_retroactive_progress_request(
        retro_request=retro_request,
        actor=hq_user,
    )

    with pytest.raises(ValidationError):
        require_approved_retroactive_progress_request(
            project=project,
            target_date=target_date,
            actor=other_field_user,
        )
    with pytest.raises(ValidationError):
        require_approved_retroactive_progress_request(
            project=other_project,
            target_date=target_date,
            actor=field_user,
        )
    with pytest.raises(ValidationError):
        require_approved_retroactive_progress_request(
            project=project,
            target_date=target_date - timedelta(days=1),
            actor=field_user,
        )
