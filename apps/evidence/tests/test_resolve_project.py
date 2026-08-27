from datetime import date

import pytest
from django.contrib.auth import get_user_model

from apps.closing.models import ClosingPeriod, ClosingStatus
from apps.contracts.models import ContractChange
from apps.core.rbac.models import LegalEntity
from apps.evidence.models import Evidence
from apps.evidence.services.resolve import (
    is_project_or_month_locked,
    resolve_project_for_evidence,
)
from apps.projects.models import Project
from apps.schedule.models import PlanChangeRequest, SchedulePlan


@pytest.fixture
def project(db):
    return Project.objects.create(code="PRJ-RES-001", name="Resolve Project")


@pytest.fixture
def user(db):
    return get_user_model().objects.create_user(username="resolver", password="pass")


def test_resolve_project_from_contract_change(db, project, user):
    change = ContractChange.objects.create(
        project=project,
        change_no=1,
        change_type="design_change",
        reason="Reason",
    )
    evidence = Evidence.objects.create(
        title="Contract Evidence",
        description="",
        object_type="CONTRACT_CHANGE",
        object_id=change.id,
        created_by=user,
    )

    resolved_project = resolve_project_for_evidence(evidence)
    assert resolved_project == project


def test_resolve_project_from_plan_change_request(db, project, user):
    base_plan = SchedulePlan.objects.create(project=project, version_no=1, is_active=True)
    change_request = PlanChangeRequest.objects.create(
        project=project,
        base_plan=base_plan,
        change_type="field_request",
        reason="Reason",
        proposed_payload=[],
    )
    evidence = Evidence.objects.create(
        title="Plan Evidence",
        description="",
        object_type="PLAN_CHANGE_REQUEST",
        object_id=change_request.id,
        created_by=user,
    )

    resolved_project = resolve_project_for_evidence(evidence)
    assert resolved_project == project


@pytest.mark.django_db
def test_month_lock_uses_the_projects_legal_entity():
    asan = LegalEntity.objects.get(code="ASAN")
    project = Project.objects.create(
        code="ASAN-EVIDENCE-LOCK",
        name="법인별 증빙 잠금 현장",
        legal_entity=asan,
    )
    ClosingPeriod.objects.create(
        legal_entity=asan,
        year=2026,
        month=8,
        status=ClosingStatus.CLOSED,
    )

    assert is_project_or_month_locked(project=project, target_date=date(2026, 8, 14))
