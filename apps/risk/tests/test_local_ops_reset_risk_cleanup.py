from decimal import Decimal

import pytest
from django.contrib.auth import get_user_model
from django.test import Client

from apps.audit.models import AuditLog
from apps.core.rbac.models import Role, UserProfile
from apps.projects.models import Project
from apps.risk.models import RiskFinding, RiskFindingStatus, RiskRule, RiskSeverity
from scripts.local_ops_reset_project_data import build_manifest


@pytest.fixture(autouse=True)
def _disable_two_factor_enforce(settings):
    settings.MIDDLEWARE = [
        middleware
        for middleware in settings.MIDDLEWARE
        if middleware != "apps.core.middleware.two_factor_enforce.TwoFactorEnforceMiddleware"
    ]


def _ceo():
    user = get_user_model().objects.create_user(username="risk-reset-ceo", password="pass")
    UserProfile.objects.create(user=user, role=Role.CEO)
    return user


def _project(code):
    return Project.objects.create(code=code, name="리스크 초기화 현장", project_type="civil")


def _finding(*, project=None, object_id=0):
    rule = RiskRule.objects.create(
        key=f"risk-reset-{RiskRule.objects.count()}",
        name="리스크 초기화 규칙",
        description="테스트용",
        severity=RiskSeverity.HIGH,
        threshold_json={},
    )
    return RiskFinding.objects.create(
        rule=rule,
        project=project,
        object_type="PROJECT",
        object_id=object_id or (project.id if project else 999999),
        score=Decimal("1"),
        severity=RiskSeverity.HIGH,
        title="삭제 대상 프로젝트 리스크",
        details="테스트용",
        status=RiskFindingStatus.OPEN,
    )


def _context(response):
    context = response.context
    if isinstance(context, list):
        merged = {}
        for item in context:
            merged.update(item.flatten() if hasattr(item, "flatten") else item)
        return merged
    return context.flatten() if hasattr(context, "flatten") else dict(context)


@pytest.mark.django_db
def test_ceo_dashboard_does_not_count_orphan_project_risks_after_project_delete():
    project = _project("RISK-ORPHAN")
    finding = _finding(project=project)
    project.delete()
    finding.refresh_from_db()

    client = Client()
    client.force_login(_ceo())
    response = client.get("/app/ceo/")
    content = response.content.decode("utf-8")

    assert response.status_code == 200
    assert finding.project_id is None
    assert _context(response)["risk_open_count"] == 0
    assert _context(response)["risk_high_count"] == 0
    assert "HIGH 1건" not in content
    assert "OPEN 리스크 1건" not in content
    assert "현재 OPEN 리스크가 없습니다." in content


@pytest.mark.django_db
def test_ceo_dashboard_still_counts_open_high_risk_for_active_project():
    project = _project("RISK-ACTIVE")
    _finding(project=project)
    client = Client()
    client.force_login(_ceo())

    response = client.get("/app/ceo/")
    context = _context(response)

    assert response.status_code == 200
    assert context["risk_open_count"] == 1
    assert context["risk_high_count"] == 1


@pytest.mark.django_db
def test_local_project_reset_manifest_selects_project_and_orphan_risks_without_touching_audit():
    from django.apps import apps

    project = _project("RISK-RESET")
    linked_finding = _finding(project=project)
    orphan_finding = _finding(object_id=999999)
    audit = AuditLog.objects.create(
        action="RISK_RESET_TEST", object_type="PROJECT", object_id=project.id, project=project
    )

    entries, _models, related_ids = build_manifest(
        apps, [project.id], [project.id]
    )

    selected_ids = set(entries["RiskFinding"].values_list("id", flat=True))
    assert selected_ids == {linked_finding.id, orphan_finding.id}
    assert related_ids["risk_cleanup"]["orphan_risk_count"] == 1

    entries["RiskFinding"].delete()
    project.delete()

    assert not RiskFinding.objects.filter(id__in=selected_ids).exists()
    audit.refresh_from_db()
    assert audit.project_id is None
