from __future__ import annotations

from datetime import date, timedelta

from django.core.exceptions import PermissionDenied, ValidationError
from django.db import IntegrityError, transaction
from django.utils import timezone

from apps.audit.services.logger import log_action
from apps.closing.guards import guard_write
from apps.core.rbac.models import Role
from apps.core.rbac.permissions import require_project_access, require_role

from .models import (
    RetroactiveEntryRequest,
    RetroactiveEntryRequestStatus,
    RetroactiveEntryRequestType,
)


RETRO_PROGRESS_OBJECT_TYPE = "RETROACTIVE_ENTRY_REQUEST"
RETRO_PROGRESS_REQUEST_TYPE = RetroactiveEntryRequestType.PROGRESS


def requires_retroactive_progress_authorization(target_date: date, *, today: date | None = None) -> bool:
    """Keep the ordinary FIELD window limited to today and yesterday."""
    return target_date < ((today or date.today()) - timedelta(days=1))


def create_retroactive_progress_request(*, project, target_date, reason, actor, request=None):
    require_role(actor, [Role.FIELD], request=request)
    require_project_access(actor, project.id)
    if not requires_retroactive_progress_authorization(target_date):
        raise ValidationError("일반 입력 가능기간(오늘/어제)의 진행률은 소급 승인 요청이 필요하지 않습니다.")
    reason = (reason or "").strip()
    if not reason:
        raise ValidationError("소급 입력 요청 사유를 입력해 주세요.")
    guard_write(
        project=project,
        target_date=target_date,
        message_context="진행률 소급 입력 요청입니다.",
        exc=PermissionDenied,
    )

    active_scope = {
        "requested_by": actor,
        "project": project,
        "target_date": target_date,
        "request_type": RETRO_PROGRESS_REQUEST_TYPE,
        "status__in": [
            RetroactiveEntryRequestStatus.PENDING,
            RetroactiveEntryRequestStatus.APPROVED,
        ],
    }
    with transaction.atomic():
        existing = RetroactiveEntryRequest.objects.select_for_update().filter(**active_scope).first()
        if existing is not None:
            return existing, False
        try:
            retro_request = RetroactiveEntryRequest.objects.create(
                requested_by=actor,
                project=project,
                target_date=target_date,
                request_type=RETRO_PROGRESS_REQUEST_TYPE,
                reason=reason,
            )
        except IntegrityError:
            retro_request = RetroactiveEntryRequest.objects.get(**active_scope)
            return retro_request, False
        log_action(
            actor=actor,
            action="RETRO_PROGRESS_REQUEST_CREATED",
            object_type=RETRO_PROGRESS_OBJECT_TYPE,
            object_id=retro_request.id,
            project=project,
            request=request,
            after={
                "status": retro_request.status,
                "target_date": str(target_date),
                "reason": reason,
            },
        )
    return retro_request, True


def _review_retroactive_progress_request(*, retro_request, actor, approved, review_comment="", request=None):
    require_role(actor, [Role.HQ, Role.CEO], request=request)
    review_comment = (review_comment or "").strip()
    if not approved and not review_comment:
        raise ValidationError("반려 사유를 입력해 주세요.")

    with transaction.atomic():
        retro_request = (
            RetroactiveEntryRequest.objects.select_for_update()
            .select_related("project", "requested_by")
            .get(pk=retro_request.pk)
        )
        if retro_request.requested_by_id == actor.id:
            raise PermissionDenied("본인이 요청한 소급 입력은 승인하거나 반려할 수 없습니다.")
        if retro_request.status != RetroactiveEntryRequestStatus.PENDING:
            raise ValidationError("승인 대기 상태의 소급 입력 요청만 처리할 수 있습니다.")
        guard_write(
            project=retro_request.project,
            target_date=retro_request.target_date,
            message_context="진행률 소급 입력 요청 처리입니다.",
            exc=PermissionDenied,
        )
        retro_request.status = (
            RetroactiveEntryRequestStatus.APPROVED
            if approved
            else RetroactiveEntryRequestStatus.REJECTED
        )
        retro_request.reviewed_by = actor
        retro_request.reviewed_at = timezone.now()
        retro_request.review_comment = review_comment
        retro_request.save(
            update_fields=["status", "reviewed_by", "reviewed_at", "review_comment", "updated_at"]
        )
        log_action(
            actor=actor,
            action=("RETRO_PROGRESS_REQUEST_APPROVED" if approved else "RETRO_PROGRESS_REQUEST_REJECTED"),
            object_type=RETRO_PROGRESS_OBJECT_TYPE,
            object_id=retro_request.id,
            project=retro_request.project,
            request=request,
            before={"status": RetroactiveEntryRequestStatus.PENDING},
            after={"status": retro_request.status, "review_comment": review_comment},
            meta={
                "requested_by_id": retro_request.requested_by_id,
                "target_date": str(retro_request.target_date),
            },
        )
    return retro_request


def approve_retroactive_progress_request(*, retro_request, actor, review_comment="", request=None):
    return _review_retroactive_progress_request(
        retro_request=retro_request,
        actor=actor,
        approved=True,
        review_comment=review_comment,
        request=request,
    )


def reject_retroactive_progress_request(*, retro_request, actor, review_comment, request=None):
    return _review_retroactive_progress_request(
        retro_request=retro_request,
        actor=actor,
        approved=False,
        review_comment=review_comment,
        request=request,
    )


def get_retroactive_progress_request(*, project, target_date, actor):
    return (
        RetroactiveEntryRequest.objects.filter(
            requested_by=actor,
            project=project,
            target_date=target_date,
            request_type=RETRO_PROGRESS_REQUEST_TYPE,
        )
        .select_related("reviewed_by")
        .order_by("-requested_at", "-id")
        .first()
    )


def require_approved_retroactive_progress_request(*, project, target_date, actor, lock=False):
    queryset = RetroactiveEntryRequest.objects.filter(
        requested_by=actor,
        project=project,
        target_date=target_date,
        request_type=RETRO_PROGRESS_REQUEST_TYPE,
    )
    if lock:
        queryset = queryset.select_for_update()
    retro_request = queryset.filter(status=RetroactiveEntryRequestStatus.APPROVED).first()
    if retro_request is not None:
        return retro_request
    if queryset.filter(status=RetroactiveEntryRequestStatus.USED).exists():
        raise ValidationError("소급 입력 승인 요청을 이미 사용했습니다. 새 요청이 필요합니다.")
    if queryset.exists():
        raise ValidationError("소급 입력 요청이 아직 승인되지 않았습니다. HQ 처리 상태를 확인해 주세요.")
    raise ValidationError("소급 입력은 HQ 승인이 필요합니다. 소급 입력 요청을 제출해 주세요.")


def consume_retroactive_progress_request(*, retro_request, actor, progress, request=None):
    if retro_request.status != RetroactiveEntryRequestStatus.APPROVED:
        raise ValidationError("승인된 소급 입력 요청만 사용할 수 있습니다.")
    if (
        retro_request.requested_by_id != actor.id
        or retro_request.project_id != progress.project_id
        or retro_request.target_date != progress.report_date
        or retro_request.request_type != RETRO_PROGRESS_REQUEST_TYPE
    ):
        raise ValidationError("소급 입력 승인 범위가 현재 진행률과 일치하지 않습니다.")
    retro_request.status = RetroactiveEntryRequestStatus.USED
    retro_request.used_at = timezone.now()
    retro_request.save(update_fields=["status", "used_at", "updated_at"])
    log_action(
        actor=actor,
        action="RETRO_PROGRESS_AUTHORIZATION_CONSUMED",
        object_type=RETRO_PROGRESS_OBJECT_TYPE,
        object_id=retro_request.id,
        project=progress.project,
        request=request,
        before={"status": RetroactiveEntryRequestStatus.APPROVED},
        after={"status": retro_request.status, "used_at": retro_request.used_at.isoformat()},
        meta={"progress_id": progress.id, "target_date": str(progress.report_date)},
    )
