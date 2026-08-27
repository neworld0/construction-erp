import html

import pytest
from django.contrib.auth import get_user_model
from django.test import Client

from apps.audit.models import AuditLog
from apps.core.models import ApprovalRequest, ApprovalStatus
from apps.core.rbac.models import LegalEntity, Role, UserLegalEntityMembership, UserProfile
from apps.core.views import get_dashboard_recent_approval_actions
from apps.projects.models import Project
from scripts.local_ops_reset_project_data import get_stale_dashboard_approval_logs


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
    if role in {Role.HQ, Role.CEO}:
        UserLegalEntityMembership.objects.get_or_create(
            user=user,
            legal_entity=LegalEntity.objects.get(code="ASAN"),
            defaults={"access_scope": "HQ", "is_active": True},
        )
    return user


def _project(code, name="승인 대상 현장"):
    return Project.objects.create(code=code, name=name, project_type="civil", is_active=True)


def _approved_baseline(project, user):
    return ApprovalRequest.objects.create(
        object_type="PROJECT_BASELINE", object_id=project.id, status=ApprovalStatus.APPROVED,
        approved_by=user,
    )


@pytest.mark.django_db
def test_dashboard_excludes_recent_approval_logs_for_deleted_projects():
    hq = _user(Role.HQ, "recent-stale-hq")
    project = _project("RECENT-STALE", "삭제된 승인 현장")
    log = AuditLog.objects.create(
        action="APPROVAL_APPROVE", object_type="APPROVAL_REQUEST", object_id=100, project=project
    )
    project.delete()
    log.refresh_from_db()

    client = Client()
    client.force_login(hq)
    response = client.get("/app/hq/")

    assert response.status_code == 200
    assert log.project_id is None
    assert _context(response)["recent_actions"] == []
    assert "최근 승인 처리 내역이 없습니다." in response.content.decode("utf-8")
    assert AuditLog.objects.filter(id=log.id).exists()


@pytest.mark.django_db
def test_dashboard_shows_recent_approval_for_active_project():
    hq = _user(Role.HQ, "recent-active-hq")
    project = _project("RECENT-ACTIVE")
    AuditLog.objects.create(
        action="APPROVAL_APPROVE", object_type="APPROVAL_REQUEST", object_id=101, project=project
    )
    client = Client()
    client.force_login(hq)

    response = client.get("/app/hq/")

    assert response.status_code == 200
    assert len(_context(response)["recent_actions"]) == 1
    assert project.name in response.content.decode("utf-8")


@pytest.mark.django_db
def test_hq_dashboard_recent_approval_history_is_scoped_to_selected_legal_entity():
    hq = _user(Role.HQ, "recent-entity-scope-hq")
    asan = LegalEntity.objects.get(code="ASAN")
    misan = LegalEntity.objects.get(code="MISAN")
    UserLegalEntityMembership.objects.get_or_create(
        user=hq, legal_entity=asan, defaults={"access_scope": "HQ", "is_active": True}
    )
    UserLegalEntityMembership.objects.create(user=hq, legal_entity=misan, access_scope="HQ", is_active=True)
    asan_project = _project("RECENT-ASAN", "아산 승인 현장")
    AuditLog.objects.create(
        action="APPROVAL_APPROVE", object_type="APPROVAL_REQUEST", object_id=103, project=asan_project
    )

    client = Client()
    client.force_login(hq)
    session = client.session
    session["current_legal_entity_id"] = misan.id
    session.save()
    response = client.get("/app/hq/")

    assert response.status_code == 200
    assert _context(response)["recent_actions"] == []
    assert "아산 승인 현장" not in response.content.decode("utf-8")


@pytest.mark.django_db
def test_ceo_dashboard_excludes_projectless_orphan_approved_request():
    ceo = _user(Role.CEO, "recent-orphan-ceo")
    approval = ApprovalRequest.objects.create(
        object_type="PROJECT_BASELINE", object_id=999999, status=ApprovalStatus.APPROVED,
        approved_by=ceo,
    )
    client = Client()
    client.force_login(ceo)
    response = client.get("/app/ceo/")

    assert response.status_code == 200
    assert _context(response)["recent_approvals"] == []
    content = html.unescape(response.content.decode("utf-8"))
    assert str(approval.object_id) not in content
    assert "승인 완료 내역이 없습니다." in content
    assert ApprovalRequest.objects.filter(id=approval.id).exists()


@pytest.mark.django_db
def test_ceo_dashboard_shows_approved_baseline_for_active_project():
    ceo = _user(Role.CEO, "recent-active-ceo")
    project = _project("CEO-RECENT-ACTIVE")
    _approved_baseline(project, ceo)
    client = Client()
    client.force_login(ceo)

    response = client.get("/app/ceo/")

    assert response.status_code == 200
    assert len(_context(response)["recent_approvals"]) == 1
    assert project.name in response.content.decode("utf-8")


@pytest.mark.django_db
def test_local_reset_dryrun_reports_stale_recent_approval_logs_without_mutation():
    project = _project("RECENT-RESET")
    log = AuditLog.objects.create(
        action="APPROVAL_APPROVE", object_type="APPROVAL_REQUEST", object_id=102, project=project
    )

    logs = get_stale_dashboard_approval_logs(AuditLog, [project.id])

    assert list(logs.values_list("id", flat=True)) == [log.id]
    assert get_dashboard_recent_approval_actions() == [log]
    assert AuditLog.objects.filter(id=log.id).exists()


def _context(response):
    context = response.context
    if isinstance(context, list):
        merged = {}
        for item in context:
            merged.update(item.flatten() if hasattr(item, "flatten") else item)
        return merged
    return context.flatten() if hasattr(context, "flatten") else dict(context)
