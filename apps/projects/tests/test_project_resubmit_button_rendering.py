import pytest
from django.contrib.auth import get_user_model
from django.contrib.messages.storage.fallback import FallbackStorage
from django.contrib.sessions.middleware import SessionMiddleware
from django.core.files.uploadedfile import SimpleUploadedFile
from django.test import RequestFactory

from apps.audit.models import AuditLog
from apps.core.models import ApprovalRequest, ApprovalStatus
from apps.core.rbac.models import UserProfile
from apps.projects.hq_views import hq_project_detail
from apps.projects.models import Project, ProjectContract, ProjectStatus
from apps.projects.services.baseline import get_project_baseline_workflow


def _hq_user():
    user = get_user_model().objects.create_user(username="resubmit-render-hq", password="pass")
    UserProfile.objects.create(user=user, role="hq")
    return user


def _request(user, project, method="get", data=None):
    request = getattr(RequestFactory(), method)(
        f"/app/hq/projects/{project.id}/", data or {}
    )
    SessionMiddleware(lambda req: None).process_request(request)
    request.session.save()
    request.user = user
    request._messages = FallbackStorage(request)
    return request


@pytest.mark.django_db
def test_actual_hq_project_screen_uses_rejected_workflow_not_stale_submitted_status():
    hq = _hq_user()
    project = Project.objects.create(
        code="RESUBMIT-STALE-STATUS-001",
        name="Stale rejected project",
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
    ApprovalRequest.objects.create(
        object_type="PROJECT_BASELINE",
        object_id=project.id,
        status=ApprovalStatus.REJECTED,
        reject_reason="Correct the WBS baseline",
    )

    response = hq_project_detail(_request(hq, project), project.id)
    content = response.content.decode("utf-8")
    workflow = get_project_baseline_workflow(project)

    assert response.status_code == 200
    assert workflow.can_hq_resubmit is True
    assert "반려됨" in content
    assert "Correct the WBS baseline" in content
    assert "재제출" in content
    assert 'name="action" value="submit_baseline"' in content

    response = hq_project_detail(
        _request(hq, project, method="post", data={"action": "submit_baseline"}),
        project.id,
    )
    project.refresh_from_db()
    assert response.status_code in (301, 302)
    assert project.status == ProjectStatus.SUBMITTED
    assert ApprovalRequest.objects.get(object_type="PROJECT_BASELINE", object_id=project.id).status == ApprovalStatus.SUBMITTED
    assert AuditLog.objects.filter(project=project, action="BASELINE_RESUBMIT").exists()
