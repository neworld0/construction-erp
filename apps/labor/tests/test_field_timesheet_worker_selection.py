from datetime import date
from decimal import Decimal

import pytest
from django.contrib.auth import get_user_model
from django.test import Client

from apps.core.rbac.models import ProjectAssignment, Role, UserProfile
from apps.labor.models import LaborRole, TimesheetLine, WorkerMaster
from apps.labor.services import get_worker_timesheet_days
from apps.projects.models import Project


@pytest.fixture(autouse=True)
def _disable_two_factor_enforce(settings):
    settings.MIDDLEWARE = [
        middleware
        for middleware in settings.MIDDLEWARE
        if middleware != "apps.core.middleware.two_factor_enforce.TwoFactorEnforceMiddleware"
    ]


def _field_client(username="timesheet-field"):
    user = get_user_model().objects.create_user(username=username, password="pass")
    UserProfile.objects.create(user=user, role=Role.FIELD)
    client = Client()
    client.force_login(user)
    return client, user


def _project_for(user, code="TS-WORKER-001"):
    project = Project.objects.create(code=code, name="출역 근로자 현장")
    ProjectAssignment.objects.create(project=project, user=user, is_active=True)
    return project


def _role(code, name):
    return LaborRole.objects.create(code=code, name=name, is_active=True)


def _worker(name, role, rrn):
    worker = WorkerMaster(name=name, active=True, default_labor_role=role)
    worker.set_rrn(rrn)
    worker.save()
    return worker


def _payload(project, rows, work_date="2026-08-14"):
    payload = {
        "project_id": str(project.id),
        "work_date": work_date,
        "action": "draft",
        "note": "현장 출역",
    }
    for idx, row in enumerate(rows):
        payload.update(
            {
                f"lines-{idx}-worker_id": str(row["worker"].id),
                f"lines-{idx}-role_id": str(row.get("role_id", "")),
                f"lines-{idx}-headcount": str(row.get("work_unit", "1.0")),
                f"lines-{idx}-hours": str(row.get("hours", "8")),
                f"lines-{idx}-rate_type": "DAY",
                f"lines-{idx}-memo": row.get("memo", ""),
            }
        )
    return payload


@pytest.mark.django_db
def test_field_timesheet_new_screen_shows_active_worker_master_selector():
    client, field_user = _field_client()
    _project_for(field_user)
    general = _role("TS-GEN", "보통인부")
    paving = _role("TS-PAV", "포장공")
    _worker("김로컬", general, "900101-1234567")
    _worker("박포장", paving, "900102-1234567")
    inactive = _worker("사용중지근로자", general, "900103-1234567")
    inactive.active = False
    inactive.save(update_fields=["active", "updated_at"])

    response = client.get("/app/field/labor/timesheets/new/")

    content = response.content.decode("utf-8")
    assert response.status_code == 200
    assert "근로자" in content
    assert "김로컬 / 보통인부" in content
    assert "박포장 / 포장공" in content
    assert "사용중지근로자" not in content
    assert "900101-1234567" not in content


@pytest.mark.django_db
def test_field_timesheet_post_saves_worker_level_attendance_and_defaults_role():
    client, field_user = _field_client("timesheet-field-save")
    project = _project_for(field_user, "TS-WORKER-002")
    role = _role("TS-EQP", "장비공")
    worker = _worker("이장비", role, "900104-1234567")

    response = client.post(
        "/app/field/labor/timesheets/new/", _payload(project, [{"worker": worker}])
    )

    assert response.status_code == 302
    line = TimesheetLine.objects.get(worker=worker)
    assert line.timesheet.project == project
    assert line.timesheet.work_date == date(2026, 8, 14)
    assert line.labor_role == role
    assert line.headcount == Decimal("1.0")
    assert line.hours == Decimal("8")


@pytest.mark.django_db
def test_field_timesheet_saves_multiple_workers_and_monthly_worker_totals():
    client, field_user = _field_client("timesheet-field-multiple")
    project = _project_for(field_user, "TS-WORKER-003")
    general = _role("TS-MONTH-GEN", "보통인부")
    paving = _role("TS-MONTH-PAV", "포장공")
    worker_a = _worker("김로컬", general, "900105-1234567")
    worker_b = _worker("박포장", paving, "900106-1234567")

    response = client.post(
        "/app/field/labor/timesheets/new/",
        _payload(project, [{"worker": worker_a}, {"worker": worker_b}]),
    )
    assert response.status_code == 302
    response = client.post(
        "/app/field/labor/timesheets/new/",
        _payload(project, [{"worker": worker_a}], work_date="2026-08-18"),
    )
    assert response.status_code == 302

    totals = {
        row["worker__name"]: row
        for row in get_worker_timesheet_days(project, date(2026, 8, 1))
    }
    assert TimesheetLine.objects.filter(worker__in=[worker_a, worker_b]).count() == 3
    assert totals["김로컬"]["attendance_days"] == 2
    assert totals["김로컬"]["total_work_unit"] == Decimal("2")
    assert totals["박포장"]["attendance_days"] == 1


@pytest.mark.django_db
def test_worker_without_default_role_is_rejected_without_saving_line():
    client, field_user = _field_client("timesheet-field-missing-role")
    project = _project_for(field_user, "TS-WORKER-004")
    worker = _worker("역할미설정", None, "900107-1234567")

    response = client.post(
        "/app/field/labor/timesheets/new/", _payload(project, [{"worker": worker}])
    )

    assert response.status_code == 200
    assert "기본 노무 역할이 설정되어 있지 않습니다" in response.content.decode("utf-8")
    assert not TimesheetLine.objects.filter(worker=worker).exists()
