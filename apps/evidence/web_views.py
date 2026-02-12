from __future__ import annotations

from django.contrib.auth.decorators import login_required
from django.core.exceptions import PermissionDenied
from django.shortcuts import get_object_or_404, redirect, render

from apps.audit.constants import EVIDENCE_FILE_ADD, EVIDENCE_UPDATE
from apps.audit.services.logger import log_action
from apps.core.models import ApprovalRequest, ApprovalStatus
from apps.core.rbac.models import Role
from apps.core.rbac.permissions import get_user_role, require_project_access
from apps.cost.models import CostActual
from apps.evidence.attachment_policy import can_edit_attachments
from apps.contracts.models import ContractChange
from apps.evidence.models import Evidence, EvidenceFile, EvidenceStatus
from apps.evidence.services.resolve import (
    is_project_or_month_locked,
    resolve_project_for_evidence,
    resolve_target_date_for_evidence,
)
from apps.field.models import DailyReport
from apps.schedule.models import PlanChangeRequest


_LOCKED_STATUSES = {"APPROVED", "FINAL", "LOCKED"}
_APPROVED_VALUES = {"APPROVED", "FINAL", "LOCKED", "CLOSED"}


def _get_target_object(evidence):
    if evidence.object_type == "CONTRACT_CHANGE":
        return ContractChange.objects.filter(id=evidence.object_id).first()
    if evidence.object_type == "PLAN_CHANGE_REQUEST":
        return PlanChangeRequest.objects.filter(id=evidence.object_id).first()
    if evidence.object_type == "COST_ACTUAL":
        return CostActual.objects.filter(id=evidence.object_id).first()
    if evidence.object_type == "DAILY_REPORT":
        return DailyReport.objects.filter(id=evidence.object_id).first()
    return None


def _is_locked_for_field(evidence) -> bool:
    target_date = resolve_target_date_for_evidence(evidence)
    project = resolve_project_for_evidence(evidence)
    is_closed_locked = is_project_or_month_locked(project=project, target_date=target_date)
    if not can_edit_attachments(status=evidence.status, is_closed_locked=is_closed_locked):
        return True
    target = _get_target_object(evidence)
    if target is None or not hasattr(target, "status"):
        return _is_approval_locked(evidence)
    status_value = str(getattr(target, "status", ""))
    if status_value.upper() in _LOCKED_STATUSES:
        return True
    if getattr(target, "approved_at", None):
        return True
    approval_status = str(getattr(target, "approval_status", "")).upper()
    if approval_status in _APPROVED_VALUES:
        return True
    if getattr(target, "is_approved", False):
        return True
    return _is_approval_locked(evidence)


def _is_approval_locked(evidence) -> bool:
    return ApprovalRequest.objects.filter(
        object_type=evidence.object_type,
        object_id=evidence.object_id,
        status=ApprovalStatus.APPROVED,
    ).exists()


def _dedupe_project_evidence(evidence):
    if evidence.object_type != "PROJECT":
        return
    Evidence.objects.filter(
        object_type="PROJECT",
        object_id=evidence.object_id,
        created_by=evidence.created_by,
        status__in=[EvidenceStatus.DRAFT, EvidenceStatus.SUBMITTED],
    ).exclude(id=evidence.id).delete()


@login_required
def evidence_edit(request, pk):
    evidence = get_object_or_404(Evidence, pk=pk)
    project = resolve_project_for_evidence(evidence)
    target_date = resolve_target_date_for_evidence(evidence)
    is_closed_locked = is_project_or_month_locked(project=project, target_date=target_date)
    if project is not None:
        require_project_access(request.user, project.id)

    role = get_user_role(request.user)
    if role == Role.FIELD:
        if evidence.created_by_id != request.user.id:
            raise PermissionDenied("Evidence edit not allowed.")
        if _is_locked_for_field(evidence):
            raise PermissionDenied("Evidence is locked after approval.")
    elif not can_edit_attachments(status=evidence.status, is_closed_locked=is_closed_locked):
        raise PermissionDenied("현재 상태에서는 첨부를 수정할 수 없습니다.")

    if request.method == "POST":
        title = (request.POST.get("title") or "").strip()
        description = (request.POST.get("description") or "").strip()
        file_obj = request.FILES.get("file")
        if not title:
            return render(
                request,
                "app/evidence_edit.html",
                {"evidence": evidence, "error": "Title is required."},
            )
        before = {"title": evidence.title, "description": evidence.description}
        evidence.title = title
        evidence.description = description
        evidence.save(update_fields=["title", "description", "updated_at"])
        _dedupe_project_evidence(evidence)
        log_action(
            actor=request.user,
            action=EVIDENCE_UPDATE,
            object_type="EVIDENCE",
            object_id=evidence.id,
            project=project,
            request=request,
            before=before,
            after={"title": evidence.title, "description": evidence.description},
            meta={"object_type": evidence.object_type, "object_id": evidence.object_id},
        )
        if file_obj:
            evidence_file = EvidenceFile.objects.create(
                evidence=evidence,
                file=file_obj,
                original_name=file_obj.name,
                content_type=getattr(file_obj, "content_type", "")
                or "application/octet-stream",
                size_bytes=file_obj.size,
                sha256="",
                created_by=request.user,
            )
            log_action(
                actor=request.user,
                action=EVIDENCE_FILE_ADD,
                object_type="EVIDENCE",
                object_id=evidence.id,
                project=project,
                request=request,
                after={"file_id": evidence_file.id},
                meta={
                    "original_name": evidence_file.original_name,
                    "size_bytes": evidence_file.size_bytes,
                    "content_type": evidence_file.content_type,
                    "sha256": evidence_file.sha256,
                },
            )
        if project is not None:
            return redirect(f"/app/field/?tab=report&project_id={project.id}")
        return redirect("/app/field/")

    return render(request, "app/evidence_edit.html", {"evidence": evidence})
