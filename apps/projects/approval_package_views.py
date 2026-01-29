from __future__ import annotations

from django.contrib import messages
from django.contrib.auth.decorators import login_required
from django.shortcuts import get_object_or_404, redirect, render

from apps.core.rbac.models import Role
from apps.core.rbac.permissions import require_role
from apps.contracts.models import ContractChange
from apps.projects.forms import ApprovalPackageForm
from apps.projects.models import (
    ApprovalPackage,
    ApprovalPackageItem,
    ApprovalPackageItemType,
    ApprovalPackageStatus,
    Project,
    WBSChangeRequest,
    WBSChangeRequestStatus,
)
from apps.projects.services.approval_package import submit_package
from apps.projects.services.wbs_baseline import get_current_wbs_version


@login_required
def hq_approval_package_new(request, project_id):
    require_role(request.user, [Role.HQ])
    project = get_object_or_404(Project, id=project_id)
    form = ApprovalPackageForm(request.POST or None)

    change_orders = ContractChange.objects.filter(project=project).order_by("-created_at")
    wbs_requests = WBSChangeRequest.objects.filter(project=project).order_by("-created_at")

    if request.method == "POST":
        change_order_id = request.POST.get("change_order_id")
        wbs_request_id = request.POST.get("wbs_request_id")
        if not change_order_id or not wbs_request_id:
            messages.error(request, "변경계약과 WBS 변경요청을 모두 선택하세요.")
        elif form.is_valid():
            change_order = get_object_or_404(
                ContractChange, id=change_order_id, project=project
            )
            wbs_request = get_object_or_404(
                WBSChangeRequest, id=wbs_request_id, project=project
            )
            current_version = get_current_wbs_version(project)
            if wbs_request.base_version != current_version:
                messages.error(request, "현재 기준선과 다른 WBS 요청은 패키지로 제출할 수 없습니다.")
            else:
                package = form.save(commit=False)
                package.project = project
                package.created_by = request.user
                package.status = ApprovalPackageStatus.DRAFT
                package.save()
                ApprovalPackageItem.objects.create(
                    package=package,
                    item_type=ApprovalPackageItemType.CHANGE_ORDER,
                    object_id=change_order.id,
                    status_snapshot=change_order.status,
                )
                ApprovalPackageItem.objects.create(
                    package=package,
                    item_type=ApprovalPackageItemType.WBS_CHANGE,
                    object_id=wbs_request.id,
                    status_snapshot=wbs_request.status,
                )
                messages.success(request, "패키지가 생성되었습니다. 제출 후 CEO 승인으로 진행됩니다.")
                return redirect(f"/app/hq/projects/{project.id}/approval-packages/{package.id}/")

    context = {
        "project": project,
        "form": form,
        "change_orders": change_orders,
        "wbs_requests": wbs_requests,
    }
    return render(request, "app/hq/approval_package_new.html", context)


@login_required
def hq_approval_package_detail(request, project_id, package_id):
    require_role(request.user, [Role.HQ])
    project = get_object_or_404(Project, id=project_id)
    package = get_object_or_404(ApprovalPackage, id=package_id, project=project)
    items = list(package.items.all())
    item_rows = []
    for item in items:
        if item.item_type == ApprovalPackageItemType.CHANGE_ORDER:
            obj = ContractChange.objects.filter(id=item.object_id).first()
            summary = "-"
            status = item.status_snapshot
            if obj:
                summary = f"#{obj.change_no} / delta {obj.contract_amount_delta}"
                status = obj.status
        elif item.item_type == ApprovalPackageItemType.WBS_CHANGE:
            obj = WBSChangeRequest.objects.filter(id=item.object_id).first()
            summary = "-"
            status = item.status_snapshot
            if obj:
                lines_count = obj.lines.count()
                summary = f"v{obj.base_version} / lines {lines_count}"
                status = obj.status
        else:
            summary = "-"
            status = item.status_snapshot
        item_rows.append(
            {
                "item_type": item.item_type,
                "status": status,
                "summary": summary,
            }
        )

    return render(
        request,
        "app/hq/approval_package_detail.html",
        {
            "project": project,
            "package": package,
            "items": item_rows,
        },
    )


@login_required
def hq_approval_package_list(request, project_id):
    require_role(request.user, [Role.HQ])
    project = get_object_or_404(Project, id=project_id)
    status_filter = (request.GET.get("status") or "submitted").lower()
    qs = (
        ApprovalPackage.objects.filter(project=project)
        .select_related("created_by")
        .order_by("-created_at")
    )
    if status_filter == "submitted":
        qs = qs.filter(status=ApprovalPackageStatus.SUBMITTED)
    elif status_filter == "approved":
        qs = qs.filter(status=ApprovalPackageStatus.APPROVED)
    elif status_filter == "rejected":
        qs = qs.filter(status=ApprovalPackageStatus.REJECTED)
    context = {
        "project": project,
        "packages": qs,
        "status_filter": status_filter,
    }
    return render(request, "app/hq/approval_package_list.html", context)


@login_required
def hq_approval_package_submit(request, package_id):
    require_role(request.user, [Role.HQ])
    package = get_object_or_404(ApprovalPackage, id=package_id)
    if request.method != "POST":
        return redirect(f"/app/hq/projects/{package.project_id}/approval-packages/{package.id}/")
    try:
        submit_package(package.id, actor=request.user, request=request)
        messages.success(request, "패키지가 제출되었습니다.")
    except Exception as exc:
        messages.error(request, f"패키지 제출에 실패했습니다: {exc}")
    return redirect(f"/app/hq/projects/{package.project_id}/approval-packages/{package.id}/")
