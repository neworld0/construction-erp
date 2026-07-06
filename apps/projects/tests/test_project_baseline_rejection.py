from django.contrib.auth import get_user_model
from django.contrib.messages.storage.fallback import FallbackStorage
from django.contrib.sessions.middleware import SessionMiddleware
from django.core.files.uploadedfile import SimpleUploadedFile
from django.test import RequestFactory

import pytest

from apps.audit.models import AuditLog
from apps.core.models import ApprovalRequest, ApprovalStatus
from apps.core.rbac.models import UserProfile
from apps.projects.hq_views import hq_project_detail, hq_project_list
from apps.projects.models import Project, ProjectContract, ProjectStatus


def _build_request(user, path, data=None, method="post"):
    factory = RequestFactory()
    request = getattr(factory, method.lower())(path, data or {})
    SessionMiddleware(lambda req: None).process_request(request)
    request.session.save()
    setattr(request, "_messages", FallbackStorage(request))
    request.user = user
    return request


def _create_project(status=ProjectStatus.SUBMITTED):
    project = Project.objects.create(
        code=f"PRJ-{status.upper()}-001",
        name="기준선 승인 테스트",
        project_type="civil",
        status=status,
        start_date="2026-05-01",
        end_date="2026-05-31",
    )
    ProjectContract.objects.create(
        project=project,
        contract_amount="1000000.00",
        contract_start_date="2026-05-01",
        contract_end_date="2026-05-31",
        contract_file=SimpleUploadedFile(
            "contract.pdf",
            b"%PDF-1.4\n",
            content_type="application/pdf",
        ),
        status="approved",
    )
    if status == ProjectStatus.SUBMITTED:
        ApprovalRequest.objects.create(
            object_type="PROJECT_BASELINE",
            object_id=project.id,
            status=ApprovalStatus.SUBMITTED,
        )
    return project


@pytest.mark.django_db
def test_ceo_reject_baseline_reopens_project_to_draft():
    ceo = get_user_model().objects.create_user(username="ceo-reject", password="pass")
    UserProfile.objects.create(user=ceo, role="ceo")
    project = _create_project()

    request = _build_request(
        ceo,
        f"/app/hq/projects/{project.id}/",
        {"action": "reject_baseline", "reject_reason": "예산과 WBS를 다시 보완해 주세요."},
    )
    response = hq_project_detail(request, project.id)

    assert response.status_code in (301, 302)
    project.refresh_from_db()
    assert project.status == ProjectStatus.DRAFT
    approval = ApprovalRequest.objects.get(
        object_type="PROJECT_BASELINE",
        object_id=project.id,
    )
    assert approval.status == ApprovalStatus.REJECTED
    assert approval.reject_reason == "예산과 WBS를 다시 보완해 주세요."
    assert AuditLog.objects.filter(project=project, action="BASELINE_REJECT").exists()


@pytest.mark.django_db
def test_hq_cannot_reject_project_baseline():
    hq = get_user_model().objects.create_user(username="hq-reject", password="pass")
    UserProfile.objects.create(user=hq, role="hq")
    project = _create_project()

    request = _build_request(
        hq,
        f"/app/hq/projects/{project.id}/",
        {"action": "reject_baseline", "reject_reason": "권한 없음"},
    )
    response = hq_project_detail(request, project.id)

    assert response.status_code in (301, 302)
    project.refresh_from_db()
    assert project.status == ProjectStatus.SUBMITTED
    approval = ApprovalRequest.objects.get(
        object_type="PROJECT_BASELINE",
        object_id=project.id,
    )
    assert approval.status == ApprovalStatus.SUBMITTED
    assert not AuditLog.objects.filter(project=project, action="BASELINE_REJECT").exists()


@pytest.mark.django_db
def test_rejected_project_can_be_resubmitted():
    hq = get_user_model().objects.create_user(username="hq-resubmit", password="pass")
    ceo = get_user_model().objects.create_user(username="ceo-resubmit", password="pass")
    UserProfile.objects.create(user=hq, role="hq")
    UserProfile.objects.create(user=ceo, role="ceo")
    project = _create_project()

    reject_request = _build_request(
        ceo,
        f"/app/hq/projects/{project.id}/",
        {"action": "reject_baseline", "reject_reason": "보완 필요"},
    )
    hq_project_detail(reject_request, project.id)

    submit_request = _build_request(
        hq,
        f"/app/hq/projects/{project.id}/",
        {"action": "submit_baseline"},
    )
    response = hq_project_detail(submit_request, project.id)

    assert response.status_code in (301, 302)
    project.refresh_from_db()
    assert project.status == ProjectStatus.SUBMITTED
    approval = ApprovalRequest.objects.get(
        object_type="PROJECT_BASELINE",
        object_id=project.id,
    )
    assert approval.status == ApprovalStatus.SUBMITTED


@pytest.mark.django_db
def test_project_list_shows_reopened_status_after_rejection():
    hq = get_user_model().objects.create_user(username="hq-list", password="pass")
    ceo = get_user_model().objects.create_user(username="ceo-list", password="pass")
    UserProfile.objects.create(user=hq, role="hq")
    UserProfile.objects.create(user=ceo, role="ceo")
    project = _create_project()

    reject_request = _build_request(
        ceo,
        f"/app/hq/projects/{project.id}/",
        {"action": "reject_baseline", "reject_reason": "수정 후 재제출"},
    )
    hq_project_detail(reject_request, project.id)

    list_request = _build_request(hq, "/app/hq/projects/", method="get")
    response = hq_project_list(list_request)

    assert response.status_code == 200
    project.refresh_from_db()
    assert project.status == ProjectStatus.DRAFT


@pytest.mark.django_db
def test_hq_project_detail_template_has_valid_korean_labels():
    hq = get_user_model().objects.create_user(username="hq-template", password="pass")
    UserProfile.objects.create(user=hq, role="hq")
    project = _create_project(status=ProjectStatus.DRAFT)

    request = _build_request(hq, f"/app/hq/projects/{project.id}/", method="get")
    response = hq_project_detail(request, project.id)
    content = response.content.decode("utf-8")

    assert response.status_code == 200
    assert "프로젝트 상세" in content
    assert "프로젝트명" in content
    assert "계약 정보" in content
    assert "기준선 변경 이력" in content
    assert "프로젝트 배정" in content
    assert "?꾨" not in content
    assert "?곸" not in content
    assert "怨꾩" not in content
    assert "湲곗" not in content
    assert "諛곗" not in content
    assert "醫낅" not in content
    assert "濡쒕" not in content
    assert "?ㅼ슫" not in content


@pytest.mark.django_db
def test_ceo_submitted_project_page_shows_approve_and_reject_controls():
    ceo = get_user_model().objects.create_user(username="ceo-template", password="pass")
    UserProfile.objects.create(user=ceo, role="ceo")
    project = _create_project(status=ProjectStatus.SUBMITTED)

    request = _build_request(ceo, f"/app/hq/projects/{project.id}/", method="get")
    response = hq_project_detail(request, project.id)
    content = response.content.decode("utf-8")

    assert response.status_code == 200
    assert "승인" in content
    assert "반려" in content
    assert 'name="reject_reason"' in content
    assert 'value="reject_baseline"' in content
