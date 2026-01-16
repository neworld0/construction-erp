from django.db import transaction
from django.utils import timezone

from apps.audit.constants import APPROVAL_APPROVE, APPROVAL_REJECT
from apps.audit.services.logger import log_action
from apps.cost.models import CostActual, CostActualStatus
from apps.core.models import ApprovalRequest, ApprovalStatus


def approve_request(approval_id, user, comment=None, request=None, failpoint=None):
    with transaction.atomic():
        approval = ApprovalRequest.objects.select_for_update().get(id=approval_id)
        if approval.status != ApprovalStatus.SUBMITTED:
            raise ValueError("Approval request is not submitted.")

        before_status = approval.status
        approval.status = ApprovalStatus.APPROVED
        approval.approved_by = user
        approval.approved_at = timezone.now()
        if comment is not None:
            approval.comment = comment
        approval.save()

        if approval.object_type == "COST_ACTUAL":
            CostActual.objects.filter(id=approval.object_id).update(
                status=CostActualStatus.APPROVED,
                approved_by=user,
                approved_at=approval.approved_at,
            )

        if failpoint == "after_status":
            raise RuntimeError("failpoint after_status")

        project = None
        cost_actual = CostActual.objects.filter(id=approval.object_id).first()
        if cost_actual:
            project = cost_actual.project
        log_action(
            actor=user,
            action=APPROVAL_APPROVE,
            object_type="APPROVAL_REQUEST",
            object_id=approval.id,
            project=project,
            request=request,
            before={"status": before_status},
            after={"status": approval.status},
        )

        return approval


def reject_request(approval_id, user, reject_reason=None, comment=None, request=None, failpoint=None):
    with transaction.atomic():
        approval = ApprovalRequest.objects.select_for_update().get(id=approval_id)
        if approval.status != ApprovalStatus.SUBMITTED:
            raise ValueError("Approval request is not submitted.")

        before_status = approval.status
        approval.status = ApprovalStatus.REJECTED
        if reject_reason is not None:
            approval.reject_reason = reject_reason
        if comment is not None:
            approval.comment = comment
        approval.save()

        if approval.object_type == "COST_ACTUAL":
            CostActual.objects.filter(id=approval.object_id).update(
                status=CostActualStatus.REJECTED,
            )

        if failpoint == "after_status":
            raise RuntimeError("failpoint after_status")

        project = None
        cost_actual = CostActual.objects.filter(id=approval.object_id).first()
        if cost_actual:
            project = cost_actual.project
        log_action(
            actor=user,
            action=APPROVAL_REJECT,
            object_type="APPROVAL_REQUEST",
            object_id=approval.id,
            project=project,
            request=request,
            before={"status": before_status},
            after={"status": approval.status},
        )

        return approval
