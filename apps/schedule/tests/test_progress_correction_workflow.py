from datetime import date
from decimal import Decimal

import pytest
from django.contrib.auth import get_user_model

from apps.core.models import ApprovalRequest, ApprovalStatus
from apps.core.services.approvals import approve_request
from apps.projects.models import Project
from apps.schedule.models import (
    DailyProgress,
    ProgressCorrectionStatus,
    ProgressCorrectionType,
    SchedulePlan,
    ScheduleTask,
)
from apps.schedule.progress_corrections import (
    create_progress_correction,
    hq_review_progress_correction,
)


@pytest.mark.django_db
def test_approved_progress_is_corrected_only_after_hq_and_ceo_approval():
    user_model = get_user_model()
    field_user = user_model.objects.create_user(username="progress-field")
    hq_user = user_model.objects.create_user(username="progress-hq")
    ceo_user = user_model.objects.create_user(username="progress-ceo")
    project = Project.objects.create(code="PC-001", name="진행률 정정 테스트")
    plan = SchedulePlan.objects.create(project=project)
    task = ScheduleTask.objects.create(plan=plan, name="포장")
    progress = DailyProgress.objects.create(project=project, plan=plan, task=task, report_date=date(2026, 8, 14), progress_percent=Decimal("30"), status="approved", reporter=field_user, note="원본")

    correction = create_progress_correction(progress=progress, actor=field_user, correction_type=ProgressCorrectionType.CORRECT, proposed_progress_percent=Decimal("35"), proposed_note="정정", reason="수량 재확인")
    progress.refresh_from_db()
    assert progress.progress_percent == Decimal("30")
    assert correction.status == ProgressCorrectionStatus.HQ_REVIEW

    hq_review_progress_correction(correction_id=correction.id, actor=hq_user, approve=True, comment="증빙 확인")
    approval = ApprovalRequest.objects.get(object_type="PROGRESS_CORRECTION", object_id=correction.id)
    assert approval.status == ApprovalStatus.SUBMITTED

    approve_request(approval.id, ceo_user)
    progress.refresh_from_db()
    correction.refresh_from_db()
    assert progress.status == "approved"
    assert progress.progress_percent == Decimal("35")
    assert progress.note == "정정"
    assert correction.original_progress_percent == Decimal("30")
    assert correction.status == ProgressCorrectionStatus.APPROVED


@pytest.mark.django_db
def test_approved_progress_cancel_is_voided_not_deleted():
    user_model = get_user_model()
    field_user = user_model.objects.create_user(username="cancel-field")
    hq_user = user_model.objects.create_user(username="cancel-hq")
    ceo_user = user_model.objects.create_user(username="cancel-ceo")
    project = Project.objects.create(code="PC-002", name="취소 테스트")
    plan = SchedulePlan.objects.create(project=project)
    task = ScheduleTask.objects.create(plan=plan, name="안전관리")
    progress = DailyProgress.objects.create(project=project, plan=plan, task=task, report_date=date(2026, 8, 15), progress_percent=Decimal("10"), status="approved", reporter=field_user)

    correction = create_progress_correction(progress=progress, actor=field_user, correction_type=ProgressCorrectionType.CANCEL, proposed_progress_percent=None, proposed_note="", reason="중복 입력")
    hq_review_progress_correction(correction_id=correction.id, actor=hq_user, approve=True)
    approval = ApprovalRequest.objects.get(object_type="PROGRESS_CORRECTION", object_id=correction.id)
    approve_request(approval.id, ceo_user)
    progress.refresh_from_db()
    assert progress.pk is not None
    assert progress.status == "voided"
