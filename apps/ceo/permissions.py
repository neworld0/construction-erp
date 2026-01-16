from rest_framework.permissions import BasePermission

from apps.core.rbac.models import Role
from apps.core.rbac.permissions import require_role


class CEOAccessPermission(BasePermission):
    message = "CEO/HQ role required."

    def has_permission(self, request, view):
        try:
            require_role(request.user, [Role.CEO, Role.HQ])
        except Exception:
            return False
        return True
