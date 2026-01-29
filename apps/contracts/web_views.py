from django.contrib.auth.decorators import login_required
from django.shortcuts import get_object_or_404, render

from apps.core.rbac.models import Role
from apps.core.rbac.permissions import require_role
from .models import ContractChange


@login_required
def hq_contract_change_detail(request, change_id: int):
    require_role(request.user, [Role.HQ, Role.CEO])
    change = get_object_or_404(
        ContractChange.objects.select_related("project", "submitted_by", "approved_by"),
        id=change_id,
    )
    context = {
        "change": change,
        "role": getattr(request.user, "role", None),
    }
    return render(request, "app/hq/contract_change_detail.html", context)
