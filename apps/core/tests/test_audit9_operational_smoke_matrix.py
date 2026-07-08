import html
import json
from datetime import date, timedelta
from decimal import Decimal

import pytest
from django.conf import settings
from django.contrib.auth import get_user_model
from django.test import Client
from django.utils import timezone

from apps.audit.constants import DRAFT_SAVE
from apps.audit.models import AuditLog
from apps.closing.services import close_month
from apps.contracts.models import ContractSnapshot
from apps.core.rbac.models import ProjectAssignment, Role, UserProfile
from apps.cost.models import (
    CostActual,
    CostActualLine,
    CostActualStatus,
    CostItem,
    CostItemCategory,
    RevenueRecognition,
)
from apps.labor.models import WorkerMaster
from apps.projects.models import BudgetCategory, BudgetItem, Project, WBSItem
from apps.schedule.models import DailyProgress, SchedulePlan, ScheduleTask


AUDIT9_KOREAN_FIXTURE_LABELS = (
    "AUDIT9 실제 현장",
    "AUDIT9 예산",
    "AUDIT9 포장공사",
    "오늘 진행률 입력",
    "CEO 대시보드",
    "프로젝트 목록",
    "프로젝트 요약",
    "진행률",
    "손익",
    "선택 가능한 작업이 없습니다",
    "마감되었습니다",
)


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


def _client(user=None):
    client = Client()
    if user is not None:
        client.force_login(user)
    return client


def _project(code="AUDIT9-PROJ", name="AUDIT9 실제 현장"):
    return Project.objects.create(
        code=code,
        name=name,
        project_type="civil",
        status="active",
        is_active=True,
        start_date=date(2026, 1, 1),
        end_date=date(2026, 12, 31),
    )


def _assign_field_to_project(field_user, project):
    return ProjectAssignment.objects.create(user=field_user, project=project, is_active=True)


def _cost_item(code="AUDIT9-CBS", name="AUDIT9 포장공사"):
    return CostItem.objects.create(
        code=code,
        name=name,
        category=CostItemCategory.OTHER,
        cost_type="E",
        work_type="08",
        is_direct=True,
        is_active=True,
    )


def _budget_item(project, cost_item, amount=1000000):
    return BudgetItem.objects.create(
        project=project,
        cost_item=cost_item,
        category=BudgetCategory.OTHER,
        name="AUDIT9 예산",
        planned_amount=amount,
        status="approved",
        note="AUDIT9 운영 스모크 예산",
    )


def _wbs_item(project, name="AUDIT9 포장공사"):
    return WBSItem.objects.create(
        project=project,
        name=name,
        weight=Decimal("100.00"),
        sort_order=1,
        is_baseline=True,
    )


def _contract_snapshot(project, amount=1000000):
    return ContractSnapshot.objects.create(
        project=project,
        version_no=1,
        base_contract_amount=Decimal(str(amount)),
        start_date=project.start_date,
        end_date=project.end_date,
        is_active=True,
    )


def _revenue(project, snapshot, progress_percent="50.0", as_of=date(2026, 6, 29)):
    return RevenueRecognition.objects.create(
        project=project,
        contract_snapshot=snapshot,
        as_of_date=as_of,
        progress_percent=Decimal(str(progress_percent)),
        recognized_revenue=Decimal("0"),
    )


def _approved_cost(project, cost_item, amount=200000, report_date=date(2026, 6, 28)):
    actual = CostActual.objects.create(
        project=project,
        report_date=report_date,
        status=CostActualStatus.APPROVED,
        total_amount=Decimal("0"),
    )
    CostActualLine.objects.create(
        cost_actual=actual,
        cost_item=cost_item,
        description="AUDIT9 실행원가",
        quantity=Decimal("1"),
        unit_price=Decimal(str(amount)),
    )
    actual.refresh_from_db()
    return actual


def _source_backed_project(*, field_user=None, code="AUDIT9-PROJ"):
    project = _project(code=code)
    cost_item = _cost_item(code=f"{code}-CBS")
    _budget_item(project, cost_item)
    _wbs_item(project)
    snapshot = _contract_snapshot(project, amount=1000000)
    _revenue(project, snapshot, progress_percent="50.0")
    _approved_cost(project, cost_item, amount=200000)
    if field_user is not None:
        _assign_field_to_project(field_user, project)
    return project


def _field_progress_task(client, project):
    response = client.get(f"/app/field/?tab=progress&project_id={project.id}")
    assert response.status_code == 200
    plan = SchedulePlan.objects.get(project=project, is_active=True)
    task = ScheduleTask.objects.get(plan=plan, name="AUDIT9 포장공사")
    return response, plan, task


def _draft_payload(project, task, *, note="AUDIT9 현장 진행률 메모"):
    return {
        "tab": "progress",
        "project_id": str(project.id),
        "action": "draft",
        "task_id": str(task.id),
        "report_date": timezone.localdate().isoformat(),
        "progress_percent": "12.5",
        "note": note,
    }


def _submit_payload(project, progress):
    return {
        "tab": "progress",
        "project_id": str(project.id),
        "action": "submit",
        "progress_id": str(progress.id),
    }


def _content(response):
    return html.unescape(response.content.decode("utf-8", errors="replace"))


def _dashboard_context(response):
    context = response.context
    if isinstance(context, list):
        merged = {}
        for item in context:
            merged.update(item.flatten() if hasattr(item, "flatten") else item)
        return merged
    return context.flatten() if hasattr(context, "flatten") else dict(context)


def _assert_no_mojibake(text):
    bad_tokens = [chr(code) for code in (0xFFFD, 0x7644, 0x71C1, 0x6C83, 0x7344, 0x4EA6, 0x6930, 0x8881, 0x91AB)]
    for token in bad_tokens:
        assert token not in text


def _assert_no_secret_leak(text, secrets):
    for secret in secrets:
        assert secret not in text
    assert "enc1:" not in text


def _assert_status(response, expected):
    if isinstance(expected, tuple):
        assert response.status_code in expected
    else:
        assert response.status_code == expected
    assert response.status_code < 500
    if response.status_code == 200:
        _assert_no_mojibake(_content(response))


@pytest.mark.django_db
def test_audit9_release_preflight_has_no_pending_migration_or_debug_artifact_contract():
    assert "apps.core.middleware.two_factor_enforce.TwoFactorEnforceMiddleware" not in settings.MIDDLEWARE
    assert "AUDIT9 실제 현장" in AUDIT9_KOREAN_FIXTURE_LABELS
    assert "CEO 대시보드" in AUDIT9_KOREAN_FIXTURE_LABELS
    assert all(("?" * 2) not in label for label in AUDIT9_KOREAN_FIXTURE_LABELS)


@pytest.mark.django_db
def test_audit9_role_based_operational_route_smoke_matrix():
    ceo = _user(Role.CEO, "audit9-ceo-matrix")
    hq = _user(Role.HQ, "audit9-hq-matrix")
    field = _user(Role.FIELD, "audit9-field-matrix")
    project = _source_backed_project(field_user=field, code="AUDIT9-MATRIX")

    clients = {
        "ceo": _client(ceo),
        "hq": _client(hq),
        "field": _client(field),
        "anon": _client(),
    }
    matrix = [
        ("/app/ceo/", {"ceo": 200, "hq": 403, "field": 403, "anon": 302}),
        ("/app/ceo/projects/", {"ceo": 200, "hq": 200, "field": 403, "anon": 302}),
        (f"/app/ceo/projects/{project.id}/", {"ceo": 200, "hq": 200, "field": 403, "anon": 302}),
        ("/app/hq/", {"ceo": 200, "hq": 200, "field": 403, "anon": 302}),
        ("/app/hq/projects/", {"ceo": 200, "hq": 200, "field": 403, "anon": 302}),
        (f"/app/hq/projects/{project.id}/", {"ceo": 200, "hq": 200, "field": 403, "anon": 403}),
        ("/app/field/", {"ceo": 200, "hq": 200, "field": 200, "anon": 302}),
        (
            f"/app/field/?tab=progress&project_id={project.id}",
            {"ceo": 200, "hq": 200, "field": 200, "anon": 302},
        ),
    ]

    for url, expectations in matrix:
        for role, expected in expectations.items():
            _assert_status(clients[role].get(url), expected)


@pytest.mark.django_db
def test_audit9_field_progress_smoke_can_open_dropdown_and_draft_submit():
    field = _user(Role.FIELD, "audit9-field-progress")
    project = _source_backed_project(field_user=field, code="AUDIT9-PROGRESS")
    client = _client(field)

    response, plan, task = _field_progress_task(client, project)
    content = _content(response)

    assert "오늘 진행률 입력" in content
    assert "AUDIT9 포장공사 / 100.000%" in content
    assert "선택 가능한 작업이 없습니다" not in content
    assert task.plan == plan

    draft_response = client.post("/app/field/", _draft_payload(project, task))
    assert draft_response.status_code == 302
    progress = DailyProgress.objects.get(project=project, task=task, reporter=field)
    assert progress.status == "draft"
    assert AuditLog.objects.filter(action=DRAFT_SAVE, object_type="DAILY_PROGRESS", object_id=progress.id).exists()

    submit_response = client.post("/app/field/", _submit_payload(project, progress))
    assert submit_response.status_code == 302
    progress.refresh_from_db()
    assert progress.status == "submitted"


@pytest.mark.django_db
def test_audit9_ceo_dashboard_smoke_shows_source_backed_project_summary():
    ceo = _user(Role.CEO, "audit9-ceo-dashboard")
    field = _user(Role.FIELD, "audit9-field-dashboard")
    project = _source_backed_project(field_user=field, code="AUDIT9-CEO")
    inactive = _source_backed_project(code="AUDIT9-INACTIVE")
    inactive.is_active = False
    inactive.save(update_fields=["is_active"])

    response = _client(ceo).get("/app/ceo/?as_of_date=2026-06-30")
    context = _dashboard_context(response)
    content = _content(response)
    project_rows = {row["project_id"]: row for row in context["projects"]}

    assert response.status_code == 200
    assert "CEO 대시보드" in content
    assert project.id in project_rows
    assert inactive.id not in project_rows
    assert project_rows[project.id]["project_name"] == "AUDIT9 실제 현장"
    assert project_rows[project.id]["recognized_revenue"] == Decimal("500000.00")
    assert project_rows[project.id]["accrual_cost"] == Decimal("200000")
    assert project_rows[project.id]["profit"] == Decimal("300000.00")


@pytest.mark.django_db
def test_audit9_hq_labor_operational_routes_smoke_for_hq_only():
    hq = _user(Role.HQ, "audit9-hq-labor")
    ceo = _user(Role.CEO, "audit9-ceo-labor")
    field = _user(Role.FIELD, "audit9-field-labor")
    routes = [
        "/app/hq/labor/e-card-imports/",
        "/app/hq/labor/workers/",
        "/app/hq/labor/work-ledger/",
        "/app/hq/labor/reporting-map/",
        "/app/hq/labor/monthly-payroll/",
        "/app/hq/labor/payroll-allocation/",
        "/app/hq/labor/confirmed-work-days/",
    ]

    for url in routes:
        _assert_status(_client(hq).get(url), 200)
        _assert_status(_client(ceo).get(url), 200)
        _assert_status(_client(field).get(url), 403)


@pytest.mark.django_db
def test_audit9_excel_import_export_routes_are_guarded_and_do_not_500():
    hq = _user(Role.HQ, "audit9-hq-excel")
    field = _user(Role.FIELD, "audit9-field-excel")
    hq_client = _client(hq)
    field_client = _client(field)

    _assert_status(hq_client.get("/app/hq/labor/e-card-imports/"), 200)
    _assert_status(field_client.get("/app/hq/labor/e-card-imports/"), 403)
    _assert_status(hq_client.get("/app/hq/labor/excel-exports/999999/download/"), 404)
    _assert_status(field_client.get("/app/hq/labor/excel-exports/999999/download/"), 403)


@pytest.mark.django_db
def test_audit9_closing_guard_smoke_blocks_mutation_after_close():
    hq = _user(Role.HQ, "audit9-hq-close")
    field = _user(Role.FIELD, "audit9-field-close")
    project = _source_backed_project(field_user=field, code="AUDIT9-CLOSE")
    client = _client(field)
    _response, _plan, task = _field_progress_task(client, project)
    today = timezone.localdate()
    close_month(today.year, today.month, hq, note="AUDIT9 closing smoke")

    response = client.post("/app/field/", _draft_payload(project, task, note="마감되었습니다"))

    assert response.status_code == 200
    assert DailyProgress.objects.filter(project=project, task=task, reporter=field).count() == 0
    assert not AuditLog.objects.filter(object_type="DAILY_PROGRESS", project=project).exists()
    assert "마감" in _content(response)


@pytest.mark.django_db
def test_audit9_auditlog_privacy_smoke_no_raw_secret_values():
    field = _user(Role.FIELD, "audit9-field-privacy")
    project = _source_backed_project(field_user=field, code="AUDIT9-PRIVACY")
    worker = WorkerMaster(name="AUDIT9 감사 근로자", phone="010-9999-7777")
    worker.set_rrn("900101-1234567")
    worker.set_account_number("AUDIT9-SECRET-ACCOUNT")
    worker.save()
    client = _client(field)
    _response, _plan, task = _field_progress_task(client, project)

    response = client.post(
        "/app/field/",
        _draft_payload(project, task, note="AUDIT9-SECRET-RRN 현장 메모"),
    )
    assert response.status_code == 302
    progress = DailyProgress.objects.get(project=project, task=task, reporter=field)
    audit_payload = json.dumps(
        list(
            AuditLog.objects.filter(object_type="DAILY_PROGRESS", object_id=progress.id)
            .values("before_json", "after_json", "meta_json")
        ),
        ensure_ascii=False,
        default=str,
    )

    _assert_no_secret_leak(
        audit_payload,
        [
            "900101-1234567",
            "010-9999-7777",
            "AUDIT9-SECRET-ACCOUNT",
            worker.identity_hash,
        ],
    )
