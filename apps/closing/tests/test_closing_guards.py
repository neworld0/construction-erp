from datetime import date

import pytest
from django.contrib.auth import get_user_model
from django.contrib.messages.storage.fallback import FallbackStorage
from django.core.exceptions import PermissionDenied, ValidationError
from django.contrib.sessions.backends.db import SessionStore
from django.test import RequestFactory

from apps.closing.guards import assert_month_open as guard_assert_month_open
from apps.closing.guards import guard_write
from apps.closing.models import (
    ClosingApprovalPolicy,
    ClosingPeriod,
    ClosingStatus,
    ProjectClose,
    ProjectCloseStatus,
)
from apps.core.models import ApprovalRequest, ApprovalStatus
from apps.core.rbac.models import Role, UserProfile
from apps.core.todo import _hq_dual_closing_pending_count
from apps.closing.services import close_month
from apps.closing.web_views import (
    _closing_periods_for_list,
    hq_closing_dual_approve,
    hq_closing_submit,
)
from apps.projects.models import Project


def _user(username="closing-hq"):
    return get_user_model().objects.create_user(username=username, password="pass")


def _hq_post(path, user):
    request = RequestFactory().post(path)
    request.user = user
    request.session = SessionStore()
    request._messages = FallbackStorage(request)
    return request


@pytest.mark.django_db
def test_close_month_is_idempotency_safe():
    actor = _user()

    close_month(2026, 5, actor)

    with pytest.raises(ValidationError):
        close_month(2026, 5, actor)


@pytest.mark.django_db
def test_assert_month_open_blocks_closed_month():
    actor = _user("closing-month")
    close_month(2026, 5, actor)

    with pytest.raises(PermissionDenied):
        guard_assert_month_open(date(2026, 5, 10))


@pytest.mark.django_db
def test_guard_write_blocks_closed_project():
    project = Project.objects.create(code="PRJ-CLOSE-001", name="Closed Project")
    ProjectClose.objects.create(project=project, status=ProjectCloseStatus.CLOSED)

    with pytest.raises(PermissionDenied):
        guard_write(project=project, target_date=date(2026, 5, 10))


@pytest.mark.django_db
def test_closing_list_includes_persisted_future_period():
    """Approved rehearsal closes must be visible before their calendar month begins."""
    ClosingPeriod.objects.create(year=2026, month=9, status=ClosingStatus.CLOSED)

    periods = _closing_periods_for_list(date(2026, 8, 20))

    assert (2026, 9) in {(period.year, period.month) for period in periods}


@pytest.mark.django_db
def test_hq_single_policy_closes_without_ceo_approval():
    hq = _user("hq-single")
    UserProfile.objects.create(user=hq, role=Role.HQ)
    period = ClosingPeriod.objects.create(
        year=2026,
        month=9,
        approval_policy=ClosingApprovalPolicy.HQ_SINGLE,
    )
    approval = ApprovalRequest.objects.create(
        object_type="CLOSING_PERIOD",
        object_id=period.id,
        status=ApprovalStatus.DRAFT,
        submitted_by=hq,
    )

    response = hq_closing_submit(_hq_post(f"/app/hq/closing/{period.id}/submit/", hq), period.id)

    assert response.status_code == 302
    period.refresh_from_db()
    approval.refresh_from_db()
    assert period.status == ClosingStatus.CLOSED
    assert approval.status == ApprovalStatus.APPROVED
    assert approval.approved_by == hq


@pytest.mark.django_db
def test_hq_dual_policy_requires_different_hq_reviewer():
    requester = _user("hq-requester")
    reviewer = _user("hq-reviewer")
    UserProfile.objects.create(user=requester, role=Role.HQ)
    UserProfile.objects.create(user=reviewer, role=Role.HQ)
    period = ClosingPeriod.objects.create(
        year=2026,
        month=9,
        approval_policy=ClosingApprovalPolicy.HQ_DUAL,
    )
    approval = ApprovalRequest.objects.create(
        object_type="CLOSING_PERIOD",
        object_id=period.id,
        status=ApprovalStatus.DRAFT,
        submitted_by=requester,
    )

    hq_closing_submit(_hq_post(f"/app/hq/closing/{period.id}/submit/", requester), period.id)
    approval.refresh_from_db()
    assert approval.status == ApprovalStatus.SUBMITTED

    hq_closing_dual_approve(
        _hq_post(f"/app/hq/closing/{period.id}/hq-dual-approve/", requester), period.id
    )
    period.refresh_from_db()
    assert period.status == ClosingStatus.OPEN

    response = hq_closing_dual_approve(
        _hq_post(f"/app/hq/closing/{period.id}/hq-dual-approve/", reviewer), period.id
    )
    assert response.status_code == 302
    period.refresh_from_db()
    approval.refresh_from_db()
    assert period.status == ClosingStatus.CLOSED
    assert approval.approved_by == reviewer


@pytest.mark.django_db
def test_hq_dual_closing_is_counted_in_hq_operating_hub():
    period = ClosingPeriod.objects.create(
        year=2026,
        month=10,
        approval_policy=ClosingApprovalPolicy.HQ_DUAL,
    )
    ApprovalRequest.objects.create(
        object_type="CLOSING_PERIOD",
        object_id=period.id,
        status=ApprovalStatus.SUBMITTED,
    )

    assert _hq_dual_closing_pending_count() == 1
