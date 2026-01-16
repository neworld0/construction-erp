from django.db import transaction
from django.utils import timezone

from apps.audit.constants import PLAN_CHANGE_APPROVE
from apps.audit.services.logger import log_action
from apps.risk.services.engine import emit_event
from apps.schedule.models import PlanChangeRequest, PlanChangeStatus, SchedulePlan, ScheduleTask


def approve_change_request(change_request_id, approver, request=None, failpoint=None):
    with transaction.atomic():
        change_request = (
            PlanChangeRequest.objects.select_for_update()
            .select_related("base_plan", "project")
            .get(id=change_request_id)
        )

        if change_request.status != PlanChangeStatus.SUBMITTED:
            raise ValueError("Only submitted change requests can be approved.")

        base_plan = change_request.base_plan
        SchedulePlan.objects.filter(id=base_plan.id).update(is_active=False)
        new_plan = SchedulePlan.objects.create(
            project=base_plan.project,
            version_no=base_plan.version_no + 1,
            name=base_plan.name,
            is_active=True,
            created_by=approver,
        )

        tasks_payload = change_request.proposed_payload or []
        for item in tasks_payload:
            ScheduleTask.objects.create(
                plan=new_plan,
                name=item.get("name", ""),
                start_date=item.get("start_date"),
                end_date=item.get("end_date"),
                weight_percent=item.get("weight_percent", 0),
                sort_order=item.get("sort_order", 0),
                is_active=item.get("is_active", True),
            )

        before_status = change_request.status
        change_request.status = PlanChangeStatus.APPROVED
        change_request.approved_by = approver
        change_request.approved_at = timezone.now()
        change_request.save(update_fields=["status", "approved_by", "approved_at"])
        if failpoint == "after_new_plan":
            raise RuntimeError("failpoint after_new_plan")
        log_action(
            actor=approver,
            action=PLAN_CHANGE_APPROVE,
            object_type="PLAN_CHANGE_REQUEST",
            object_id=change_request.id,
            project=change_request.project,
            request=request,
            before={"status": before_status},
            after={"status": change_request.status},
            meta={
                "base_plan_id": base_plan.id,
                "base_version_no": base_plan.version_no,
                "new_plan_id": new_plan.id,
                "new_version_no": new_plan.version_no,
            },
        )
        emit_event(
            "PLAN_APPROVED",
            "PLAN_CHANGE_REQUEST",
            change_request.id,
            {"change_type": change_request.change_type},
            actor=approver,
        )

    return new_plan
