from datetime import date

import pytest
from django.contrib.auth import get_user_model
from django.test import Client

from apps.core.rbac.models import ProjectAssignment, Role, UserProfile
from apps.labor.models import (
    LaborRateScope,
    LaborRateTable,
    LaborRateType,
    LaborRole,
    Timesheet,
    TimesheetLine,
    TimesheetStatus,
    WorkerMaster,
)
from apps.labor.services import (
    create_rate,
    create_timesheet,
    resolve_labor_rate,
    submit_timesheet,
    update_rate,
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


def _worker(name, role, rrn):
    worker = WorkerMaster(name=name, active=True, default_labor_role=role)
    worker.set_rrn(rrn)
    worker.save()
    return worker


def _rate(actor, role, amount, *, project=None, worker=None, start=date(2026, 8, 1), end=None):
    return create_rate(
        {
            "labor_role": role,
            "rate_type": LaborRateType.DAY,
            "unit_rate": amount,
            "effective_from": start,
            "effective_to": end,
            "scope_type": LaborRateScope.PROJECT if project else LaborRateScope.GLOBAL,
            "project": project,
            "worker": worker,
            "is_active": True,
        },
        actor=actor,
    )


@pytest.mark.django_db
def test_hq_can_access_labor_rate_management_pages():
    hq = _user(Role.HQ, "rate-hq-ui")
    client = Client()
    client.force_login(hq)

    assert client.get("/app/hq/labor/rates/").status_code == 200
    response = client.get("/app/hq/labor/rates/new/")

    assert response.status_code == 200
    content = response.content.decode("utf-8")
    assert "직종 단가" in content
    assert "노무역할" in content
    assert "단가유형" in content
    assert "일 단가" in content
    assert "적용 시작일" in content


@pytest.mark.django_db
def test_field_cannot_access_labor_rate_management_pages():
    field = _user(Role.FIELD, "rate-field-ui")
    client = Client()
    client.force_login(field)

    assert client.get("/app/hq/labor/rates/").status_code == 403
    assert client.post("/app/hq/labor/rates/new/", {}).status_code == 403


@pytest.mark.django_db
def test_rate_resolution_prefers_project_worker_then_other_scopes():
    hq = _user(Role.HQ, "rate-priority-hq")
    project = Project.objects.create(code="RATE-02-001", name="단가 우선순위 현장")
    role = LaborRole.objects.create(code="RATE-PAV", name="포장공", is_active=True)
    worker = _worker("박포장", role, "900101-1234567")

    _rate(hq, role, 210000)
    _rate(hq, role, 230000, project=project)
    _rate(hq, role, 240000, worker=worker)
    highest = _rate(hq, role, 280000, project=project, worker=worker)

    resolved, scope = resolve_labor_rate(
        worker=worker,
        labor_role=role,
        project=project,
        work_date=date(2026, 8, 14),
        rate_type=LaborRateType.DAY,
    )

    assert resolved == highest
    assert resolved.unit_rate == 280000
    assert scope == "PROJECT_WORKER"


@pytest.mark.django_db
def test_rate_resolution_respects_effective_dates_and_blocks_overlap():
    hq = _user(Role.HQ, "rate-effective-hq")
    role = LaborRole.objects.create(code="RATE-GEN-02", name="보통인부", is_active=True)
    _rate(hq, role, 160000, end=date(2026, 8, 31))
    september = _rate(hq, role, 170000, start=date(2026, 9, 1))

    august, _ = resolve_labor_rate(
        worker=None,
        labor_role=role,
        project=None,
        work_date=date(2026, 8, 14),
        rate_type=LaborRateType.DAY,
    )
    resolved_september, _ = resolve_labor_rate(
        worker=None,
        labor_role=role,
        project=None,
        work_date=date(2026, 9, 2),
        rate_type=LaborRateType.DAY,
    )

    assert august.unit_rate == 160000
    assert resolved_september == september
    with pytest.raises(Exception, match="동일 적용범위의 단가 기간이 중복됩니다"):
        _rate(hq, role, 180000, start=date(2026, 8, 15), end=date(2026, 9, 15))


@pytest.mark.django_db
def test_field_submit_snapshots_resolved_rate_without_rewriting_past_amount():
    hq = _user(Role.HQ, "rate-snapshot-hq")
    field = _user(Role.FIELD, "rate-snapshot-field")
    project = Project.objects.create(code="RATE-02-002", name="단가 스냅샷 현장")
    ProjectAssignment.objects.create(project=project, user=field, is_active=True)
    role = LaborRole.objects.create(code="RATE-SNAPSHOT", name="장비공", is_active=True)
    worker = _worker("이장비", role, "900102-1234567")
    rate = _rate(hq, role, 250000)
    timesheet = create_timesheet(project=project, work_date=date(2026, 8, 14), actor=field)
    upsert_timesheet_lines(
        timesheet=timesheet,
        lines_payload=[{"worker_id": worker.id, "headcount": "1.0", "hours": "8", "rate_type": "DAY"}],
        actor=field,
    )

    submit_timesheet(timesheet=timesheet, actor=field)
    line = TimesheetLine.objects.get(timesheet=timesheet)
    update_rate(rate, {"unit_rate": 280000}, actor=hq)
    line.refresh_from_db()
    timesheet.refresh_from_db()

    assert timesheet.status == TimesheetStatus.SUBMITTED
    assert line.applied_rate_id == rate.id
    assert line.applied_rate_scope == "ROLE_BASE"
    assert line.applied_rate_effective_from == date(2026, 8, 1)
    assert line.applied_rate_resolved_at is not None
    assert line.unit_rate == 250000
    assert line.amount == 250000
    assert LaborRateTable.objects.get(id=rate.id).unit_rate == 280000
