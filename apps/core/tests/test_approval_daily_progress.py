import pytest
from django.contrib.auth import get_user_model

from apps.core.models import ApprovalRequest, ApprovalStatus
from apps.core.rbac.models import LegalEntity, OrganizationGroup
from apps.core.services.approvals import approve_request, reject_request
from apps.closing.models import ClosingApprovalPolicy, ClosingPeriod, ClosingStatus
from apps.projects.models import Project
from apps.schedule.models import DailyProgress, SchedulePlan, ScheduleTask


@pytest.fixture
def users(db):
    User = get_user_model()
    reporter = User.objects.create_user(username="field-user", password="pass")
    approver = User.objects.create_user(username="ceo-user", password="pass")
    return reporter, approver


@pytest.fixture
def progress_entry(db, users):
    reporter, _ = users
    project = Project.objects.create(code="PRJ-DP-001", name="Progress Project")
    plan = SchedulePlan.objects.create(project=project, name="Base", is_active=True)
    task = ScheduleTask.objects.create(plan=plan, name="Task 1", weight_percent=100)
    return DailyProgress.objects.create(
        project=project,
        plan=plan,
        task=task,
        report_date="2026-02-03",
        progress_percent=25.0,
        status="submitted",
        reporter=reporter,
    )


def test_approve_syncs_daily_progress_status(progress_entry, users):
    _, approver = users
    approval = ApprovalRequest.objects.create(
        object_type="DAILY_PROGRESS",
        object_id=progress_entry.id,
        status=ApprovalStatus.SUBMITTED,
    )

    approve_request(approval.id, approver)

    progress_entry.refresh_from_db()
    approval.refresh_from_db()
    assert approval.status == ApprovalStatus.APPROVED
    assert progress_entry.status == "approved"
    assert progress_entry.approved_by == approver
    assert progress_entry.approved_at is not None


def test_reject_syncs_daily_progress_status(progress_entry, users):
    _, approver = users
    approval = ApprovalRequest.objects.create(
        object_type="DAILY_PROGRESS",
        object_id=progress_entry.id,
        status=ApprovalStatus.SUBMITTED,
    )

    reject_request(approval.id, approver, reject_reason="invalid")

    progress_entry.refresh_from_db()
    approval.refresh_from_db()
    assert approval.status == ApprovalStatus.REJECTED
    assert progress_entry.status == "rejected"
    assert progress_entry.rejected_by == approver
    assert progress_entry.rejected_at is not None
    assert progress_entry.reject_reason == "invalid"


def test_dashboard_approval_closes_the_requested_month(users):
    _, approver = users
    group = OrganizationGroup.objects.create(code="TEST-GRP", name="테스트 그룹")
    entity = LegalEntity.objects.create(
        group=group,
        code="TEST-ENTITY",
        name="테스트 법인",
        legal_name="테스트 법인 주식회사",
    )
    period = ClosingPeriod.objects.create(
        legal_entity=entity,
        year=2026,
        month=8,
        status=ClosingStatus.OPEN,
        approval_policy=ClosingApprovalPolicy.CEO,
    )
    approval = ApprovalRequest.objects.create(
        object_type="CLOSING_PERIOD", object_id=period.id,
        status=ApprovalStatus.SUBMITTED, comment="8월 운영 마감",
    )

    approve_request(approval.id, approver)

    period.refresh_from_db()
    approval.refresh_from_db()
    assert approval.status == ApprovalStatus.APPROVED
    assert period.status == ClosingStatus.CLOSED
    assert period.closed_by == approver
