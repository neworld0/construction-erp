from datetime import date

import pytest
from django.contrib.auth import get_user_model
from django.test import Client

from apps.audit.models import AuditLog
from apps.closing.models import ClosingPeriod, ClosingStatus
from apps.core.rbac.models import ProjectAssignment, Role, UserProfile
from apps.labor.models import (
    LaborRateScope,
    LaborRateTable,
    LaborRateType,
    LaborRole,
    TimesheetStatus,
    WorkerMaster,
)
from apps.labor.services import (
    create_timesheet,
    get_timesheet_workflow_state,
    reject_timesheet,
    submit_timesheet,
    upsert_timesheet_lines,
)
from apps.projects.models import Project


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


def _rejected_timesheet():
    field = _user(Role.FIELD, "rework-field")
    hq = _user(Role.HQ, "rework-hq")
    project = Project.objects.create(code="REWORK-001", name="반려 재작업 현장")
    ProjectAssignment.objects.create(project=project, user=field, is_active=True)
    role = LaborRole.objects.create(code="REWORK-ROLE", name="보통인부", is_active=True)
    worker = WorkerMaster(name="김재작업", active=True, default_labor_role=role)
    worker.set_rrn("900101-1234567")
    worker.save()
    LaborRateTable.objects.create(
        labor_role=role,
        rate_type=LaborRateType.DAY,
        unit_rate=160000,
        effective_from=date(2026, 8, 1),
        scope_type=LaborRateScope.GLOBAL,
        is_active=True,
    )
    timesheet = create_timesheet(
        project=project, work_date=date(2026, 8, 14), actor=field, note="초기 입력"
    )
    upsert_timesheet_lines(
        timesheet=timesheet,
        lines_payload=[{"worker_id": worker.id, "headcount": "1", "hours": "8", "rate_type": "DAY"}],
        actor=field,
    )
    submit_timesheet(timesheet=timesheet, actor=field)
    reject_timesheet(timesheet=timesheet, actor=hq, reason="공수 수정 필요")
    timesheet.refresh_from_db()
    return field, hq, project, worker, timesheet


def _payload(project, worker, *, action, headcount="1.5"):
    return {
        "project_id": str(project.id),
        "work_date": "2026-08-14",
        "note": "수정 완료",
        "action": action,
        "lines-0-worker_id": str(worker.id),
        "lines-0-role_id": "",
        "lines-0-headcount": headcount,
        "lines-0-hours": "8",
        "lines-0-rate_type": "DAY",
        "lines-0-memo": "재작업 반영",
    }


@pytest.mark.django_db
def test_hq_reject_unlocks_field_edit_and_shows_reason():
    field, _hq, project, worker, timesheet = _rejected_timesheet()
    client = Client()
    client.force_login(field)

    response = client.get(f"/app/field/labor/timesheets/{timesheet.id}/")
    content = response.content.decode("utf-8")
    save_response = client.post(
        f"/app/field/labor/timesheets/{timesheet.id}/",
        _payload(project, worker, action="draft"),
    )

    assert response.status_code == 200
    assert "반려됨" in content
    assert "공수 수정 필요" in content
    assert "반려된 출역부입니다" in content
    assert "수정 저장" in content
    assert "다시 제출" in content
    assert save_response.status_code == 302
    timesheet.refresh_from_db()
    assert timesheet.status == TimesheetStatus.REJECTED
    assert timesheet.lines.get().headcount == 1.5
    assert AuditLog.objects.filter(action="TIMESHEET_EDITED_AFTER_REJECT", object_id=timesheet.id).exists()


@pytest.mark.django_db
def test_field_can_resubmit_rejected_timesheet_and_hq_can_review_again():
    field, _hq, project, worker, timesheet = _rejected_timesheet()
    client = Client()
    client.force_login(field)

    response = client.post(
        f"/app/field/labor/timesheets/{timesheet.id}/",
        _payload(project, worker, action="resubmit"),
    )

    assert response.status_code == 302
    timesheet.refresh_from_db()
    state = get_timesheet_workflow_state(timesheet, user=field)
    assert timesheet.status == TimesheetStatus.SUBMITTED
    assert not state["can_field_edit"]
    assert state["can_hq_review"]
    assert AuditLog.objects.filter(action="TIMESHEET_RESUBMIT", object_id=timesheet.id).exists()


@pytest.mark.django_db
def test_submitted_approved_and_closed_rejected_timesheets_remain_locked():
    field, _hq, _project, _worker, timesheet = _rejected_timesheet()
    timesheet.status = TimesheetStatus.SUBMITTED
    timesheet.save(update_fields=["status", "updated_at"])
    assert not get_timesheet_workflow_state(timesheet, user=field)["can_field_edit"]

    timesheet.status = TimesheetStatus.APPROVED
    timesheet.save(update_fields=["status", "updated_at"])
    assert not get_timesheet_workflow_state(timesheet, user=field)["can_field_edit"]

    timesheet.status = TimesheetStatus.REJECTED
    timesheet.save(update_fields=["status", "updated_at"])
    ClosingPeriod.objects.create(year=2026, month=8, status=ClosingStatus.CLOSED)
    state = get_timesheet_workflow_state(timesheet, user=field)
    assert state["is_closed_blocked"]
    assert not state["can_field_edit"]
    assert not state["can_field_resubmit"]
