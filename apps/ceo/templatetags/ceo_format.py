import re

from django import template

register = template.Library()

_AMOUNT_TOKEN_RE = re.compile(r"\b(\d{4,})(\.\d+)?\b")


@register.filter
def amount_commas_in_text(value):
    text = "" if value is None else str(value)
    if not text:
        return text

    def _replace(match):
        integer_part = match.group(1)
        decimal_part = match.group(2) or ""
        next_char = text[match.end() : match.end() + 1]
        # Keep date fragments like 2026-02-12 or 2026/02/12 untouched.
        if len(integer_part) == 4 and next_char in {"-", "/"}:
            return match.group(0)
        try:
            formatted_integer = f"{int(integer_part):,}"
        except (TypeError, ValueError):
            return match.group(0)
        return f"{formatted_integer}{decimal_part}"

    return _AMOUNT_TOKEN_RE.sub(_replace, text)
