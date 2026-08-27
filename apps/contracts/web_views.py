from django.contrib.auth.decorators import login_required
from django.shortcuts import get_object_or_404, render

from apps.core.rbac.models import Role
from apps.core.rbac.permissions import get_current_legal_entity, require_project_access, require_role
from .models import ContractChange


@login_required
def hq_contract_change_detail(request, change_id: int):
    require_role(request.user, [Role.HQ, Role.CEO])
    change = get_object_or_404(
        ContractChange.objects.select_related("project", "submitted_by", "approved_by"),
        id=change_id,
    )
    require_project_access(request.user, change.project_id)
    if change.project.legal_entity_id != getattr(get_current_legal_entity(request), "id", None):
        from django.core.exceptions import PermissionDenied
        raise PermissionDenied("선택한 운영 법인의 계약 변경만 조회할 수 있습니다.")
    context = {
        "change": change,
        "role": getattr(request.user, "role", None),
    }
    return render(request, "app/hq/contract_change_detail.html", context)
