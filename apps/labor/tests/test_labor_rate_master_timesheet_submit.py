from datetime import date
from decimal import Decimal

import pytest
from django.contrib.auth import get_user_model
from django.core.management import call_command
from django.test import Client

from apps.closing.models import ClosingPeriod, ClosingStatus
from apps.core.rbac.models import ProjectAssignment, Role, UserProfile
from apps.labor.models import (
    LaborMonthlyPayroll,
    LaborRateScope,
    LaborRateTable,
    LaborRateType,
    LaborRole,
    Timesheet,
    TimesheetLine,
    TimesheetStatus,
    WorkerMaster,
)
from apps.labor.rate_master import LOCAL_OPS_LABOR_RATE_SPECS
from apps.labor.services import (
    create_timesheet,
    get_applicable_rate,
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


def _field_client(username="labor-rate-field"):
    user = _user(Role.FIELD, username)
    client = Client()
    client.force_login(user)
    return client, user


def _project(user, code="RATE-TS-001"):
    project = Project.objects.create(code=code, name="직종 단가 검증 현장")
    ProjectAssignment.objects.create(project=project, user=user, is_active=True)
    return project


def _worker(name, role, rrn):
    worker = WorkerMaster(name=name, active=True, default_labor_role=role)
    worker.set_rrn(rrn)
    worker.save()
    return worker


def _timesheet_payload(project, worker, *, action="draft", work_date="2026-08-14"):
    return {
        "project_id": str(project.id),
        "work_date": work_date,
        "action": action,
        "lines-0-worker_id": str(worker.id),
        "lines-0-role_id": "",
        "lines-0-headcount": "1.0",
        "lines-0-hours": "8",
        "lines-0-rate_type": "DAY",
        "lines-0-memo": "단가 검증",
    }


def _global_day_rate(role, amount, effective_from=date(2026, 8, 1), effective_to=None):
    return LaborRateTable.objects.create(
        labor_role=role,
        rate_type=LaborRateType.DAY,
        unit_rate=amount,
        effective_from=effective_from,
        effective_to=effective_to,
        scope_type=LaborRateScope.GLOBAL,
        is_active=True,
    )


@pytest.mark.django_db
def test_field_timesheet_submit_missing_rate_shows_clear_hq_action_message():
    client, field_user = _field_client()
    project = _project(field_user)
    role = LaborRole.objects.create(code="RATE-MISSING", name="장비공", is_active=True)
    worker = _worker("이장비", role, "900101-1234567")

    draft_response = client.post(
        "/app/field/labor/timesheets/new/", _timesheet_payload(project, worker)
    )
    timesheet = Timesheet.objects.get()
    response = client.post(
        f"/app/field/labor/timesheets/{timesheet.id}/",
        _timesheet_payload(project, worker, action="submit"),
    )
    content = response.content.decode("utf-8")

    assert draft_response.status_code == 302
    assert response.status_code == 200
    timesheet.refresh_from_db()
    assert timesheet.status == TimesheetStatus.DRAFT
    assert "장비공 단가가 등록되지 않았습니다" in content
    assert "HQ에서 노무 역할 단가를 먼저 등록해 주세요" in content
    assert "['직종 단가가 등록되지 않았습니다.']" not in content
    assert TimesheetLine.objects.get().unit_rate == 0
    assert not LaborMonthlyPayroll.objects.exists()


@pytest.mark.django_db
def test_local_ops_labor_rates_exist_after_seed_and_are_idempotent():
    legacy_general = LaborRole.objects.create(
        code="ORDINARY-WORKER", name="보통인부", is_active=True
    )
    call_command("seed_labor_rates")
    call_command("seed_labor_rates")

    expected = dict(LOCAL_OPS_LABOR_RATE_SPECS)
    rates = {
        rate.labor_role.code: rate
        for rate in LaborRateTable.objects.select_related("labor_role").filter(
            labor_role__code__in=expected,
            rate_type=LaborRateType.DAY,
            scope_type=LaborRateScope.GLOBAL,
            effective_from=date(2026, 8, 1),
        )
    }

    assert set(rates) == set(expected)
    assert LaborRateTable.objects.filter(labor_role__code__in=expected).count() == 5
    for code, amount in expected.items():
        assert rates[code].unit_rate == amount
        assert get_applicable_rate(
            None, rates[code].labor_role, date(2026, 8, 14)
        ) == rates[code]
        assert get_applicable_rate(
            None, rates[code].labor_role, date(2026, 8, 31)
        ) == rates[code]
    assert get_applicable_rate(None, legacy_general, date(2026, 8, 14)).unit_rate == 160000


@pytest.mark.django_db
def test_field_timesheet_submit_succeeds_when_labor_role_rate_exists():
    client, field_user = _field_client("labor-rate-submit")
    project = _project(field_user, "RATE-TS-002")
    role = LaborRole.objects.create(code="RATE-GEN", name="보통인부", is_active=True)
    worker = _worker("김로컬", role, "900102-1234567")
    _global_day_rate(role, 160000)

    client.post("/app/field/labor/timesheets/new/", _timesheet_payload(project, worker))
    timesheet = Timesheet.objects.get()
    response = client.post(
        f"/app/field/labor/timesheets/{timesheet.id}/",
        _timesheet_payload(project, worker, action="submit"),
    )

    assert response.status_code == 302
    timesheet.refresh_from_db()
    line = timesheet.lines.get()
    assert timesheet.status == TimesheetStatus.SUBMITTED
    assert line.unit_rate == 160000
    assert line.amount == 160000


@pytest.mark.django_db
def test_local_ops_monthly_submitted_timesheet_rates_sum_to_expected_labor_amount():
    field_user = _user(Role.FIELD, "labor-rate-monthly")
    project = _project(field_user, "RATE-TS-003")
    call_command("seed_labor_rates")
    scenarios = (
        ("김로컬", "LAB-GEN", 3, "900103-1234567", 480000),
        ("박포장", "LAB-PAV", 3, "900104-1234567", 630000),
        ("이장비", "LAB-EQP", 1, "900105-1234567", 250000),
        ("최다짐", "LAB-CMP", 1, "900106-1234567", 220000),
        ("정도색", "LAB-PNT", 1, "900107-1234567", 200000),
    )

    expected_amounts = {}
    day_number = 1
    for name, role_code, days, rrn, expected_amount in scenarios:
        role = LaborRole.objects.get(code=role_code)
        worker = _worker(name, role, rrn)
        for _ in range(days):
            timesheet = create_timesheet(
                project=project,
                work_date=date(2026, 8, day_number),
                actor=field_user,
            )
            upsert_timesheet_lines(
                timesheet=timesheet,
                lines_payload=[
                    {
                        "worker_id": worker.id,
                        "headcount": "1.0",
                        "hours": "8",
                        "rate_type": LaborRateType.DAY,
                    }
                ],
                actor=field_user,
            )
            submit_timesheet(timesheet=timesheet, actor=field_user)
            day_number += 1
        expected_amounts[name] = expected_amount

    actual_amounts = {
        name: sum(
            TimesheetLine.objects.filter(
                worker__name=name,
                timesheet__project=project,
                timesheet__status=TimesheetStatus.SUBMITTED,
            ).values_list("amount", flat=True)
        )
        for name in expected_amounts
    }

    assert actual_amounts == expected_amounts
    assert sum(actual_amounts.values()) == 1780000


@pytest.mark.django_db
def test_labor_rate_lookup_respects_effective_date():
    role = LaborRole.objects.create(code="RATE-DATE", name="보통인부", is_active=True)
    old_rate = _global_day_rate(role, 150000, effective_to=date(2026, 8, 20))
    new_rate = _global_day_rate(role, 160000, effective_from=date(2026, 8, 21))

    assert get_applicable_rate(None, role, date(2026, 8, 14)) == old_rate
    assert get_applicable_rate(None, role, date(2026, 8, 31)) == new_rate


@pytest.mark.django_db
def test_field_cannot_create_or_edit_labor_rate_master():
    client, field_user = _field_client("labor-rate-rbac")
    _project(field_user, "RATE-TS-004")

    assert client.get("/app/hq/master/labor/rates/new/").status_code == 403
    assert client.post("/app/hq/master/labor/rates/new/", {}).status_code == 403


@pytest.mark.django_db
def test_timesheet_submit_rate_patch_preserves_closing_guard():
    client, field_user = _field_client("labor-rate-closed")
    project = _project(field_user, "RATE-TS-005")
    role = LaborRole.objects.create(code="RATE-CLOSED", name="도색공", is_active=True)
    worker = _worker("정도색", role, "900108-1234567")
    _global_day_rate(role, 200000)
    ClosingPeriod.objects.create(year=2026, month=8, status=ClosingStatus.CLOSED)

    response = client.post(
        "/app/field/labor/timesheets/new/", _timesheet_payload(project, worker)
    )

    assert response.status_code == 200
    assert not Timesheet.objects.exists()
    assert "출역부 입력은 불가능합니다" in response.content.decode("utf-8")
