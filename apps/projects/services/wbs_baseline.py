from __future__ import annotations

from typing import Any

from django.utils import timezone

from apps.projects.models import (
    WBSChangeRequest,
    WBSChangeRequestStatus,
    WBSChangeRequestType,
    WBSItem,
)

# Discovery (T10-5-4)
# - Project model: apps/projects/models.py -> Project (current_wbs_version may exist)
# - WBSChangeRequest: apps/projects/models.py -> WBSChangeRequest (status, proposed_version, approved_at, approved_by, base_version)
# - WBS baseline: apps/projects/models.py -> WBSItem (baseline_version, is_baseline)
# - Project detail templates: apps/ceo/templates/ceo/project_detail.html, templates/app/hq_project_detail.html


TYPE_LABELS = {
    WBSChangeRequestType.DESIGN_CONTRACT_CHANGE: "설계/계약 변경",
    WBSChangeRequestType.SCHEDULE_ADJUSTMENT: "공정 조정",
}


def _user_label(user) -> str | None:
    if not user:
        return None
    full_name = getattr(user, "get_full_name", lambda: "")()
    return full_name or getattr(user, "username", None) or None


def _approved_requests(project):
    return (
        WBSChangeRequest.objects.filter(
            project=project,
            status=WBSChangeRequestStatus.APPROVED,
            proposed_version__isnull=False,
            approved_at__isnull=False,
        )
        .select_related("approved_by")
        .order_by("proposed_version", "approved_at")
    )


def get_current_wbs_version(project) -> int:
    current = getattr(project, "current_wbs_version", None)
    if isinstance(current, int) and current > 0:
        return current
    max_version = (
        WBSItem.objects.filter(project=project, is_baseline=True)
        .order_by("-baseline_version")
        .values_list("baseline_version", flat=True)
        .first()
    )
    return max_version or 1


def get_wbs_baseline_badge(project) -> dict[str, Any]:
    current_version = get_current_wbs_version(project)
    last_request = _approved_requests(project).last()
    last_change_at = last_request.approved_at if last_request else None
    last_change_by = _user_label(last_request.approved_by) if last_request else None

    label = f"기준선 v{current_version} 적용중"
    sub_label = None
    if last_change_at:
        date_str = timezone.localtime(last_change_at).date()
        sub_label = f"최근 변경: {date_str}"
        if last_change_by:
            sub_label = f"{sub_label} ({last_change_by})"

    return {
        "show": current_version > 1,
        "current_version": current_version,
        "last_change_at": last_change_at,
        "last_change_by": last_change_by,
        "label": label,
        "sub_label": sub_label,
    }


def get_wbs_baseline_history(project, limit: int = 20) -> list[dict[str, Any]]:
    history = []
    prev_to = None
    qs = _approved_requests(project)
    if limit:
        qs = qs[:limit]
    for req in qs:
        from_version = req.base_version or prev_to
        history.append(
            {
                "from_version": from_version,
                "to_version": req.proposed_version,
                "approved_at": req.approved_at,
                "approved_by": _user_label(req.approved_by),
                "request_type": req.request_type,
                "request_type_label": TYPE_LABELS.get(req.request_type, req.request_type),
                "reason": req.reason,
                "request_id": req.id,
            }
        )
        prev_to = req.proposed_version
    return history
