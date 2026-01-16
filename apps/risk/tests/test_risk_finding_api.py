import pytest
from django.contrib.auth import get_user_model
from rest_framework.test import APIClient

from apps.projects.models import Project
from apps.core.rbac.models import UserProfile
from apps.risk.models import RiskFinding, RiskFindingStatus, RiskRule
from apps.risk.services.engine import emit_event


@pytest.fixture
def auth_client(db):
    client = APIClient()
    user = get_user_model().objects.create_user(username="tester", password="pass")
    UserProfile.objects.create(user=user, role="hq")
    client.force_authenticate(user=user)
    return client


@pytest.fixture
def project(db):
    return Project.objects.create(code="PRJ-RISK-001", name="Risk Project")


def _create_rule(key="PROGRESS_SPIKE", active=True):
    return RiskRule.objects.create(
        key=key,
        name=key,
        description="",
        severity="high",
        threshold_json={"max_daily_delta": 5},
        is_active=active,
    )


def test_emit_event_creates_finding(auth_client, project):
    _create_rule()
    event = emit_event(
        "DAILY_PROGRESS",
        "PROJECT",
        project.id,
        {"prev_progress": 0, "new_progress": 10, "delta_percent": 10},
        actor=get_user_model().objects.get(username="tester"),
    )
    finding = RiskFinding.objects.filter(event=event).first()
    assert finding is not None


def test_list_filter_by_status_and_project(auth_client, project):
    _create_rule()
    event = emit_event(
        "DAILY_PROGRESS",
        "PROJECT",
        project.id,
        {"prev_progress": 0, "new_progress": 10, "delta_percent": 10},
    )
    finding = RiskFinding.objects.get(event=event)
    finding.status = RiskFindingStatus.ACK
    finding.save(update_fields=["status"])

    response = auth_client.get(f"/api/risk/findings/?project_id={project.id}&status=ack")
    assert response.status_code == 200
    assert len(response.json()) == 1


def test_ack_success(auth_client, project):
    _create_rule()
    event = emit_event(
        "DAILY_PROGRESS",
        "PROJECT",
        project.id,
        {"prev_progress": 0, "new_progress": 10, "delta_percent": 10},
    )
    finding = RiskFinding.objects.get(event=event)

    response = auth_client.post(f"/api/risk/findings/{finding.id}/ack/")
    assert response.status_code == 200
    finding.refresh_from_db()
    assert finding.status == RiskFindingStatus.ACK


def test_ack_idempotent_policy(auth_client, project):
    _create_rule()
    event = emit_event(
        "DAILY_PROGRESS",
        "PROJECT",
        project.id,
        {"prev_progress": 0, "new_progress": 10, "delta_percent": 10},
    )
    finding = RiskFinding.objects.get(event=event)
    auth_client.post(f"/api/risk/findings/{finding.id}/ack/")

    second = auth_client.post(f"/api/risk/findings/{finding.id}/ack/")
    assert second.status_code == 400


def test_inactive_rule_no_finding(auth_client, project):
    _create_rule(active=False)
    emit_event(
        "DAILY_PROGRESS",
        "PROJECT",
        project.id,
        {"prev_progress": 0, "new_progress": 10, "delta_percent": 10},
    )
    assert RiskFinding.objects.count() == 0


def test_missing_payload_safe(auth_client, project):
    _create_rule()
    emit_event("DAILY_PROGRESS", "PROJECT", project.id, {}, actor=None)
    assert RiskFinding.objects.count() == 0
