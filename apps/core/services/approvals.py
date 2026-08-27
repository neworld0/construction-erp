from django.db import transaction
from django.utils import timezone

from apps.audit.constants import APPROVAL_APPROVE, APPROVAL_REJECT
from apps.audit.services.logger import log_action
from apps.cost.models import CostActual, CostActualStatus
from apps.core.models import ApprovalRequest, ApprovalStatus
from apps.field.models import DailyReport, DailyReportStatus
from apps.reports.models import FieldReport, FieldReportStatus
from apps.schedule.models import DailyProgress


def _sync_target_status_on_approve(approval, user, _visited=None):
    if _visited is None:
        _visited = set()
    if approval.id in _visited:
        return
    _visited.add(approval.id)

    object_type = (approval.object_type or "").upper()
    if object_type == "CLOSING_PERIOD":
        from apps.closing.models import ClosingApprovalPolicy, ClosingStatus
        from apps.closing.services import close_month

        from apps.closing.models import ClosingPeriod

        period = ClosingPeriod.objects.filter(id=approval.object_id).first()
        if period is not None and period.approval_policy != ClosingApprovalPolicy.CEO:
            raise ValueError("CEO 예외 승인으로 요청된 월 마감만 CEO가 승인할 수 있습니다.")
        if period is not None and period.status != ClosingStatus.CLOSED:
            close_month(
                period.year,
                period.month,
                user,
                legal_entity=period.legal_entity,
                note=approval.comment,
            )
        return
    if object_type == "PROJECT_BASELINE":
        from apps.projects.models import Project, ProjectStatus

        Project.objects.filter(
            id=approval.object_id,
            status=ProjectStatus.SUBMITTED,
        ).update(status=ProjectStatus.APPROVED, updated_at=timezone.now())
        return
    if object_type == "APPROVAL_REQUEST":
        nested = ApprovalRequest.objects.filter(id=approval.object_id).first()
        if nested:
            if nested.status == ApprovalStatus.SUBMITTED:
                nested.status = ApprovalStatus.APPROVED
                nested.approved_by = user
                nested.approved_at = approval.approved_at
                nested.save(update_fields=["status", "approved_by", "approved_at"])
            # Always recurse for nested approvals so target object status cannot stay stale.
            _sync_target_status_on_approve(nested, user, _visited)
        return
    if object_type == "COST_ACTUAL":
        CostActual.objects.filter(id=approval.object_id).update(
            status=CostActualStatus.APPROVED,
            approved_by=user,
            approved_at=approval.approved_at,
        )
        from apps.inventory.models import IssueStatus, IssueToWork

        IssueToWork.objects.filter(cost_actual_id=approval.object_id).update(
            status=IssueStatus.APPROVED,
            approved_by=user,
            approved_at=approval.approved_at,
        )
        cost_actual = CostActual.objects.filter(id=approval.object_id).select_related("project").first()
        # DailyReport is the source record of a CostActual, not a separate
        # approval work item.  Keep its lifecycle synchronized so it cannot
        # remain as a phantom submitted report after the cost is approved.
        if cost_actual is not None and cost_actual.source_daily_report_id:
            DailyReport.objects.filter(id=cost_actual.source_daily_report_id).update(
                status=DailyReportStatus.APPROVED,
            )
        if cost_actual is not None:
            from apps.finance.services.expense_execution import queue_ceo_approved_cost_execution

            queue_ceo_approved_cost_execution(
                cost_actual=cost_actual,
                actor=user,
                approved_at=approval.approved_at,
            )
        return
    if object_type == "DAILY_PROGRESS":
        DailyProgress.objects.filter(id=approval.object_id).update(
            status="approved",
            approved_by=user,
            approved_at=approval.approved_at,
            rejected_by=None,
            rejected_at=None,
            reject_reason="",
        )
        return
    if object_type == "PROGRESS_CORRECTION":
        from apps.schedule.progress_corrections import approve_progress_correction

        approve_progress_correction(correction_id=approval.object_id, actor=user)
        return
    if object_type == "DAILY_REPORT":
        DailyReport.objects.filter(id=approval.object_id).update(
            status=DailyReportStatus.APPROVED
        )
        return
    if object_type == "FIELD_REPORT":
        FieldReport.objects.filter(id=approval.object_id).update(
            status=FieldReportStatus.APPROVED,
            approved_at=approval.approved_at,
        )


def _sync_target_status_on_reject(approval, user=None, _visited=None):
    if _visited is None:
        _visited = set()
    if approval.id in _visited:
        return
    _visited.add(approval.id)

    object_type = (approval.object_type or "").upper()
    if object_type == "PROJECT_BASELINE":
        from apps.projects.models import Project, ProjectStatus

        # A rejected baseline returns to HQ rework, but never reopens a closed project.
        Project.objects.filter(
            id=approval.object_id,
            status=ProjectStatus.SUBMITTED,
        ).update(status=ProjectStatus.DRAFT, updated_at=timezone.now())
        return
    if object_type == "APPROVAL_REQUEST":
        nested = ApprovalRequest.objects.filter(id=approval.object_id).first()
        if nested and nested.status == ApprovalStatus.SUBMITTED:
            nested.status = ApprovalStatus.REJECTED
            nested.save(update_fields=["status"])
            _sync_target_status_on_reject(nested, user, _visited)
        return
    if object_type == "COST_ACTUAL":
        CostActual.objects.filter(id=approval.object_id).update(
            status=CostActualStatus.REJECTED,
        )
        from apps.inventory.models import IssueStatus, IssueToWork

        IssueToWork.objects.filter(cost_actual_id=approval.object_id).update(
            status=IssueStatus.REJECTED,
        )
        cost_actual = CostActual.objects.filter(id=approval.object_id).only(
            "source_daily_report_id"
        ).first()
        if cost_actual is not None and cost_actual.source_daily_report_id:
            DailyReport.objects.filter(id=cost_actual.source_daily_report_id).update(
                status=DailyReportStatus.REJECTED,
            )
        return
    if object_type == "DAILY_PROGRESS":
        DailyProgress.objects.filter(id=approval.object_id).update(
            status="rejected",
            rejected_by=user,
            rejected_at=timezone.now(),
            reject_reason=(approval.reject_reason or "").strip(),
        )
        return
    if object_type == "PROGRESS_CORRECTION":
        from apps.schedule.progress_corrections import reject_progress_correction

        reject_progress_correction(
            correction_id=approval.object_id, actor=user, reason=approval.reject_reason
        )
        return
    if object_type == "DAILY_REPORT":
        DailyReport.objects.filter(id=approval.object_id).update(
            status=DailyReportStatus.REJECTED
        )
        return
    if object_type == "FIELD_REPORT":
        FieldReport.objects.filter(id=approval.object_id).update(status=FieldReportStatus.REJECTED)


def _resolve_approval_project(approval):
    object_type = (approval.object_type or "").upper()
    if object_type == "PROJECT_BASELINE":
        from apps.projects.models import Project

        return Project.objects.filter(id=approval.object_id).first()
    if object_type == "APPROVAL_REQUEST":
        nested = ApprovalRequest.objects.filter(id=approval.object_id).first()
        if nested:
            return _resolve_approval_project(nested)
        return None
    if object_type == "COST_ACTUAL":
        cost_actual = CostActual.objects.filter(id=approval.object_id).select_related("project").first()
        return cost_actual.project if cost_actual else None
    if object_type == "DAILY_PROGRESS":
        progress = DailyProgress.objects.filter(id=approval.object_id).select_related("project").first()
        return progress.project if progress else None
    if object_type == "PROGRESS_CORRECTION":
        from apps.schedule.models import ProgressCorrectionRequest

        correction = ProgressCorrectionRequest.objects.filter(id=approval.object_id).select_related("project").first()
        return correction.project if correction else None
    if object_type == "DAILY_REPORT":
        report = DailyReport.objects.filter(id=approval.object_id).select_related("project").first()
        return report.project if report else None
    if object_type == "FIELD_REPORT":
        report = FieldReport.objects.filter(id=approval.object_id).select_related("project").first()
        return report.project if report else None
    return None


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

        _sync_target_status_on_approve(approval, user)

        if failpoint == "after_status":
            raise RuntimeError("failpoint after_status")

        project = _resolve_approval_project(approval)
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

        _sync_target_status_on_reject(approval, user)

        if failpoint == "after_status":
            raise RuntimeError("failpoint after_status")

        project = _resolve_approval_project(approval)
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
