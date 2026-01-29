import json

from django.contrib.auth.decorators import login_required
from django.shortcuts import get_object_or_404, render

from apps.core.rbac.models import Role
from apps.core.rbac.permissions import require_role
from .models import PlanChangeRequest


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
