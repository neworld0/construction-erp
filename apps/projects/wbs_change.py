from __future__ import annotations

from datetime import date
from decimal import Decimal

from django.contrib import messages
from django.core.exceptions import PermissionDenied
from django.db import transaction
from django.forms import formset_factory
from django.shortcuts import get_object_or_404, redirect, render

from apps.closing.guards import guard_write
from apps.audit.constants import (
    WBS_CHANGE_REQUEST_SAVE_DRAFT,
    WBS_CHANGE_REQUEST_SUBMIT,
)
from apps.audit.services.logger import log_action
from apps.core.rbac.models import Role

from .forms import WBSChangeLineForm, WBSChangeRequestForm
from .models import (
    Project,
    WBSChangeLine,
    WBSChangeRequest,
    WBSChangeRequestStatus,
    WBSItem,
)


def _get_baseline_items(project: Project):
    baseline_qs = (
        WBSItem.objects.filter(project=project, is_baseline=True)
        .order_by("sort_order", "id")
    )
    if not baseline_qs.exists():
        baseline_qs = WBSItem.objects.filter(project=project).order_by(
            "sort_order", "id"
        )
    base_version = (
        baseline_qs.order_by("-baseline_version")
        .values_list("baseline_version", flat=True)
        .first()
        or 1
    )
    return list(baseline_qs), base_version


def _build_line_initial_from_baseline(baseline_items):
    initial = []
    for item in baseline_items:
        initial.append(
            {
                "task_name": item.name,
                "weight": item.weight,
                "planned_start": item.plan_start_date,
                "planned_end": item.plan_end_date,
                "note": "",
            }
        )
    return initial


def _extract_lines(formset):
    lines = []
    for form in formset:
        if not form.cleaned_data:
            continue
        if form.cleaned_data.get("DELETE"):
            continue
        task_name = (form.cleaned_data.get("task_name") or "").strip()
        weight = form.cleaned_data.get("weight") or Decimal("0")
        planned_start = form.cleaned_data.get("planned_start")
        planned_end = form.cleaned_data.get("planned_end")
        note = (form.cleaned_data.get("note") or "").strip()
        if not task_name and weight == 0 and not planned_start and not planned_end and not note:
            continue
        lines.append(
            {
                "task_name": task_name,
                "weight": weight,
                "planned_start": planned_start,
                "planned_end": planned_end,
                "note": note,
            }
        )
    return lines


def _validate_lines(lines, errors):
    if not lines:
        errors.append("WBS 라인은 1개 이상 입력해야 합니다.")
        return
    weight_sum = sum(Decimal(str(line.get("weight") or 0)) for line in lines)
    if abs(weight_sum - Decimal("100")) > Decimal("0.1"):
        errors.append("WBS 가중치 합계는 100%여야 합니다.")
    for line in lines:
        if not line.get("task_name"):
            errors.append("작업명이 비어있습니다.")
            break
    for line in lines:
        start = line.get("planned_start")
        end = line.get("planned_end")
        if start and end and start > end:
            errors.append("계획 시작일/종료일을 확인하세요.")
            break


def render_wbs_change_form(
    request,
    project: Project,
    role: str,
    template_name: str,
    back_url: str,
):
    # Discovery:
    # - WBS baseline model: projects.WBSItem (baseline_version, is_baseline)
    # - RBAC: Role from apps.core.rbac.models
    baseline_items, base_version = _get_baseline_items(project)
    draft_request = (
        WBSChangeRequest.objects.filter(
            project=project,
            requested_by=request.user,
            status=WBSChangeRequestStatus.DRAFT,
        )
        .order_by("-updated_at")
        .first()
    )
    request_instance = draft_request
    formset_factory_cls = formset_factory(WBSChangeLineForm, extra=0, can_delete=True)

    if request.method == "POST":
        request_id = request.POST.get("request_id")
        if request_id:
            request_instance = get_object_or_404(
                WBSChangeRequest, id=request_id, project=project
            )
        if request_instance and request_instance.status != WBSChangeRequestStatus.DRAFT:
            raise PermissionDenied("WBS change request is locked after submission.")

        form = WBSChangeRequestForm(request.POST, instance=request_instance)
        formset = formset_factory_cls(request.POST, prefix="lines")
        action = request.POST.get("action", "draft")

        if form.is_valid() and formset.is_valid():
            lines = _extract_lines(formset)
            errors = []
            if action == "submit":
                try:
                    guard_write(
                        project=project,
                        target_date=date.today(),
                        message_context="WBS ???? ?? ??????.",
                        exc=PermissionDenied,
                    )
                except PermissionDenied as exc:
                    messages.error(request, str(exc))
                    return redirect(request.path)
                _validate_lines(lines, errors)
            if errors:
                for error in errors:
                    messages.error(request, error)
            else:
                with transaction.atomic():
                    obj = form.save(commit=False)
                    obj.project = project
                    obj.requested_by = request.user
                    obj.role_snapshot = role
                    obj.base_version = base_version
                    obj.status = (
                        WBSChangeRequestStatus.SUBMITTED
                        if action == "submit"
                        else WBSChangeRequestStatus.DRAFT
                    )
                    obj.save()

                    WBSChangeLine.objects.filter(request=obj).delete()
                    for idx, line in enumerate(lines, start=1):
                        WBSChangeLine.objects.create(
                            request=obj,
                            order=idx,
                            task_name=line["task_name"],
                            weight=line["weight"],
                            planned_start=line["planned_start"],
                            planned_end=line["planned_end"],
                            note=line["note"],
                        )

                log_action(
                    actor=request.user,
                    action=WBS_CHANGE_REQUEST_SUBMIT
                    if obj.status == WBSChangeRequestStatus.SUBMITTED
                    else WBS_CHANGE_REQUEST_SAVE_DRAFT,
                    object_type="WBSChangeRequest",
                    object_id=obj.id,
                    project=project,
                    request=request,
                    after={
                        "status": obj.status,
                        "base_version": obj.base_version,
                        "lines_count": len(lines),
                    },
                )
                if obj.status == WBSChangeRequestStatus.SUBMITTED:
                    messages.success(request, "WBS 변경 요청이 제출되었습니다.")
                else:
                    messages.success(request, "WBS 변경 요청이 임시저장되었습니다.")
                return redirect(request.path)
        else:
            messages.error(request, "입력 오류가 있습니다. 아래 항목을 확인해 주세요.")
    else:
        form = WBSChangeRequestForm(instance=request_instance)
        if request_instance:
            line_initial = [
                {
                    "task_name": line.task_name,
                    "weight": line.weight,
                    "planned_start": line.planned_start,
                    "planned_end": line.planned_end,
                    "note": line.note,
                }
                for line in request_instance.lines.order_by("order", "id")
            ]
        else:
            line_initial = _build_line_initial_from_baseline(baseline_items)
        formset = formset_factory_cls(initial=line_initial, prefix="lines")

    can_edit = bool(
        not request_instance
        or request_instance.status == WBSChangeRequestStatus.DRAFT
    )
    if not can_edit:
        for field in form.fields.values():
            field.disabled = True
        for line_form in formset:
            for field in line_form.fields.values():
                field.disabled = True

    context = {
        "project": project,
        "baseline_items": baseline_items,
        "base_version": base_version,
        "form": form,
        "formset": formset,
        "draft_request": request_instance,
        "is_submitted": bool(
            request_instance
            and request_instance.status == WBSChangeRequestStatus.SUBMITTED
        ),
        "back_url": back_url,
        "role": role,
        "can_edit": can_edit,
    }
    return render(request, template_name, context)
