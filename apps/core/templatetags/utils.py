from django import template


register = template.Library()


_FIELD_STATUS_LABELS = {
    "DRAFT": "임시저장",
    "SUBMITTED": "제출",
    "PENDING": "제출",
    "APPROVED": "승인",
    "REJECTED": "반려",
    "CLOSED": "마감",
    "LOCKED": "마감",
    "FINAL": "확정",
    "VOIDED": "취소",
    "CANCELLED": "취소",
    "HQ_REVIEW": "HQ 검토",
    "CEO_REVIEW": "CEO 검토",
    "USED": "사용 완료",
}


@register.filter
def get_attribute(obj, name):
    if obj is None or not name:
        return ""
    return getattr(obj, name, "")


@register.filter
def get_item(mapping, key):
    if not mapping:
        return ""
    return mapping.get(str(key), "")


@register.filter
def work_code(value):
    if value is None:
        return ""
    try:
        return f"{int(value):02d}"
    except (TypeError, ValueError):
        return str(value)


@register.filter
def field_status_label(value):
    raw = str(value or "").strip()
    return _FIELD_STATUS_LABELS.get(raw.upper(), raw or "-")


@register.filter
def field_status_class(value):
    raw = str(value or "").strip().lower().replace("_", "-")
    return f"status-{raw}" if raw else "status-unknown"
