from __future__ import annotations

from dataclasses import dataclass
from datetime import date
from typing import Iterable

from django.db import transaction
from django.utils import timezone

from apps.audit.constants import PACKAGE_APPROVE, PACKAGE_REJECT, PACKAGE_SUBMIT
from apps.audit.services.logger import log_action
from apps.closing.guards import guard_write
from apps.contracts.models import ContractChange, ContractChangeStatus
from apps.contracts.services import approve_contract_change
from apps.projects.models import (
    ApprovalPackage,
    ApprovalPackageItem,
    ApprovalPackageItemType,
    ApprovalPackageStatus,
    WBSChangeRequest,
    WBSChangeRequestStatus,
)
from apps.projects.services.wbs_baseline import get_current_wbs_version

from .wbs_change_approval import approve_wbs_change_request

# Discovery (T10-5-5):
# - WBSChangeRequest: apps/projects/models.py (status, base_version, proposed_version)
# - ContractChange: apps/contracts/models.py (status, contract_amount_delta)
# - ProjectContract: apps/projects/models.py (contract_amount)
# - BudgetItem: apps/projects/models.py (planned_amount)


@dataclass
class PackageItemRef:
    item: ApprovalPackageItem
    obj: object


def _load_items_for_update(package: ApprovalPackage) -> list[PackageItemRef]:
    refs: list[PackageItemRef] = []
    for item in package.items.all():
        if item.item_type == ApprovalPackageItemType.CHANGE_ORDER:
            obj = ContractChange.objects.select_for_update().get(id=item.object_id)
        elif item.item_type == ApprovalPackageItemType.WBS_CHANGE:
            obj = WBSChangeRequest.objects.select_for_update().get(id=item.object_id)
        else:
            raise ValueError(f"Unsupported package item type: {item.item_type}")
        refs.append(PackageItemRef(item=item, obj=obj))
    return refs


def _ensure_submitted(refs: Iterable[PackageItemRef]) -> None:
    for ref in refs:
        if isinstance(ref.obj, ContractChange):
            if ref.obj.status != ContractChangeStatus.SUBMITTED:
                raise ValueError("All contract changes must be SUBMITTED.")
        elif isinstance(ref.obj, WBSChangeRequest):
            if ref.obj.status != WBSChangeRequestStatus.SUBMITTED:
                raise ValueError("All WBS change requests must be SUBMITTED.")


def submit_package(package_id: int, *, actor, request=None) -> ApprovalPackage:
    with transaction.atomic():
        package = ApprovalPackage.objects.select_for_update().get(id=package_id)
        if package.status != ApprovalPackageStatus.DRAFT:
            raise ValueError("Only draft packages can be submitted.")

        guard_write(
            project=package.project,
            target_date=date.today(),
            message_context="??? ?? ??????.",
        )

        refs = _load_items_for_update(package)
        for ref in refs:
            if isinstance(ref.obj, WBSChangeRequest):
                current_version = get_current_wbs_version(ref.obj.project)
                if ref.obj.base_version != current_version:
                    raise ValueError("WBS request base version is not current.")
                if ref.obj.status == WBSChangeRequestStatus.DRAFT:
                    ref.obj.status = WBSChangeRequestStatus.SUBMITTED
                    ref.obj.save(update_fields=["status", "updated_at"])
            elif isinstance(ref.obj, ContractChange):
                if ref.obj.status == ContractChangeStatus.DRAFT:
                    ref.obj.status = ContractChangeStatus.SUBMITTED
                    ref.obj.submitted_by = actor
                    ref.obj.submitted_at = timezone.now()
                    ref.obj.save(
                        update_fields=["status", "submitted_by", "submitted_at", "updated_at"]
                    )

        _ensure_submitted(refs)

        package.status = ApprovalPackageStatus.SUBMITTED
        package.submitted_at = timezone.now()
        package.save(update_fields=["status", "submitted_at", "updated_at"])

    log_action(
        actor=actor,
        action=PACKAGE_SUBMIT,
        object_type="APPROVAL_PACKAGE",
        object_id=package.id,
        project=package.project,
        request=request,
        after={
            "status": package.status,
            "items": [
                {"type": item.item_type, "object_id": item.object_id}
                for item in package.items.all()
            ],
        },
    )
    return package


def approve_package(package_id: int, *, actor, request=None) -> ApprovalPackage:
    with transaction.atomic():
        package = ApprovalPackage.objects.select_for_update().get(id=package_id)
        if package.status != ApprovalPackageStatus.SUBMITTED:
            raise ValueError("Only submitted packages can be approved.")

        _ = package.project
        package.project.refresh_from_db()
        refs = _load_items_for_update(package)
        _ensure_submitted(refs)

        new_version = None
        for ref in refs:
            if isinstance(ref.obj, ContractChange):
                approve_contract_change(ref.obj.id, actor, request=request)
            elif isinstance(ref.obj, WBSChangeRequest):
                new_version = approve_wbs_change_request(
                    ref.obj, actor=actor, request=request, in_package=True
                )

        package.status = ApprovalPackageStatus.APPROVED
        package.decided_by = actor
        package.decided_at = timezone.now()
        package.save(update_fields=["status", "decided_by", "decided_at", "updated_at"])

    log_action(
        actor=actor,
        action=PACKAGE_APPROVE,
        object_type="APPROVAL_PACKAGE",
        object_id=package.id,
        project=package.project,
        request=request,
        after={
            "status": package.status,
            "items": [
                {"type": item.item_type, "object_id": item.object_id}
                for item in package.items.all()
            ],
            "wbs_new_version": new_version,
        },
    )
    return package


def reject_package(
    package_id: int,
    *,
    actor,
    decision_note: str,
    request=None,
) -> ApprovalPackage:
    if not decision_note:
        raise ValueError("Decision note is required.")
    with transaction.atomic():
        package = ApprovalPackage.objects.select_for_update().get(id=package_id)
        if package.status != ApprovalPackageStatus.SUBMITTED:
            raise ValueError("Only submitted packages can be rejected.")

        refs = _load_items_for_update(package)
        for ref in refs:
            if isinstance(ref.obj, ContractChange):
                ref.obj.status = ContractChangeStatus.REJECTED
                ref.obj.approved_by = actor
                ref.obj.approved_at = timezone.now()
                ref.obj.save(
                    update_fields=["status", "approved_by", "approved_at", "updated_at"]
                )
            elif isinstance(ref.obj, WBSChangeRequest):
                ref.obj.status = WBSChangeRequestStatus.REJECTED
                ref.obj.approved_by = actor
                ref.obj.approved_at = timezone.now()
                ref.obj.decision_note = decision_note
                ref.obj.save(
                    update_fields=[
                        "status",
                        "approved_by",
                        "approved_at",
                        "decision_note",
                        "updated_at",
                    ]
                )

        package.status = ApprovalPackageStatus.REJECTED
        package.decided_by = actor
        package.decided_at = timezone.now()
        package.decision_note = decision_note
        package.save(
            update_fields=["status", "decided_by", "decided_at", "decision_note", "updated_at"]
        )

    log_action(
        actor=actor,
        action=PACKAGE_REJECT,
        object_type="APPROVAL_PACKAGE",
        object_id=package.id,
        project=package.project,
        request=request,
        after={
            "status": package.status,
            "decision_note": decision_note,
            "items": [
                {"type": item.item_type, "object_id": item.object_id}
                for item in package.items.all()
            ],
        },
    )
    return package
