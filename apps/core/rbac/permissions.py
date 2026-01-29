import logging
import os

from django.core.exceptions import PermissionDenied

from .models import ProjectAssignment, Role, UserProfile

logger = logging.getLogger(__name__)


def _get_role(user) -> str:
    if user is None or not getattr(user, "is_authenticated", False):
        return Role.FIELD
    profile = getattr(user, "profile", None)
    if isinstance(profile, UserProfile):
        raw_role = str(profile.role).strip()
        normalized = raw_role.lower()
        if normalized in (Role.CEO, Role.HQ, Role.FIELD):
            return normalized
        legacy_map = {
            "CEO": Role.CEO,
            "HQ": Role.HQ,
            "FIELD": Role.FIELD,
            "ceo": Role.CEO,
            "hq": Role.HQ,
            "field": Role.FIELD,
        }
        if raw_role in legacy_map:
            return legacy_map[raw_role]
    if getattr(user, "is_authenticated", False):
        seed_ceo = os.getenv("SEED_CEO_USERNAME")
        seed_hq = os.getenv("SEED_HQ_USERNAME")
        role_guess = None
        if seed_ceo and user.username == seed_ceo:
            role_guess = Role.CEO
        elif seed_hq and user.username == seed_hq:
            role_guess = Role.HQ
        if role_guess:
            profile, _created = UserProfile.objects.get_or_create(
                user=user, defaults={"role": role_guess}
            )
            return str(profile.role).lower()
    if getattr(user, "is_superuser", False):
        return Role.CEO
    if getattr(user, "is_staff", False):
        return Role.HQ
    return Role.FIELD


def get_user_role(user) -> str:
    return _get_role(user)


def require_role(user, allowed_roles: list[str], request=None) -> None:
    role = _get_role(user)
    if role not in allowed_roles:
        logger.warning(
            "RBAC deny: user=%s role=%s path=%s allowed_roles=%s",
            getattr(user, "username", None),
            role,
            getattr(request, "path", None),
            allowed_roles,
        )
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
