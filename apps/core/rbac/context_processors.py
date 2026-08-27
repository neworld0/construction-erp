from .permissions import get_current_legal_entity, get_user_legal_entities


def legal_entity_context(request):
    if not getattr(request.user, "is_authenticated", False):
        return {"current_legal_entity": None, "accessible_legal_entities": []}
    entities = list(get_user_legal_entities(request.user))
    entity_codes = {entity.code for entity in entities}
    return {
        "current_legal_entity": get_current_legal_entity(request),
        "accessible_legal_entities": entities,
        "current_entity_scope": request.session.get("current_entity_scope", "") if hasattr(request, "session") else "",
        "has_group_entity_scope": {"ASAN", "MISAN"}.issubset(entity_codes),
        # The selector remains disabled until existing transactional records have
        # been given an entity key and server-side query filtering is enabled.
        "legal_entity_scope_enforced": False,
    }
