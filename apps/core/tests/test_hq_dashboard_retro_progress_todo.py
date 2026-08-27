import pytest
from django.contrib.auth import get_user_model
from django.test import Client
from django.utils import timezone

from apps.core.rbac.models import LegalEntity, LegalEntityAccessScope, Role, UserLegalEntityMembership, UserProfile
from apps.field.models import (
    RetroactiveEntryRequest,
    RetroactiveEntryRequestStatus,
    RetroactiveEntryRequestType,
)
from apps.projects.models import Project
from apps.labor.models import Timesheet, TimesheetStatus


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
    UserLegalEntityMembership.objects.create(
        user=user,
        legal_entity=LegalEntity.objects.get(code="ASAN"),
        access_scope=LegalEntityAccessScope.ENTITY_HQ if role == Role.HQ else LegalEntityAccessScope.FIELD,
    )
    return user


def _context(response):
    context = response.context
    if isinstance(context, list):
        merged = {}
        for item in context:
            merged.update(item.flatten() if hasattr(item, "flatten") else item)
        return merged
    return context.flatten() if hasattr(context, "flatten") else dict(context)


@pytest.mark.django_db
def test_hq_operating_hub_shows_pending_retroactive_progress_request_with_direct_link():
    hq = _user(Role.HQ, "hq-retro-todo")
    field = _user(Role.FIELD, "field-retro-todo")
    project = Project.objects.create(
        code="HQ-RETRO-TODO",
        name="소급 요청 표시 현장",
        project_type="civil",
        is_active=True,
    )
    RetroactiveEntryRequest.objects.create(
        request_type=RetroactiveEntryRequestType.PROGRESS,
        project=project,
        target_date=timezone.localdate() - timezone.timedelta(days=3),
        requested_by=field,
        reason="현장 통신 장애",
        status=RetroactiveEntryRequestStatus.PENDING,
    )
    client = Client()
    client.force_login(hq)

    response = client.get("/app/hq/")

    assert response.status_code == 200
    todo = next(
        item
        for item in _context(response)["todo_items"]
        if item.text == "진행률 소급 입력 요청"
    )
    assert todo.count == 1
    assert todo.url == "/app/hq/progress/retro-requests/?status=PENDING"
    content = response.content.decode("utf-8")
    assert "진행률 소급 입력 요청" in content
    assert "retro-requests/?status=PENDING" in content


@pytest.mark.django_db
def test_hq_operating_hub_shows_submitted_timesheets_with_direct_link():
    hq = _user(Role.HQ, "hq-timesheet-todo")
    field = _user(Role.FIELD, "field-timesheet-todo")
    active_project = Project.objects.create(
        code="HQ-TIMESHEET-TODO",
        name="출역부 승인 대기 현장",
        project_type="civil",
        is_active=True,
    )
    inactive_project = Project.objects.create(
        code="HQ-TIMESHEET-INACTIVE",
        name="종료 현장",
        project_type="civil",
        is_active=False,
    )
    Timesheet.objects.create(
        sheet_no="TS-HQ-TODO-001",
        project=active_project,
        work_date=timezone.localdate(),
        status=TimesheetStatus.SUBMITTED,
        created_by=field,
    )
    Timesheet.objects.create(
        sheet_no="TS-HQ-TODO-002",
        project=inactive_project,
        work_date=timezone.localdate(),
        status=TimesheetStatus.SUBMITTED,
        created_by=field,
    )
    client = Client()
    client.force_login(hq)

    response = client.get("/app/hq/")

    assert response.status_code == 200
    todo = next(item for item in _context(response)["todo_items"] if item.text == "출역부 승인 대기")
    assert todo.count == 1
    assert todo.url == "/app/hq/labor/timesheets/?status=SUBMITTED"
    content = response.content.decode("utf-8")
    assert "출역부 승인 대기" in content
    assert "labor/timesheets/?status=SUBMITTED" in content
