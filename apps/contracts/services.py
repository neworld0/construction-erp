from django.db import transaction
from django.utils import timezone

from apps.audit.constants import CONTRACT_APPROVE
from apps.audit.services.logger import log_action
from apps.risk.services.engine import emit_event

from .models import ContractChange, ContractChangeStatus, ContractSnapshot


def get_active_contract_snapshot(project_id):
    if not project_id:
        return None
    return (
        ContractSnapshot.objects.filter(project_id=project_id, is_active=True)
        .order_by("-version_no")
        .first()
    )


def create_new_snapshot_from_change(contract_change):
    active = (
        ContractSnapshot.objects.select_for_update()
        .filter(project_id=contract_change.project_id, is_active=True)
        .order_by("-version_no")
        .first()
    )
    base_amount = (
        active.base_contract_amount
        if active is not None
        else contract_change.project.contract_amount
    )
    new_amount = base_amount + (contract_change.contract_amount_delta or 0)
    latest = (
        ContractSnapshot.objects.select_for_update()
        .filter(project=contract_change.project)
        .order_by("-version_no")
        .first()
    )
    next_version = (latest.version_no if latest else 0) + 1
    ContractSnapshot.objects.filter(
        project=contract_change.project, is_active=True
    ).update(is_active=False)
    return ContractSnapshot.objects.create(
        project=contract_change.project,
        version_no=next_version,
        base_contract_amount=new_amount,
        start_date=None,
        end_date=None,
        is_active=True,
        source_change=contract_change,
    )


def approve_contract_change(change_id, approver, request=None, failpoint=None):
    with transaction.atomic():
        change = (
            ContractChange.objects.select_for_update()
            .select_related("project")
            .get(id=change_id)
        )
        if change.status != ContractChangeStatus.SUBMITTED:
            raise ValueError("Only submitted contract changes can be approved.")

        before_status = change.status
        change.status = ContractChangeStatus.APPROVED
        change.approved_by = approver
        change.approved_at = timezone.now()
        change.save(update_fields=["status", "approved_by", "approved_at"])

        if failpoint == "after_status":
            raise RuntimeError("failpoint after_status")

        log_action(
            actor=approver,
            action=CONTRACT_APPROVE,
            object_type="CONTRACT_CHANGE",
            object_id=change.id,
            project=change.project,
            request=request,
            before={"status": before_status},
            after={"status": change.status},
            meta={
                "contract_amount_delta": str(change.contract_amount_delta),
                "time_extension_days": change.time_extension_days,
            },
        )
        create_new_snapshot_from_change(change)
        emit_event(
            "CONTRACT_APPROVED",
            "CONTRACT_CHANGE",
            change.id,
            {
                "contract_amount_delta": str(change.contract_amount_delta),
                "time_extension_days": change.time_extension_days,
            },
            actor=approver,
        )
        return change
