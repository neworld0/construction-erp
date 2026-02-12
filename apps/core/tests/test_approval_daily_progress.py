import pytest
from django.contrib.auth import get_user_model

from apps.core.models import ApprovalRequest, ApprovalStatus
from apps.core.services.approvals import approve_request, reject_request
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
