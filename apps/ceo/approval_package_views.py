from __future__ import annotations

from django.contrib import messages
from django.contrib.auth.decorators import login_required
from django.shortcuts import get_object_or_404, redirect, render

from apps.core.rbac.models import Role
from apps.core.rbac.permissions import require_role
from apps.contracts.models import ContractChange
from apps.projects.models import (
    ApprovalPackage,
    ApprovalPackageItemType,
    ApprovalPackageStatus,
    WBSChangeRequest,
)
from apps.projects.services.approval_package import approve_package, reject_package


@login_required
def ceo_approval_package_list(request):
    require_role(request.user, [Role.CEO])
    status_filter = (request.GET.get("status") or "submitted").lower()
    qs = ApprovalPackage.objects.select_related("project", "created_by").order_by(
        "-created_at"
    )
    if status_filter == "submitted":
        qs = qs.filter(status=ApprovalPackageStatus.SUBMITTED)
    elif status_filter == "approved":
        qs = qs.filter(status=ApprovalPackageStatus.APPROVED)
    elif status_filter == "rejected":
        qs = qs.filter(status=ApprovalPackageStatus.REJECTED)
    context = {
        "packages": qs,
        "status_filter": status_filter,
    }
    return render(request, "ceo/approval_package_list.html", context)


@login_required
def ceo_approval_package_detail(request, package_id):
    require_role(request.user, [Role.CEO])
    package = get_object_or_404(ApprovalPackage, id=package_id)
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
        "ceo/approval_package_detail.html",
        {
            "package": package,
            "items": item_rows,
        },
    )


@login_required
def ceo_approval_package_approve(request, package_id):
    require_role(request.user, [Role.CEO])
    if request.method != "POST":
        return redirect(f"/app/ceo/approval-packages/{package_id}/")
    try:
        approve_package(package_id, actor=request.user, request=request)
        messages.success(request, "패키지가 승인되었습니다.")
    except Exception as exc:
        messages.error(request, f"패키지 승인에 실패했습니다: {exc}")
    return redirect(f"/app/ceo/approval-packages/{package_id}/")


@login_required
def ceo_approval_package_reject(request, package_id):
    require_role(request.user, [Role.CEO])
    if request.method != "POST":
        return redirect(f"/app/ceo/approval-packages/{package_id}/")
    decision_note = (request.POST.get("decision_note") or "").strip()
    try:
        reject_package(
            package_id, actor=request.user, decision_note=decision_note, request=request
        )
        messages.success(request, "패키지가 반려되었습니다.")
    except Exception as exc:
        messages.error(request, f"패키지 반려에 실패했습니다: {exc}")
    return redirect(f"/app/ceo/approval-packages/{package_id}/")
