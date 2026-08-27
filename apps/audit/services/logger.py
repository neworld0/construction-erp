import re
import uuid

from apps.audit.models import AuditLog


REDACTED = "[REDACTED]"

SENSITIVE_KEY_FRAGMENTS = (
    "password",
    "passwd",
    "token",
    "access_token",
    "refresh_token",
    "secret",
    "secret_key",
    "api_key",
    "apikey",
    "authorization",
    "credential",
    "credentials",
    "session",
    "cookie",
    "rrn",
    "resident_no",
    "resident_number",
    "registration_no",
    "주민등록번호",
    "주민번호",
    "rrn_raw",
    "rrn_encrypted",
    "rrn_masked",
    "identity_hash",
    "account_number",
    "account_no",
    "bank_account",
    "account_number_encrypted",
    "account_number_masked",
    "계좌번호",
    "phone_raw",
    "raw_phone",
    "birth_date",
    "birth_date_encrypted",
    "birth_date_masked",
)

SENSITIVE_KEY_EXACT = (
    "pwd",
    "auth",
    "bearer",
    "계좌",
)

_RRN_PATTERN = re.compile(r"\b\d{6}-?\d{7}\b")
_ACCOUNT_PATTERN = re.compile(r"\b\d{2,6}[- ]\d{2,6}[- ]\d{3,8}\b")
_ENCRYPTED_PATTERN = re.compile(r"\b(?:enc1|gAAAAA|fernet):?", re.IGNORECASE)
_BEARER_PATTERN = re.compile(r"\bbearer\s+[-._~+/A-Za-z0-9]+=*", re.IGNORECASE)


def sanitize_audit_payload(value):
    if isinstance(value, dict):
        masked = {}
        for key, item in value.items():
            if _is_sensitive_key(key):
                masked[key] = REDACTED
            else:
                masked[key] = sanitize_audit_payload(item)
        return masked
    if isinstance(value, (list, tuple)):
        return [sanitize_audit_payload(item) for item in value]
    if isinstance(value, str) and _looks_sensitive_value(value):
        return REDACTED
    return value


def _is_sensitive_key(key):
    normalized = _normalize_key(key)
    exact_keys = {_normalize_key(fragment) for fragment in SENSITIVE_KEY_EXACT}
    if normalized in exact_keys:
        return True
    return any(_normalize_key(fragment) in normalized for fragment in SENSITIVE_KEY_FRAGMENTS)


def _normalize_key(key):
    return re.sub(r"[\s_\-]+", "", str(key or "").strip().lower())


def _looks_sensitive_value(value: str) -> bool:
    text = str(value or "")
    if not text:
        return False
    if _RRN_PATTERN.search(text):
        return True
    if _ACCOUNT_PATTERN.search(text):
        return True
    if _ENCRYPTED_PATTERN.search(text):
        return True
    if _BEARER_PATTERN.search(text):
        return True
    return False


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
    before_json = sanitize_audit_payload(before) if before is not None else None
    after_json = sanitize_audit_payload(after) if after is not None else None
    meta_json = sanitize_audit_payload(meta) if meta is not None else {}

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
