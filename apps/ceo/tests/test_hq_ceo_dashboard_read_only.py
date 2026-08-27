import pytest
from django.contrib.auth import get_user_model
from django.core.exceptions import PermissionDenied
from django.test import RequestFactory

from apps.ceo.app_views import _build_pending_items, _run_ceo_quick_action, ceo_approval_quick_approve, ceo_home
from apps.closing.models import ClosingApprovalPolicy, ClosingPeriod, ClosingStatus
from apps.core.models import ApprovalRequest, ApprovalStatus
from apps.core.rbac.models import Role, UserProfile
from apps.labor.models import OfficePayrollCorrection, OfficePayrollCorrectionStatus, OfficePayrollRun, OfficePayrollStatus


@pytest.mark.django_db
def test_hq_can_view_ceo_dashboard_but_cannot_execute_ceo_approval():
    user = get_user_model().objects.create_user(username="hq-ceo-view", password="test")
    UserProfile.objects.create(user=user, role=Role.HQ)
    factory = RequestFactory()

    view_request = factory.get("/app/ceo/")
    view_request.user = user
    response = ceo_home(view_request)
    assert response.status_code == 200

    action_request = factory.post(
        "/app/ceo/approvals/approve/", {"object_type": "APPROVAL_REQUEST", "object_id": "1"}
    )
    action_request.user = user
    with pytest.raises(PermissionDenied):
        ceo_approval_quick_approve(action_request)


@pytest.mark.django_db
def test_ceo_dashboard_allows_approval_of_open_future_closing_period_after_prior_month_closed():
    """A September close request must not be blocked because August is closed."""
    ClosingPeriod.objects.create(year=2026, month=8, status=ClosingStatus.CLOSED)
    september = ClosingPeriod.objects.create(
        year=2026,
        month=9,
        status=ClosingStatus.OPEN,
        approval_policy=ClosingApprovalPolicy.CEO,
    )
    approval = ApprovalRequest.objects.create(
        object_type="CLOSING_PERIOD",
        object_id=september.id,
        status=ApprovalStatus.SUBMITTED,
    )

    pending_item = next(
        item
        for item in _build_pending_items()
        if item["object_type"] == "APPROVAL_REQUEST" and item["object_id"] == approval.id
    )

    assert pending_item["can_approve"] is True
    assert pending_item["can_reject"] is True
    assert pending_item["block_message"] == ""


@pytest.mark.django_db
def test_ceo_dashboard_surfaces_and_approves_office_payroll_correction():
    user_model = get_user_model()
    hq = user_model.objects.create_user(username="payroll-correction-hq", password="test")
    ceo = user_model.objects.create_user(username="payroll-correction-ceo", password="test")
    UserProfile.objects.create(user=hq, role=Role.HQ)
    UserProfile.objects.create(user=ceo, role=Role.CEO)
    run = OfficePayrollRun.objects.create(period_year=2026, period_month=3, status=OfficePayrollStatus.APPROVED, created_by=hq)
    correction = OfficePayrollCorrection.objects.create(
        run=run,
        requested_by=hq,
        status=OfficePayrollCorrectionStatus.SUBMITTED,
        reason="국민연금 정정",
    )

    pending_item = next(
        item for item in _build_pending_items()
        if item["object_type"] == "OFFICE_PAYROLL_CORRECTION" and item["object_id"] == correction.id
    )
    assert pending_item["can_approve"] is True
    assert pending_item["detail_url"].endswith(f"/corrections/{correction.id}/")

    _run_ceo_quick_action("OFFICE_PAYROLL_CORRECTION", correction.id, "approve", ceo)
    correction.refresh_from_db()
    assert correction.status == OfficePayrollCorrectionStatus.APPROVED
    assert correction.approved_by == ceo
