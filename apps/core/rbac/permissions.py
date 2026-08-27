import logging
import os

from django.core.exceptions import PermissionDenied

from .models import LegalEntity, ProjectAssignment, Role, UserLegalEntityMembership, UserProfile

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
    # A role alone must not bypass the legal-entity ownership boundary when a
    # user types a project URL directly.
    from apps.projects.models import Project

    project = Project.objects.filter(id=project_id).only("legal_entity_id").first()
    if project is None or not can_access_legal_entity(user, project.legal_entity_id):
        return False

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


def get_user_legal_entities(user):
    """Return only explicitly active entity memberships; role never implies membership."""
    if user is None or not getattr(user, "is_authenticated", False):
        return LegalEntity.objects.none()
    return LegalEntity.objects.filter(
        memberships__user=user,
        memberships__is_active=True,
        is_active=True,
    ).distinct().order_by("code")


def can_access_legal_entity(user, legal_entity) -> bool:
    entity_id = getattr(legal_entity, "id", legal_entity)
    return get_user_legal_entities(user).filter(id=entity_id).exists()


def require_legal_entity_access(user, legal_entity, request=None) -> None:
    if can_access_legal_entity(user, legal_entity):
        return
    logger.warning(
        "Legal entity RBAC deny: user=%s entity=%s path=%s",
        getattr(user, "username", None),
        getattr(legal_entity, "id", legal_entity),
        getattr(request, "path", None),
    )
    raise PermissionDenied("Legal entity access denied.")


def get_current_legal_entity(request):
    """Resolve a membership-scoped context without granting transaction access.

    The current entity is a convenience for defaults and navigation. Every
    transaction remains protected by its own legal-entity access check.
    """
    entities = get_user_legal_entities(getattr(request, "user", None))
    selected_id = request.session.get("current_legal_entity_id") if hasattr(request, "session") else None
    if selected_id:
        selected = entities.filter(id=selected_id).first()
        if selected:
            return selected
    return entities.first()
