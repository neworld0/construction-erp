import pytest
from django.contrib.auth import get_user_model
from django.contrib.messages.storage.fallback import FallbackStorage
from django.contrib.sessions.middleware import SessionMiddleware
from django.core.files.uploadedfile import SimpleUploadedFile
from django.test import RequestFactory

from apps.audit.models import AuditLog
from apps.core.models import ApprovalRequest, ApprovalStatus
from apps.core.rbac.models import UserProfile
from apps.core.services.approvals import reject_request
from apps.projects.hq_views import hq_project_detail
from apps.projects.models import Project, ProjectContract, ProjectStatus, WBSItem
from apps.projects.services.baseline import get_project_baseline_workflow, is_baseline_locked


def _user(role, username):
    user = get_user_model().objects.create_user(username=username, password="pass")
    UserProfile.objects.create(user=user, role=role)
    return user


def _request(user, project, data):
    request = RequestFactory().post(f"/app/hq/projects/{project.id}/", data)
    SessionMiddleware(lambda req: None).process_request(request)
    request.session.save()
    request.user = user
    request._messages = FallbackStorage(request)
    return request


@pytest.mark.django_db
def test_ceo_dashboard_reject_unlocks_hq_rework_and_resubmit():
    hq = _user("hq", "reject-rework-hq")
    ceo = _user("ceo", "reject-rework-ceo")
    project = Project.objects.create(
        code="REJECT-REWORK-001",
        name="Reject rework project",
        project_type="civil",
        status=ProjectStatus.SUBMITTED,
        start_date="2026-08-14",
        end_date="2026-09-13",
    )
    ProjectContract.objects.create(
        project=project,
        contract_amount=132000000,
        contract_start_date="2026-08-14",
        contract_end_date="2026-09-13",
        contract_file=SimpleUploadedFile("contract.pdf", b"%PDF-1.4\n"),
        status="approved",
    )
    wbs = WBSItem.objects.create(project=project, name="WBS-01 Preparation", weight=100)
    approval = ApprovalRequest.objects.create(
        object_type="PROJECT_BASELINE",
        object_id=project.id,
        status=ApprovalStatus.SUBMITTED,
        submitted_by=hq,
    )

    reject_request(approval.id, ceo, reject_reason="WBS baseline needs rework")

    project.refresh_from_db()
    approval.refresh_from_db()
    workflow = get_project_baseline_workflow(project)
    assert project.status == ProjectStatus.DRAFT
    assert approval.status == ApprovalStatus.REJECTED
    assert workflow.label == "반려됨"
    assert workflow.rejection_reason == "WBS baseline needs rework"
    assert workflow.can_hq_edit is True
    assert is_baseline_locked(project) is False
    assert AuditLog.objects.filter(project=project, action="APPROVAL_REJECT").exists()

    edit_response = hq_project_detail(
        _request(
            hq,
            project,
            {
                "action": "save_wbs",
                "wbs-TOTAL_FORMS": "1",
                "wbs-INITIAL_FORMS": "1",
                "wbs-MIN_NUM_FORMS": "0",
                "wbs-MAX_NUM_FORMS": "1000",
                "wbs-0-id": str(wbs.id),
                "wbs-0-name": "WBS-01 Corrected preparation",
                "wbs-0-parent": "",
                "wbs-0-weight": "100",
                "wbs-0-plan_start_date": "2026-08-14",
                "wbs-0-plan_end_date": "2026-09-13",
            },
        ),
        project.id,
    )
    assert edit_response.status_code in (301, 302)
    wbs.refresh_from_db()
    assert wbs.name == "WBS-01 Corrected preparation"

    resubmit_response = hq_project_detail(
        _request(hq, project, {"action": "submit_baseline"}), project.id
    )
    assert resubmit_response.status_code in (301, 302)
    project.refresh_from_db()
    approval.refresh_from_db()
    assert project.status == ProjectStatus.SUBMITTED
    assert approval.status == ApprovalStatus.SUBMITTED
    assert is_baseline_locked(project) is True


@pytest.mark.django_db
def test_closed_project_is_not_reopened_by_generic_baseline_rejection():
    ceo = _user("ceo", "reject-closed-ceo")
    project = Project.objects.create(
        code="REJECT-CLOSED-001",
        name="Closed project",
        project_type="civil",
        status=ProjectStatus.CLOSED,
    )
    approval = ApprovalRequest.objects.create(
        object_type="PROJECT_BASELINE",
        object_id=project.id,
        status=ApprovalStatus.SUBMITTED,
    )

    reject_request(approval.id, ceo, reject_reason="Closed project test")

    project.refresh_from_db()
    assert project.status == ProjectStatus.CLOSED
    assert is_baseline_locked(project) is True
