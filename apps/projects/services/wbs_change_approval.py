from __future__ import annotations

from decimal import Decimal

from django.db import transaction
from django.utils import timezone

from apps.audit.services.logger import log_action
from apps.contracts.models import ContractChangeStatus
from apps.projects.models import (
    Project,
    WBSChangeLine,
    WBSChangeRequest,
    WBSChangeRequestStatus,
    WBSChangeRequestType,
    WBSItem,
)


def _sum_weights(lines: list[WBSChangeLine]) -> Decimal:
    total = Decimal("0")
    for line in lines:
        total += Decimal(str(line.weight or 0))
    return total


def _max_baseline_version(project: Project) -> int:
    return (
        WBSItem.objects.filter(project=project)
        .order_by("-baseline_version")
        .values_list("baseline_version", flat=True)
        .first()
        or 1
    )


def approve_wbs_change_request(
    change_request: WBSChangeRequest,
    *,
    actor,
    request=None,
    in_package: bool = False,
) -> int:
    if change_request.status != WBSChangeRequestStatus.SUBMITTED:
        raise ValueError("Only submitted WBS change requests can be approved.")
    if (
        change_request.request_type == WBSChangeRequestType.DESIGN_CONTRACT_CHANGE
        and change_request.change_order
        and change_request.change_order.status != ContractChangeStatus.APPROVED
    ):
        raise ValueError("Change order must be approved before WBS approval.")

    request_lines = list(change_request.lines.order_by("order", "id"))
    if not request_lines:
        raise ValueError("WBS change request must include at least one line.")
    weight_sum = _sum_weights(request_lines)
    if abs(weight_sum - Decimal("100")) > Decimal("0.1"):
        raise ValueError("WBS weight sum must be 100.")
    for line in request_lines:
        if line.planned_start and line.planned_end and line.planned_start > line.planned_end:
            raise ValueError("Planned start date must be before planned end date.")

    with transaction.atomic():
        project = Project.objects.select_for_update().get(id=change_request.project_id)
        change_request = (
            WBSChangeRequest.objects.select_for_update()
            .select_related("project")
            .get(id=change_request.id)
        )
        max_version = _max_baseline_version(project)
        new_version = max_version + 1

        WBSItem.objects.bulk_create(
            [
                WBSItem(
                    project=project,
                    name=line.task_name,
                    weight=line.weight,
                    plan_start_date=line.planned_start,
                    plan_end_date=line.planned_end,
                    sort_order=idx,
                    baseline_version=new_version,
                    is_baseline=True,
                )
                for idx, line in enumerate(request_lines, start=1)
            ]
        )

        change_request.proposed_version = new_version
        change_request.status = WBSChangeRequestStatus.APPROVED
        change_request.approved_by = actor
        change_request.approved_at = timezone.now()
        change_request.save(
            update_fields=[
                "proposed_version",
                "status",
                "approved_by",
                "approved_at",
                "updated_at",
            ]
        )

        if hasattr(project, "current_wbs_version"):
            project.current_wbs_version = new_version
            project.save(update_fields=["current_wbs_version"])

    log_action(
        actor=actor,
        action="WBS_CHANGE_REQUEST_APPROVE",
        object_type="WBSChangeRequest",
        object_id=change_request.id,
        project=project,
        request=request,
        after={
            "base_version": change_request.base_version,
            "new_version": change_request.proposed_version,
            "lines_count": len(request_lines),
            "in_package": in_package,
        },
    )
    return new_version

