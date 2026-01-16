import pytest
from django.contrib.auth import get_user_model

from apps.contracts.models import ContractChange, ContractChangeStatus
from apps.contracts.services import approve_contract_change
from apps.projects.models import Project
from apps.schedule.models import PlanChangeRequest, PlanChangeStatus, SchedulePlan
from apps.schedule.services.plan_change import approve_change_request


@pytest.fixture
def approver(db):
    return get_user_model().objects.create_user(username="approver", password="pass")


@pytest.fixture
def project(db):
    return Project.objects.create(code="PRJ-AT-001", name="Atomic Project")


def test_plan_change_approve_atomic_rollback(approver, project, db):
    base_plan = SchedulePlan.objects.create(project=project, version_no=1, is_active=True)
    change_request = PlanChangeRequest.objects.create(
        project=project,
        base_plan=base_plan,
        change_type="field_request",
        reason="Reason",
        proposed_payload=[{"name": "Task", "weight_percent": 100}],
        status=PlanChangeStatus.SUBMITTED,
    )

    with pytest.raises(RuntimeError):
        approve_change_request(change_request.id, approver, failpoint="after_new_plan")

    change_request.refresh_from_db()
    assert change_request.status == PlanChangeStatus.SUBMITTED
    assert SchedulePlan.objects.filter(project=project, version_no=2).count() == 0
    base_plan.refresh_from_db()
    assert base_plan.is_active is True


def test_contract_change_approve_atomic_rollback(approver, project, db):
    change = ContractChange.objects.create(
        project=project,
        change_no=1,
        change_type="design_change",
        reason="Reason",
        status=ContractChangeStatus.SUBMITTED,
    )

    with pytest.raises(RuntimeError):
        approve_contract_change(change.id, approver, failpoint="after_status")

    change.refresh_from_db()
    assert change.status == ContractChangeStatus.SUBMITTED
