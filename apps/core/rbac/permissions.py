from django.core.exceptions import PermissionDenied

from .models import ProjectAssignment, Role, UserProfile


def _get_role(user) -> str:
    if user is None or not getattr(user, "is_authenticated", False):
        return Role.FIELD
    profile = getattr(user, "profile", None)
    if isinstance(profile, UserProfile):
        return profile.role
    return Role.FIELD


def get_user_role(user) -> str:
    return _get_role(user)


def require_role(user, allowed_roles: list[str]) -> None:
    role = _get_role(user)
    if role not in allowed_roles:
        raise PermissionDenied("User role not permitted.")


def can_view_project(user, project_id) -> bool:
    role = _get_role(user)
    if role in (Role.CEO, Role.HQ):
        return True
    if role == Role.FIELD:
        return ProjectAssignment.objects.filter(
            user=user, project_id=project_id, is_active=True
        ).exists()
    return False


def require_project_access(user, project_id) -> None:
    if not can_view_project(user, project_id):
        raise PermissionDenied("Project access denied.")
