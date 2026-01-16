from decimal import Decimal

import pytest
from django.contrib.auth import get_user_model

from apps.contracts.models import (
    ContractChange,
    ContractChangeStatus,
    ContractSnapshot,
)
from apps.contracts.services import approve_contract_change
from apps.finance.services.profit_loss import get_profit_loss_by_project
from apps.projects.models import Project


@pytest.fixture
def approver(db):
    return get_user_model().objects.create_user(username="approver", password="pass")


@pytest.fixture
def project(db):
    return Project.objects.create(
        code="PRJ-SNAP-001",
        name="Snapshot Project",
        contract_amount=Decimal("1000.00"),
    )


def _create_submitted_change(project, delta):
    return ContractChange.objects.create(
        project=project,
        change_type="design_change",
        reason="Snapshot update",
        contract_amount_delta=delta,
        time_extension_days=0,
        status=ContractChangeStatus.SUBMITTED,
    )


def test_first_approve_creates_active_snapshot(project, approver):
    change = _create_submitted_change(project, Decimal("100.00"))

    approve_contract_change(change.id, approver)

    snapshots = ContractSnapshot.objects.filter(project=project)
    assert snapshots.count() == 1
    active = snapshots.filter(is_active=True).first()
    assert active is not None
    assert active.version_no == 1
    assert active.base_contract_amount == Decimal("1100.00")


def test_second_approve_rotates_active_snapshot(project, approver):
    first = _create_submitted_change(project, Decimal("100.00"))
    approve_contract_change(first.id, approver)
    second = _create_submitted_change(project, Decimal("50.00"))
    approve_contract_change(second.id, approver)

    snapshots = list(ContractSnapshot.objects.filter(project=project).order_by("version_no"))
    assert len(snapshots) == 2
    assert snapshots[0].is_active is False
    assert snapshots[1].is_active is True
    assert snapshots[1].version_no == snapshots[0].version_no + 1
    assert ContractSnapshot.objects.filter(project=project, is_active=True).count() == 1


def test_profit_loss_uses_active_snapshot(project, approver):
    change = _create_submitted_change(project, Decimal("100.00"))
    approve_contract_change(change.id, approver)
    active = ContractSnapshot.objects.filter(project=project, is_active=True).first()

    summary = get_profit_loss_by_project(project.id)

    assert summary["snapshot_id"] == active.id
    assert "recognized_revenue" in summary
    assert "accrual_cost" in summary
    assert "profit" in summary


def test_snapshot_rollback_on_exception(project, approver):
    change = _create_submitted_change(project, Decimal("100.00"))

    with pytest.raises(RuntimeError):
        approve_contract_change(change.id, approver, failpoint="after_status")

    change.refresh_from_db()
    assert change.status == ContractChangeStatus.SUBMITTED
    assert ContractSnapshot.objects.filter(project=project).count() == 0
