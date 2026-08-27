from django.core.exceptions import ValidationError
from django.db import transaction
from django.utils import timezone

from apps.audit.services.logger import log_action
from apps.closing.guards import guard_write
from apps.core.models import ApprovalRequest, ApprovalStatus

from .models import (
    DailyProgress,
    ProgressCorrectionRequest,
    ProgressCorrectionStatus,
    ProgressCorrectionType,
)


def create_progress_correction(*, progress, actor, correction_type, proposed_progress_percent, proposed_note, reason, request=None):
    if progress.status != "approved":
        raise ValidationError("승인 완료된 진행률만 정정·취소 요청할 수 있습니다.")
    guard_write(project=progress.project, target_date=progress.report_date, message_context="진행률 정정·취소 요청입니다.")
    if correction_type not in {ProgressCorrectionType.CORRECT, ProgressCorrectionType.CANCEL}:
        raise ValidationError("정정 또는 취소를 선택해 주세요.")
    if not (reason or "").strip():
        raise ValidationError("정정·취소 사유를 입력해 주세요.")

    with transaction.atomic():
        progress = DailyProgress.objects.select_for_update().select_related("project").get(pk=progress.pk)
        if progress.status != "approved":
            raise ValidationError("이미 정정·취소 처리 중이거나 승인 상태가 아닙니다.")
        correction = ProgressCorrectionRequest(
            original_progress=progress,
            project=progress.project,
            correction_type=correction_type,
            proposed_progress_percent=proposed_progress_percent if correction_type == ProgressCorrectionType.CORRECT else None,
            proposed_note=(proposed_note or "").strip() if correction_type == ProgressCorrectionType.CORRECT else "",
            reason=reason.strip(),
            original_report_date=progress.report_date,
            original_progress_percent=progress.progress_percent,
            original_note=progress.note,
            requested_by=actor,
        )
        correction.full_clean()
        correction.save()
        log_action(
            actor=actor, action="PROGRESS_CORRECTION_REQUEST", object_type="PROGRESS_CORRECTION",
            object_id=correction.id, project=progress.project, request=request,
            before={"status": progress.status, "progress_percent": str(progress.progress_percent), "note": progress.note},
            after={"status": correction.status, "type": correction.correction_type, "proposed_progress_percent": str(correction.proposed_progress_percent) if correction.proposed_progress_percent is not None else None},
            meta={"reason": correction.reason, "original_progress_id": progress.id},
        )
        return correction


def hq_review_progress_correction(*, correction_id, actor, approve, comment="", request=None):
    with transaction.atomic():
        correction = ProgressCorrectionRequest.objects.select_for_update().select_related("original_progress", "project").get(pk=correction_id)
        if correction.status != ProgressCorrectionStatus.HQ_REVIEW:
            raise ValidationError("HQ 검토 대기 상태의 요청만 처리할 수 있습니다.")
        guard_write(project=correction.project, target_date=correction.original_report_date, message_context="진행률 정정·취소 검토입니다.")
        correction.hq_reviewed_by = actor
        correction.hq_reviewed_at = timezone.now()
        correction.hq_review_comment = (comment or "").strip()
        if not approve:
            correction.status = ProgressCorrectionStatus.REJECTED
            correction.rejection_reason = correction.hq_review_comment or "HQ 검토에서 반려되었습니다."
            correction.save(update_fields=["hq_reviewed_by", "hq_reviewed_at", "hq_review_comment", "status", "rejection_reason", "updated_at"])
            log_action(actor=actor, action="PROGRESS_CORRECTION_HQ_REJECT", object_type="PROGRESS_CORRECTION", object_id=correction.id, project=correction.project, request=request, after={"status": correction.status}, meta={"reason": correction.rejection_reason})
            return correction
        correction.status = ProgressCorrectionStatus.CEO_REVIEW
        correction.save(update_fields=["hq_reviewed_by", "hq_reviewed_at", "hq_review_comment", "status", "updated_at"])
        ApprovalRequest.objects.update_or_create(
            object_type="PROGRESS_CORRECTION", object_id=correction.id,
            defaults={"status": ApprovalStatus.SUBMITTED, "submitted_by": actor, "submitted_at": timezone.now(), "approved_by": None, "approved_at": None, "reject_reason": ""},
        )
        log_action(actor=actor, action="PROGRESS_CORRECTION_HQ_SUBMIT", object_type="PROGRESS_CORRECTION", object_id=correction.id, project=correction.project, request=request, after={"status": correction.status}, meta={"hq_comment": correction.hq_review_comment})
        return correction


def approve_progress_correction(*, correction_id, actor, request=None):
    with transaction.atomic():
        correction = ProgressCorrectionRequest.objects.select_for_update().select_related("original_progress", "project").get(pk=correction_id)
        if correction.status != ProgressCorrectionStatus.CEO_REVIEW:
            raise ValidationError("CEO 승인 대기 상태의 요청만 승인할 수 있습니다.")
        guard_write(project=correction.project, target_date=correction.original_report_date, message_context="진행률 정정·취소 승인입니다.")
        progress = DailyProgress.objects.select_for_update().get(pk=correction.original_progress_id)
        if progress.status != "approved":
            raise ValidationError("원본 진행률 상태가 변경되어 정정·취소할 수 없습니다.")
        before = {"status": progress.status, "progress_percent": str(progress.progress_percent), "note": progress.note}
        if correction.correction_type == ProgressCorrectionType.CANCEL:
            progress.status = "voided"
            progress.save(update_fields=["status", "updated_at"])
        else:
            progress.progress_percent = correction.proposed_progress_percent
            progress.note = correction.proposed_note
            progress.save(update_fields=["progress_percent", "note", "updated_at"])
        correction.status = ProgressCorrectionStatus.APPROVED
        correction.approved_by = actor
        correction.approved_at = timezone.now()
        correction.save(update_fields=["status", "approved_by", "approved_at", "updated_at"])
        log_action(actor=actor, action="PROGRESS_CORRECTION_APPROVE", object_type="PROGRESS_CORRECTION", object_id=correction.id, project=correction.project, request=request, before=before, after={"status": progress.status, "progress_percent": str(progress.progress_percent), "note": progress.note}, meta={"type": correction.correction_type, "original_progress_id": progress.id})
        return correction


def reject_progress_correction(*, correction_id, actor, reason, request=None):
    with transaction.atomic():
        correction = ProgressCorrectionRequest.objects.select_for_update().select_related("project").get(pk=correction_id)
        if correction.status != ProgressCorrectionStatus.CEO_REVIEW:
            raise ValidationError("CEO 승인 대기 상태의 요청만 반려할 수 있습니다.")
        correction.status = ProgressCorrectionStatus.REJECTED
        correction.rejection_reason = (reason or "").strip() or "CEO 검토에서 반려되었습니다."
        correction.approved_by = actor
        correction.approved_at = timezone.now()
        correction.save(update_fields=["status", "rejection_reason", "approved_by", "approved_at", "updated_at"])
        log_action(actor=actor, action="PROGRESS_CORRECTION_CEO_REJECT", object_type="PROGRESS_CORRECTION", object_id=correction.id, project=correction.project, request=request, after={"status": correction.status}, meta={"reason": correction.rejection_reason})
        return correction
