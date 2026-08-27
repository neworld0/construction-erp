import json

from django.contrib import messages
from django.contrib.auth.decorators import login_required
from django.core.exceptions import ValidationError
from django.shortcuts import get_object_or_404, redirect, render

from apps.core.rbac.models import Role
from apps.core.rbac.permissions import get_user_role, require_role
from .models import PlanChangeRequest, ProgressCorrectionRequest, ProgressCorrectionStatus
from .progress_corrections import hq_review_progress_correction


@login_required
def hq_plan_change_request_detail(request, request_id: int):
    require_role(request.user, [Role.HQ, Role.CEO])
    plan_change = get_object_or_404(
        PlanChangeRequest.objects.select_related(
            "project",
            "base_plan",
            "contract_change",
            "requested_by",
            "approved_by",
        ),
        id=request_id,
    )
    payload = plan_change.proposed_payload or {}
    context = {
        "plan_change": plan_change,
        "payload_json": json.dumps(payload, ensure_ascii=False, indent=2),
        "role": getattr(request.user, "role", None),
    }
    return render(request, "app/hq/plan_change_request_detail.html", context)


@login_required
def hq_progress_correction_list(request):
    require_role(request.user, [Role.HQ, Role.CEO])
    status = (request.GET.get("status") or "HQ_REVIEW").upper()
    qs = ProgressCorrectionRequest.objects.select_related("project", "original_progress__task", "requested_by", "hq_reviewed_by").order_by("-created_at")
    if status in {choice for choice, _label in ProgressCorrectionStatus.choices}:
        qs = qs.filter(status=status)
    return render(request, "app/hq/progress_correction_list.html", {"requests": qs, "status": status})


@login_required
def hq_progress_correction_review(request, correction_id: int):
    require_role(request.user, [Role.HQ])
    if request.method != "POST":
        return redirect(f"/app/hq/progress/corrections/{correction_id}/")
    action, comment = request.POST.get("action"), request.POST.get("comment", "")
    if action not in {"approve", "reject"}:
        messages.error(request, "검토 결과를 선택해 주세요.")
    elif action == "reject" and not comment.strip():
        messages.error(request, "HQ 반려 사유를 입력해 주세요.")
    else:
        try:
            hq_review_progress_correction(correction_id=correction_id, actor=request.user, approve=action == "approve", comment=comment, request=request)
        except ValidationError as exc:
            messages.error(request, str(exc))
        else:
            messages.success(request, "CEO 승인 대기 상태로 전달했습니다." if action == "approve" else "요청을 반려했습니다.")
    return redirect(f"/app/hq/progress/corrections/{correction_id}/")


@login_required
def progress_correction_detail(request, correction_id: int):
    require_role(request.user, [Role.HQ, Role.CEO])
    correction = get_object_or_404(ProgressCorrectionRequest.objects.select_related("project", "original_progress__task", "requested_by", "hq_reviewed_by", "approved_by"), pk=correction_id)
    return render(request, "app/hq/progress_correction_detail.html", {"correction": correction, "is_hq": get_user_role(request.user) == Role.HQ})
