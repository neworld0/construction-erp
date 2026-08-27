from dataclasses import dataclass

from apps.core.models import ApprovalRequest, ApprovalStatus
from apps.projects.models import ProjectStatus


@dataclass(frozen=True)
class ProjectBaselineWorkflow:
    label: str
    can_hq_edit: bool
    can_hq_resubmit: bool
    is_rejected: bool = False
    rejection_reason: str = ""


def get_project_baseline_workflow(project) -> ProjectBaselineWorkflow:
    """Return the HQ baseline state, with the latest CEO rejection taking precedence."""
    if project is None:
        return ProjectBaselineWorkflow("-", False, False)

    approval = (
        ApprovalRequest.objects.filter(
            object_type="PROJECT_BASELINE",
            object_id=project.id,
        )
        .order_by("-updated_at", "-id")
        .first()
    )
    if project.status == ProjectStatus.CLOSED:
        return ProjectBaselineWorkflow("마감", False, False)
    if approval and approval.status == ApprovalStatus.REJECTED:
        return ProjectBaselineWorkflow(
            "반려됨",
            True,
            True,
            is_rejected=True,
            rejection_reason=approval.reject_reason or "",
        )
    if project.status == ProjectStatus.APPROVED:
        return ProjectBaselineWorkflow("승인완료", False, False)
    if project.status == ProjectStatus.SUBMITTED:
        return ProjectBaselineWorkflow("제출됨", False, False)
    return ProjectBaselineWorkflow("작성중", True, False)


def is_baseline_locked(project) -> bool:
    if project is None:
        return True
    return not get_project_baseline_workflow(project).can_hq_edit
