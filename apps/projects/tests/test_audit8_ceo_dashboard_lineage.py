import html
import json
from datetime import date, timedelta
from decimal import Decimal

import pytest
from django.contrib.auth import get_user_model
from django.test import Client

from apps.audit.models import AuditLog
from apps.closing.models import ProjectClose, ProjectCloseStatus
from apps.contracts.models import ContractSnapshot
from apps.core.rbac.models import Role, UserProfile
from apps.cost.models import (
    CostActual,
    CostActualLine,
    CostActualStatus,
    CostItem,
    CostItemCategory,
    RevenueRecognition,
)
from apps.labor.models import WorkerMaster
from apps.projects.models import BudgetCategory, BudgetItem, Project
from apps.schedule.models import DailyProgress, SchedulePlan, ScheduleTask


AUDIT8_KOREAN_FIXTURE_LABELS = (
    "AUDIT8 실제 현장",
    "AUDIT8 A현장",
    "AUDIT8 B현장",
    "AUDIT8 한강 현장",
    "AUDIT8 비활성 현장",
    "AUDIT8 마감 현장",
    "AUDIT8 개인정보 현장",
    "AUDIT8 링크 현장",
    "토공사",
    "포장공사",
    "예산",
    "실행원가",
    "진행률",
    "손익",
    "프로젝트 요약",
    "태스크 진행 현황",
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


def _client(user):
    client = Client()
    client.force_login(user)
    return client


def _dashboard_url(as_of=date(2026, 6, 30)):
    return f"/app/ceo/?as_of_date={as_of.isoformat()}"


def _project(code, name, *, status="active", is_active=True):
    return Project.objects.create(
        code=code,
        name=name,
        project_type="civil",
        status=status,
        is_active=is_active,
        start_date=date(2026, 1, 1),
        end_date=date(2026, 12, 31),
    )


def _cost_item(code, name, *, category=CostItemCategory.OTHER):
    return CostItem.objects.create(
        code=code,
        name=name,
        category=category,
        cost_type="E",
        work_type="99",
        is_direct=True,
        is_active=True,
    )


def _budget_item(project, cost_item, amount, *, name="예산"):
    return BudgetItem.objects.create(
        project=project,
        cost_item=cost_item,
        category=BudgetCategory.OTHER,
        name=name,
        planned_amount=amount,
        status="approved",
        note="AUDIT8 예산 기준선",
    )


def _contract_snapshot(project, amount):
    return ContractSnapshot.objects.create(
        project=project,
        version_no=1,
        base_contract_amount=Decimal(str(amount)),
        start_date=project.start_date,
        end_date=project.end_date,
        is_active=True,
    )


def _revenue(project, snapshot, as_of, progress_percent):
    return RevenueRecognition.objects.create(
        project=project,
        contract_snapshot=snapshot,
        as_of_date=as_of,
        progress_percent=Decimal(str(progress_percent)),
        recognized_revenue=Decimal("0"),
    )


def _approved_cost(project, cost_item, amount, *, report_date=date(2026, 6, 20)):
    actual = CostActual.objects.create(
        project=project,
        report_date=report_date,
        status=CostActualStatus.APPROVED,
        total_amount=Decimal("0"),
    )
    CostActualLine.objects.create(
        cost_actual=actual,
        cost_item=cost_item,
        description="AUDIT8 실행원가",
        quantity=Decimal("1"),
        unit_price=Decimal(str(amount)),
    )
    actual.refresh_from_db()
    return actual


def _progress(project, reporter, percent, *, task_name="포장공사", report_date=date(2026, 6, 20)):
    plan = SchedulePlan.objects.create(project=project, version_no=1, name="AUDIT8 기준선")
    task = ScheduleTask.objects.create(
        plan=plan,
        name=task_name,
        weight_percent=Decimal("100.000"),
        sort_order=1,
    )
    return DailyProgress.objects.create(
        project=project,
        plan=plan,
        task=task,
        report_date=report_date,
        progress_percent=Decimal(str(percent)),
        status="approved",
        reporter=reporter,
        note="AUDIT8 진행률",
    )


def _configured_project(
    *,
    code,
    name,
    contract_amount,
    revenue_progress,
    cost_amount,
    progress_percent,
    reporter,
    as_of=date(2026, 6, 30),
    is_active=True,
    status="active",
):
    project = _project(code, name, status=status, is_active=is_active)
    cost_item = _cost_item(f"{code}-CBS", "토공사")
    _budget_item(project, cost_item, contract_amount // 2, name="토공사 예산")
    snapshot = _contract_snapshot(project, contract_amount)
    _revenue(project, snapshot, as_of - timedelta(days=1), revenue_progress)
    _approved_cost(project, cost_item, cost_amount, report_date=as_of - timedelta(days=2))
    _progress(project, reporter, progress_percent, report_date=as_of - timedelta(days=3))
    return project


def _dashboard_context(response):
    context = response.context
    if isinstance(context, list):
        merged = {}
        for item in context:
            if hasattr(item, "flatten"):
                merged.update(item.flatten())
            else:
                merged.update(item)
        return merged
    if hasattr(context, "flatten"):
        return context.flatten()
    return dict(context)


def _unescaped_content(response):
    return html.unescape(response.content.decode("utf-8"))


def _assert_no_mojibake(text):
    bad_tokens = [chr(code) for code in (0xFFFD, 0x7644, 0x71C1, 0x6C83, 0x7344, 0x4EA6, 0x6930, 0x8881, 0x91AB)]
    for token in bad_tokens:
        assert token not in text


def _project_summary(context, project):
    for item in context["projects"]:
        if item["project_id"] == project.id:
            return item
    raise AssertionError(f"project {project.id} missing from CEO dashboard context")


@pytest.mark.django_db
def test_audit8_ceo_dashboard_renders_for_ceo_with_clean_korean_labels():
    ceo = _user(Role.CEO, "audit8-ceo-render")
    field_reporter = _user(Role.FIELD, "audit8-field-render")
    project = _configured_project(
        code="AUDIT8-RENDER",
        name="AUDIT8 실제 현장",
        contract_amount=1000000,
        revenue_progress="50.0",
        cost_amount=200000,
        progress_percent="40.0",
        reporter=field_reporter,
    )

    response = _client(ceo).get(_dashboard_url())
    content = _unescaped_content(response)

    assert response.status_code == 200
    assert "CEO 대시보드" in content
    assert "프로젝트별 진행률" in content
    assert "월별 원가 추이" in content
    assert _project_summary(_dashboard_context(response), project)["project_name"] == project.name
    _assert_no_mojibake(content)


@pytest.mark.django_db
def test_audit8_ceo_portfolio_summary_matches_project_source_totals():
    ceo = _user(Role.CEO, "audit8-ceo-portfolio")
    reporter = _user(Role.FIELD, "audit8-field-portfolio")
    as_of = date(2026, 6, 30)
    project_a = _configured_project(
        code="AUDIT8-A",
        name="AUDIT8 A현장",
        contract_amount=1000000,
        revenue_progress="50.0",
        cost_amount=200000,
        progress_percent="40.0",
        reporter=reporter,
        as_of=as_of,
    )
    project_b = _configured_project(
        code="AUDIT8-B",
        name="AUDIT8 B현장",
        contract_amount=2000000,
        revenue_progress="25.0",
        cost_amount=300000,
        progress_percent="80.0",
        reporter=reporter,
        as_of=as_of,
    )
    future_snapshot = ContractSnapshot.objects.get(project=project_a, is_active=True)
    _revenue(project_a, future_snapshot, as_of + timedelta(days=5), "90.0")
    _approved_cost(
        project_b,
        CostItem.objects.get(code="AUDIT8-B-CBS"),
        999999,
        report_date=as_of + timedelta(days=5),
    )

    response = _client(ceo).get(_dashboard_url(as_of))
    context = _dashboard_context(response)

    assert response.status_code == 200
    assert len(context["projects"]) == 2
    assert {item["project_id"] for item in context["projects"]} == {project_a.id, project_b.id}
    assert context["total_revenue"] == Decimal("1000000.00")
    assert context["total_cost"] == Decimal("500000")
    assert context["total_profit"] == Decimal("500000.00")
    assert context["avg_progress"] == Decimal("60.000")


@pytest.mark.django_db
def test_audit8_ceo_project_card_lineage_matches_project_budget_progress_cost():
    ceo = _user(Role.CEO, "audit8-ceo-card")
    reporter = _user(Role.FIELD, "audit8-field-card")
    project = _configured_project(
        code="AUDIT8-CARD",
        name="AUDIT8 한강 현장",
        contract_amount=3000000,
        revenue_progress="10.0",
        cost_amount=123456,
        progress_percent="33.3",
        reporter=reporter,
    )
    unrelated = _configured_project(
        code="AUDIT8-OTHER",
        name="AUDIT8 다른 현장",
        contract_amount=4000000,
        revenue_progress="20.0",
        cost_amount=654321,
        progress_percent="90.0",
        reporter=reporter,
    )

    response = _client(ceo).get(_dashboard_url())
    context = _dashboard_context(response)
    summary = _project_summary(context, project)
    unrelated_summary = _project_summary(context, unrelated)

    assert summary["project_name"] == project.name
    assert summary["recognized_revenue"] == Decimal("300000.00")
    assert summary["accrual_cost"] == Decimal("123456")
    assert summary["profit"] == Decimal("176544.00")
    assert summary["overall_progress_percent"] == Decimal("33.300")
    assert unrelated_summary["recognized_revenue"] == Decimal("800000.00")


@pytest.mark.django_db
def test_audit8_ceo_dashboard_excludes_inactive_projects_and_keeps_closed_read_only():
    ceo = _user(Role.CEO, "audit8-ceo-inactive")
    reporter = _user(Role.FIELD, "audit8-field-inactive")
    active_project = _configured_project(
        code="AUDIT8-ACTIVE",
        name="AUDIT8 활성 현장",
        contract_amount=1000000,
        revenue_progress="10.0",
        cost_amount=10000,
        progress_percent="20.0",
        reporter=reporter,
    )
    inactive_project = _configured_project(
        code="AUDIT8-INACTIVE",
        name="AUDIT8 비활성 현장",
        contract_amount=9000000,
        revenue_progress="100.0",
        cost_amount=9000000,
        progress_percent="100.0",
        reporter=reporter,
        is_active=False,
    )
    closed_project = _configured_project(
        code="AUDIT8-CLOSED",
        name="AUDIT8 마감 현장",
        contract_amount=2000000,
        revenue_progress="50.0",
        cost_amount=20000,
        progress_percent="70.0",
        reporter=reporter,
        status="closed",
    )
    ProjectClose.objects.create(project=closed_project, status=ProjectCloseStatus.CLOSED)
    before_counts = {
        "project_close": ProjectClose.objects.count(),
        "daily_progress": DailyProgress.objects.count(),
        "budget": BudgetItem.objects.count(),
        "cost": CostActual.objects.count(),
        "audit": AuditLog.objects.count(),
    }

    response = _client(ceo).get(_dashboard_url())
    context = _dashboard_context(response)
    project_ids = {item["project_id"] for item in context["projects"]}

    assert response.status_code == 200
    assert active_project.id in project_ids
    assert closed_project.id in project_ids
    assert inactive_project.id not in project_ids
    assert before_counts == {
        "project_close": ProjectClose.objects.count(),
        "daily_progress": DailyProgress.objects.count(),
        "budget": BudgetItem.objects.count(),
        "cost": CostActual.objects.count(),
        "audit": AuditLog.objects.count(),
    }


@pytest.mark.django_db
def test_audit8_rbac_boundary_for_ceo_dashboard():
    ceo = _user(Role.CEO, "audit8-ceo-rbac")
    hq = _user(Role.HQ, "audit8-hq-rbac")
    field = _user(Role.FIELD, "audit8-field-rbac")

    assert _client(ceo).get(_dashboard_url()).status_code == 200
    assert _client(field).get(_dashboard_url()).status_code == 403
    assert _client(hq).get(_dashboard_url()).status_code == 403


@pytest.mark.django_db
def test_audit8_ceo_dashboard_does_not_expose_raw_labor_pii_or_secret_values():
    ceo = _user(Role.CEO, "audit8-ceo-privacy")
    reporter = _user(Role.FIELD, "audit8-field-privacy")
    _configured_project(
        code="AUDIT8-PRIVACY",
        name="AUDIT8 개인정보 현장",
        contract_amount=1000000,
        revenue_progress="5.0",
        cost_amount=10000,
        progress_percent="10.0",
        reporter=reporter,
    )
    worker = WorkerMaster(name="감사 근로자", phone="010-9999-8888")
    worker.set_rrn("900101-1234567")
    worker.set_account_number("AUDIT8-SECRET-ACCOUNT")
    worker.save()

    response = _client(ceo).get(_dashboard_url())
    content = _unescaped_content(response)
    context_payload = json.dumps(_dashboard_context(response), ensure_ascii=False, default=str)
    combined = content + context_payload

    assert response.status_code == 200
    assert "900101-1234567" not in combined
    assert "010-9999-8888" not in combined
    assert "AUDIT8-SECRET-ACCOUNT" not in combined
    assert "enc1:" not in combined
    assert worker.identity_hash not in combined


@pytest.mark.django_db
def test_audit8_ceo_dashboard_project_links_resolve_with_clean_korean_labels():
    ceo = _user(Role.CEO, "audit8-ceo-links")
    reporter = _user(Role.FIELD, "audit8-field-links")
    project = _configured_project(
        code="AUDIT8-LINK",
        name="AUDIT8 링크 현장",
        contract_amount=1000000,
        revenue_progress="30.0",
        cost_amount=100000,
        progress_percent="55.0",
        reporter=reporter,
    )
    client = _client(ceo)

    dashboard = client.get(_dashboard_url())
    projects = client.get("/app/ceo/projects/")
    detail = client.get(f"/app/ceo/projects/{project.id}/")
    projects_content = _unescaped_content(projects)
    detail_content = _unescaped_content(detail)

    assert dashboard.status_code == 200
    assert projects.status_code == 200
    assert detail.status_code == 200
    assert f'/app/ceo/projects/{project.id}/' in projects_content
    assert "프로젝트 목록" in projects_content
    assert "프로젝트 요약" in detail_content
    assert "태스크 진행 현황" in detail_content
    assert "손익" in detail_content
    assert project.name in projects_content
    _assert_no_mojibake(projects_content + detail_content)
