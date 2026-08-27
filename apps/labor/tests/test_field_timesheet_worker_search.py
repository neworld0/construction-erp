import pytest
from django.contrib.auth import get_user_model
from django.test import Client

from apps.core.rbac.models import ProjectAssignment, Role, UserProfile
from apps.labor.models import LaborRole, TimesheetLine, WorkerMaster
from apps.projects.models import Project


@pytest.fixture(autouse=True)
def _disable_two_factor_enforce(settings):
    settings.MIDDLEWARE = [
        middleware
        for middleware in settings.MIDDLEWARE
        if middleware != "apps.core.middleware.two_factor_enforce.TwoFactorEnforceMiddleware"
    ]


def _field_client(username="worker-search-field"):
    user = get_user_model().objects.create_user(username=username, password="pass")
    UserProfile.objects.create(user=user, role=Role.FIELD)
    client = Client()
    client.force_login(user)
    return client, user


def _project(user):
    project = Project.objects.create(code="TS-SEARCH-001", name="근로자 검색 현장")
    ProjectAssignment.objects.create(project=project, user=user, is_active=True)
    return project


def _worker(name, role, rrn, phone="010-1234-5678"):
    worker = WorkerMaster(name=name, default_labor_role=role, active=True, phone=phone)
    worker.set_rrn(rrn)
    worker.set_account_number("12345678901234")
    worker.save()
    return worker


@pytest.mark.django_db
def test_field_timesheet_page_shows_searchable_worker_selector():
    client, user = _field_client()
    _project(user)
    role = LaborRole.objects.create(code="SEARCH-GEN", name="보통인부", is_active=True)
    _worker("김로컬", role, "900101-1234567")

    response = client.get("/app/field/labor/timesheets/new/")

    content = response.content.decode("utf-8")
    assert response.status_code == 200
    assert "근로자 이름 또는 직종 검색" in content
    assert "/app/field/labor/workers/search/" in content
    assert "900101-1234567" not in content
    assert "12345678901234" not in content


@pytest.mark.django_db
def test_field_worker_search_returns_safe_results_by_name_and_role():
    client, user = _field_client("worker-search-by-name")
    project = _project(user)
    general = LaborRole.objects.create(code="SEARCH-GEN-2", name="보통인부", is_active=True)
    equipment = LaborRole.objects.create(code="SEARCH-EQP", name="장비공", is_active=True)
    general_worker = _worker("김로컬", general, "900102-1234567")
    equipment_worker = _worker("이장비", equipment, "900103-1234567", "010-9999-8888")

    by_name = client.get(
        f"/app/field/labor/workers/search/?project_id={project.id}&q=김"
    )
    by_role = client.get(
        f"/app/field/labor/workers/search/?project_id={project.id}&q=장비"
    )

    assert by_name.status_code == 200
    assert by_name.json()["results"] == [
        {"id": general_worker.id, "text": "김로컬 / 보통인부", "role_id": general.id}
    ]
    assert by_role.json()["results"] == [
        {"id": equipment_worker.id, "text": "이장비 / 장비공", "role_id": equipment.id}
    ]
    serialized = str(by_role.json())
    assert "900103" not in serialized
    assert "010-9999-8888" not in serialized
    assert "12345678901234" not in serialized
    assert set(by_role.json()["results"][0]) == {"id", "text", "role_id"}


@pytest.mark.django_db
def test_inactive_workers_are_excluded_from_field_worker_search():
    client, user = _field_client("worker-search-inactive")
    project = _project(user)
    role = LaborRole.objects.create(code="SEARCH-PNT", name="도색공", is_active=True)
    _worker("정도색", role, "900104-1234567")
    inactive = _worker("사용중지 도색", role, "900105-1234567")
    inactive.active = False
    inactive.save(update_fields=["active", "updated_at"])

    response = client.get(
        f"/app/field/labor/workers/search/?project_id={project.id}&q=도색"
    )

    assert response.status_code == 200
    assert [row["text"] for row in response.json()["results"]] == ["정도색 / 도색공"]


@pytest.mark.django_db
def test_search_selected_worker_id_saves_worker_master_fk():
    client, user = _field_client("worker-search-save")
    project = _project(user)
    role = LaborRole.objects.create(code="SEARCH-CMP", name="조립공", is_active=True)
    worker = _worker("최현장", role, "900106-1234567")

    response = client.post(
        "/app/field/labor/timesheets/new/",
        {
            "project_id": str(project.id),
            "work_date": "2026-08-24",
            "action": "draft",
            "lines-0-worker_id": str(worker.id),
            "lines-0-role_id": "",
            "lines-0-headcount": "1",
            "lines-0-hours": "8",
            "lines-0-rate_type": "DAY",
        },
    )

    assert response.status_code == 302
    line = TimesheetLine.objects.get(worker=worker)
    assert line.worker == worker
    assert line.labor_role == role


@pytest.mark.django_db
def test_worker_search_requires_field_project_access():
    client, user = _field_client("worker-search-access")
    other_user = get_user_model().objects.create_user(
        username="worker-search-other", password="pass"
    )
    UserProfile.objects.create(user=other_user, role=Role.FIELD)
    other_project = _project(other_user)

    response = client.get(
        f"/app/field/labor/workers/search/?project_id={other_project.id}&q=김"
    )

    assert response.status_code == 403
