import html

import pytest
from django.contrib.auth import get_user_model
from django.test import Client

from apps.core.rbac.models import LegalEntity, LegalEntityAccessScope, Role, UserLegalEntityMembership, UserProfile
from apps.projects.models import Project
from apps.risk.dashboard_visibility import classify_operational_dashboard_risk
from apps.risk.models import RiskFinding, RiskFindingStatus, RiskRule, RiskSeverity
from scripts.local_ops_reset_project_data import build_manifest


@pytest.fixture(autouse=True)
def _disable_two_factor_enforce(settings):
    settings.MIDDLEWARE = [item for item in settings.MIDDLEWARE if item != "apps.core.middleware.two_factor_enforce.TwoFactorEnforceMiddleware"]


def _user(role, username):
    user = get_user_model().objects.create_user(username=username, password="pass")
    UserProfile.objects.create(user=user, role=role)
    UserLegalEntityMembership.objects.create(
        user=user,
        legal_entity=LegalEntity.objects.get(code="ASAN"),
        access_scope=LegalEntityAccessScope.ENTITY_HQ if role == Role.HQ else LegalEntityAccessScope.CEO_VIEW,
    )
    return user


def _finding(*, project=None, title="운영 리스크", status=RiskFindingStatus.OPEN):
    rule = RiskRule.objects.create(key=f"risk-visible-{RiskRule.objects.count()}", name="리스크 규칙", description="", severity=RiskSeverity.HIGH, threshold_json={})
    return RiskFinding.objects.create(rule=rule, project=project, object_type="PROJECT", object_id=project.id if project else 999999, score=1, severity=RiskSeverity.HIGH, title=title, details="", status=status)


def _context(response):
    context = response.context
    if isinstance(context, list):
        merged = {}
        for item in context:
            merged.update(item.flatten() if hasattr(item, "flatten") else item)
        return merged
    return context.flatten() if hasattr(context, "flatten") else dict(context)


def _risk_todo_count(response):
    return next(item.count for item in _context(response)["todo_items"] if item.text == "CRITICAL/HIGH 리스크 확인")


@pytest.mark.django_db
def test_hq_dashboard_excludes_demo_seed_risk_when_no_projects_exist():
    hq = _user(Role.HQ, "hq-risk-demo")
    _finding(title="Demo risk finding 2026-05-08 16:58")
    client = Client(); client.force_login(hq)
    response = client.get("/app/hq/")
    content = html.unescape(response.content.decode("utf-8"))
    assert response.status_code == 200
    assert _risk_todo_count(response) == 0
    assert "Demo risk finding" not in content
    assert "현재 확인할 운영 리스크가 없습니다." in content


@pytest.mark.django_db
def test_hq_dashboard_excludes_orphan_project_risk_after_project_delete():
    hq = _user(Role.HQ, "hq-risk-orphan")
    project = Project.objects.create(code="HQ-RISK-ORPHAN", name="삭제 현장", project_type="civil")
    finding = _finding(project=project, title="고아 프로젝트 위험")
    project.delete(); finding.refresh_from_db()
    client = Client(); client.force_login(hq)
    response = client.get("/app/hq/")
    assert finding.project_id is None
    assert _risk_todo_count(response) == 0
    assert finding.title not in html.unescape(response.content.decode("utf-8"))


@pytest.mark.django_db
def test_hq_dashboard_counts_high_risk_for_active_project():
    hq = _user(Role.HQ, "hq-risk-active")
    project = Project.objects.create(code="HQ-RISK-ACTIVE", name="운영 현장", project_type="civil")
    finding = _finding(project=project, title="공정 위험")
    client = Client(); client.force_login(hq)
    response = client.get("/app/hq/")
    assert _risk_todo_count(response) == 1
    assert finding.title in html.unescape(response.content.decode("utf-8"))


@pytest.mark.django_db
def test_hq_and_ceo_dashboards_apply_same_project_risk_visibility_policy():
    hq = _user(Role.HQ, "hq-risk-consistent"); ceo = _user(Role.CEO, "ceo-risk-consistent")
    project = Project.objects.create(code="HQ-CEO-RISK", name="공통 현장", project_type="civil")
    valid = _finding(project=project, title="유효 위험")
    _finding(title="Demo risk finding")
    orphan = _finding(title="고아 위험")
    _finding(project=project, title="종료 위험", status=RiskFindingStatus.CLOSED)
    hq_client = Client(); hq_client.force_login(hq)
    ceo_client = Client(); ceo_client.force_login(ceo)
    hq_response = hq_client.get("/app/hq/"); ceo_response = ceo_client.get("/app/ceo/")
    assert _risk_todo_count(hq_response) == 1
    assert _context(ceo_response)["risk_high_count"] == 1
    assert valid.title in html.unescape(hq_response.content.decode("utf-8"))
    assert orphan.title not in html.unescape(hq_response.content.decode("utf-8"))


@pytest.mark.django_db
def test_local_reset_risk_diagnostic_classifies_demo_seed_risk():
    finding = _finding(title="Demo risk finding")
    assert classify_operational_dashboard_risk(finding) == "DEMO_SEED_RISK"


@pytest.mark.django_db
def test_local_project_reset_dryrun_reports_demo_seed_risk_cleanup():
    from django.apps import apps
    finding = _finding(title="Demo risk finding")
    entries, _models, _related_ids = build_manifest(apps, [], [])
    assert finding.id in set(entries["RiskFinding"].values_list("id", flat=True))
    assert RiskFinding.objects.filter(id=finding.id).exists()
