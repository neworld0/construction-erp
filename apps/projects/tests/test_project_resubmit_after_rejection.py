import pytest
from django.contrib.auth import get_user_model
from django.contrib.messages.storage.fallback import FallbackStorage
from django.contrib.sessions.middleware import SessionMiddleware
from django.core.exceptions import PermissionDenied
from django.core.files.uploadedfile import SimpleUploadedFile
from django.test import RequestFactory

from apps.audit.models import AuditLog
from apps.core.models import ApprovalRequest, ApprovalStatus
from apps.core.rbac.models import UserProfile
from apps.core.services.approvals import reject_request
from apps.projects.hq_views import hq_project_detail
from apps.projects.models import Project, ProjectContract, ProjectStatus


def _user(role, username):
    user = get_user_model().objects.create_user(username=username, password="pass")
    UserProfile.objects.create(user=user, role=role)
    return user


def _request(user, project, *, method="get", data=None):
    request = getattr(RequestFactory(), method)(
        f"/app/hq/projects/{project.id}/", data or {}
    )
    SessionMiddleware(lambda req: None).process_request(request)
    request.session.save()
    request.user = user
    request._messages = FallbackStorage(request)
    return request


def _rejected_project(hq, ceo):
    project = Project.objects.create(
        code="RESUBMIT-001",
        name="Resubmit project",
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
    approval = ApprovalRequest.objects.create(
        object_type="PROJECT_BASELINE",
        object_id=project.id,
        status=ApprovalStatus.SUBMITTED,
        submitted_by=hq,
    )
    reject_request(approval.id, ceo, reject_reason="LOCAL-OPS rejection test")
    return project, approval


@pytest.mark.django_db
def test_hq_sees_and_can_resubmit_after_ceo_rejection():
    hq = _user("hq", "resubmit-hq")
    ceo = _user("ceo", "resubmit-ceo")
    project, approval = _rejected_project(hq, ceo)

    detail_response = hq_project_detail(_request(hq, project), project.id)
    content = detail_response.content.decode("utf-8")
    assert detail_response.status_code == 200
    assert "반려됨" in content
    assert "LOCAL-OPS rejection test" in content
    assert "재제출" in content

    response = hq_project_detail(
        _request(hq, project, method="post", data={"action": "submit_baseline"}),
        project.id,
    )
    project.refresh_from_db()
    approval.refresh_from_db()
    assert response.status_code in (301, 302)
    assert project.status == ProjectStatus.SUBMITTED
    assert approval.status == ApprovalStatus.SUBMITTED
    assert AuditLog.objects.filter(project=project, action="BASELINE_RESUBMIT").exists()
    assert AuditLog.objects.filter(project=project, action="APPROVAL_REJECT").exists()


@pytest.mark.django_db
def test_pending_project_hides_resubmit_and_field_cannot_submit():
    hq = _user("hq", "pending-resubmit-hq")
    field = _user("field", "pending-resubmit-field")
    project = Project.objects.create(
        code="RESUBMIT-PENDING-001",
        name="Pending project",
        project_type="civil",
        status=ProjectStatus.SUBMITTED,
    )
    ApprovalRequest.objects.create(
        object_type="PROJECT_BASELINE",
        object_id=project.id,
        status=ApprovalStatus.SUBMITTED,
    )

    content = hq_project_detail(_request(hq, project), project.id).content.decode("utf-8")
    assert "재제출" not in content

    with pytest.raises(PermissionDenied):
        hq_project_detail(
            _request(field, project, method="post", data={"action": "submit_baseline"}),
            project.id,
        )
