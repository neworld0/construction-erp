from decimal import Decimal

import pytest
from django.contrib.auth import get_user_model
from django.test import Client

from apps.closing.models import ClosingPeriod, ClosingStatus
from apps.core.rbac.models import LegalEntity, LegalEntityAccessScope, ProjectAssignment, Role, UserLegalEntityMembership, UserProfile
from apps.labor.models import LaborRole, Timesheet, TimesheetLine, WorkerMaster
from apps.projects.models import Project


@pytest.fixture(autouse=True)
def _disable_two_factor_enforce(settings):
    settings.MIDDLEWARE = [
        middleware
        for middleware in settings.MIDDLEWARE
        if middleware != "apps.core.middleware.two_factor_enforce.TwoFactorEnforceMiddleware"
    ]


def _field_client(username="timesheet-mobile-field"):
    user = get_user_model().objects.create_user(username=username, password="pass")
    UserProfile.objects.create(user=user, role=Role.FIELD)
    UserLegalEntityMembership.objects.create(
        user=user,
        legal_entity=LegalEntity.objects.get(code="ASAN"),
        access_scope=LegalEntityAccessScope.FIELD,
    )
    client = Client()
    client.force_login(user)
    return client, user


def _project(user, code="TS-MOBILE-001"):
    project = Project.objects.create(code=code, name="모바일 출역 입력 현장")
    ProjectAssignment.objects.create(project=project, user=user, is_active=True)
    return project


def _worker(name="김로컬", role=None, rrn="900101-1234567"):
    worker = WorkerMaster(name=name, active=True, default_labor_role=role)
    worker.set_rrn(rrn)
    worker.set_account_number("12345678901234")
    worker.phone = "010-9876-5432"
    worker.save()
    return worker


def _save_payload(project, worker, *, work_date="2026-08-24"):
    return {
        "project_id": str(project.id),
        "work_date": work_date,
        "action": "draft",
        "note": "현장 전체 메모",
        "lines-0-worker_id": str(worker.id),
        "lines-0-role_id": "",
        "lines-0-headcount": "1.5",
        "lines-0-hours": "8",
        "lines-0-rate_type": "HOUR",
        "lines-0-memo": "야간 작업",
    }


@pytest.mark.django_db
def test_field_timesheet_mobile_page_contains_required_input_labels():
    client, user = _field_client()
    project = _project(user)
    role = LaborRole.objects.create(code="MOBILE-GEN", name="보통인부", is_active=True)
    _worker(role=role)

    response = client.get("/app/field/labor/timesheets/new/", {"project_id": project.id})
    content = response.content.decode("utf-8")

    assert response.status_code == 200
    for label in ("근로자", "노무역할", "공수", "시간", "단가유형", "메모", "출역 저장"):
        assert label in content


@pytest.mark.django_db
def test_field_timesheet_page_uses_mobile_card_layout():
    client, user = _field_client("timesheet-mobile-layout")
    _project(user, "TS-MOBILE-002")

    response = client.get("/app/field/labor/timesheets/new/")
    content = response.content.decode("utf-8")

    assert response.status_code == 200
    for marker in (
        "field-timesheet-mobile",
        "timesheet-entry-card",
        "worker-entry-card",
        "labor-detail-grid",
        "mobile-sticky-actions",
    ):
        assert marker in content


@pytest.mark.django_db
def test_field_timesheet_input_form_does_not_use_table_layout_for_mobile_entry():
    client, user = _field_client("timesheet-mobile-no-table")
    _project(user, "TS-MOBILE-003")

    response = client.get("/app/field/labor/timesheets/new/")
    content = response.content.decode("utf-8")

    assert "timesheet-entry-list" in content
    assert '<table class="table">' not in content


@pytest.mark.django_db
def test_mobile_timesheet_worker_search_selector_remains_present():
    client, user = _field_client("timesheet-mobile-search")
    _project(user, "TS-MOBILE-004")

    response = client.get("/app/field/labor/timesheets/new/")
    content = response.content.decode("utf-8")

    assert "근로자 이름 또는 직종 검색" in content
    assert 'data-name="lines-0-worker_id"' in content
    assert "/app/field/labor/workers/search/" in content


@pytest.mark.django_db
def test_field_timesheet_mobile_page_does_not_expose_worker_pii():
    client, user = _field_client("timesheet-mobile-privacy")
    _project(user, "TS-MOBILE-005")
    role = LaborRole.objects.create(code="MOBILE-PRIV", name="포장공", is_active=True)
    _worker(name="김비공개", role=role, rrn="900102-1234567")

    response = client.get("/app/field/labor/timesheets/new/")
    content = response.content.decode("utf-8")

    assert "900102-1234567" not in content
    assert "010-9876-5432" not in content
    assert "12345678901234" not in content


@pytest.mark.django_db
def test_field_timesheet_mobile_form_still_saves_worker_level_entry():
    client, user = _field_client("timesheet-mobile-save")
    project = _project(user, "TS-MOBILE-006")
    role = LaborRole.objects.create(code="MOBILE-SAVE", name="보통인부", is_active=True)
    worker = _worker(name="김로컬", role=role, rrn="900103-1234567")

    response = client.post("/app/field/labor/timesheets/new/", _save_payload(project, worker))

    assert response.status_code == 302
    line = TimesheetLine.objects.get(worker=worker)
    assert line.labor_role == role
    assert line.headcount == Decimal("1.5")
    assert line.hours == Decimal("8")
    assert line.rate_type == "HOUR"
    assert line.memo == "야간 작업"
    assert line.timesheet.note == "현장 전체 메모"


@pytest.mark.django_db
def test_mobile_ui_patch_does_not_allow_field_worker_master_management():
    client, user = _field_client("timesheet-mobile-rbac")
    _project(user, "TS-MOBILE-007")

    response = client.get("/app/hq/labor/workers/new/")

    assert response.status_code == 403
    assert WorkerMaster.objects.count() == 0


@pytest.mark.django_db
def test_mobile_ui_patch_preserves_closed_period_guard():
    client, user = _field_client("timesheet-mobile-closed")
    project = _project(user, "TS-MOBILE-008")
    role = LaborRole.objects.create(code="MOBILE-CLOSED", name="보통인부", is_active=True)
    worker = _worker(name="김마감", role=role, rrn="900104-1234567")
    ClosingPeriod.objects.create(
        legal_entity=LegalEntity.objects.get(code="ASAN"),
        year=2026,
        month=8,
        status=ClosingStatus.CLOSED,
    )

    response = client.post("/app/field/labor/timesheets/new/", _save_payload(project, worker))

    assert response.status_code == 200
    assert not Timesheet.objects.exists()
    assert "출역부 입력은 불가능합니다" in response.content.decode("utf-8")
