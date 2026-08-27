import pytest
from django.contrib.auth import get_user_model
from django.utils import timezone

from apps.ceo.app_views import _build_recent_approved_items
from apps.core.models import ApprovalRequest, ApprovalStatus
from apps.projects.models import Project


@pytest.mark.django_db
def test_recent_approval_labels_project_baseline_without_generic_internal_identifier():
    ceo = get_user_model().objects.create_user(username="ceo-baseline-label", password="pass")
    project = Project.objects.create(
        code="CEO-BASELINE-LABEL",
        name="기준선 표기 검증 현장",
        project_type="civil",
        is_active=True,
    )
    approval = ApprovalRequest.objects.create(
        object_type="PROJECT_BASELINE",
        object_id=project.id,
        status=ApprovalStatus.APPROVED,
        approved_by=ceo,
        approved_at=timezone.now(),
    )

    item = next(
        item
        for item in _build_recent_approved_items()
        if item["object_id"] == approval.object_id
        and item["object_type"] == "PROJECT_BASELINE"
    )

    assert item["type_label"] == "프로젝트 기준선"
    assert item["title"] == "프로젝트 기준선 승인"
    assert "PROJECT_BASELINE" not in item["title"]
    assert item["project_name"] == project.name
