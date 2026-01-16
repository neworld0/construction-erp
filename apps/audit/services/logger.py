import uuid

from apps.audit.models import AuditLog


SENSITIVE_KEYS = ("password", "token", "secret")


def _mask_sensitive(value):
    if isinstance(value, dict):
        masked = {}
        for key, item in value.items():
            if _is_sensitive_key(key):
                masked[key] = "***"
            else:
                masked[key] = _mask_sensitive(item)
        return masked
    if isinstance(value, list):
        return [_mask_sensitive(item) for item in value]
    return value


def _is_sensitive_key(key):
    key_lower = str(key).lower()
    return any(fragment in key_lower for fragment in SENSITIVE_KEYS)


def _extract_request_meta(request):
    if request is None:
        return None, None, None

    request_id = getattr(request, "request_id", None)
    if request_id is None:
        request_id = uuid.uuid4()
        setattr(request, "request_id", request_id)

    ip = request.META.get("HTTP_X_FORWARDED_FOR") or request.META.get("REMOTE_ADDR")
    if ip and "," in ip:
        ip = ip.split(",", 1)[0].strip()

    user_agent = request.META.get("HTTP_USER_AGENT", "")[:255]
    return request_id, ip, user_agent


def log_action(
    *,
    actor,
    action,
    object_type,
    object_id,
    project=None,
    request=None,
    before=None,
    after=None,
    meta=None,
):
    request_id, ip, user_agent = _extract_request_meta(request)
    before_json = _mask_sensitive(before) if before is not None else None
    after_json = _mask_sensitive(after) if after is not None else None
    meta_json = _mask_sensitive(meta) if meta is not None else {}

    return AuditLog.objects.create(
        actor=actor,
        action=action,
        object_type=object_type,
        object_id=object_id,
        project=project,
        request_id=request_id,
        ip=ip,
        user_agent=user_agent or "",
        before_json=before_json,
        after_json=after_json,
        meta_json=meta_json,
    )
