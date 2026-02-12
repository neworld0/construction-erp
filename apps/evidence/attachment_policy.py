from __future__ import annotations

from dataclasses import dataclass


EDITABLE_STATUSES = {"draft", "rejected"}
LOCKED_STATUSES = {"submitted", "approved"}


@dataclass(frozen=True)
class AttachmentEditability:
    can_edit: bool
    reason: str


def normalize_status(value: str | None) -> str:
    return (value or "").strip().lower()


def can_edit_attachments(*, status: str | None, is_closed_locked: bool = False) -> bool:
    return evaluate_attachment_editability(
        status=status,
        is_closed_locked=is_closed_locked,
    ).can_edit


def evaluate_attachment_editability(
    *,
    status: str | None,
    is_closed_locked: bool = False,
) -> AttachmentEditability:
    """
    ATT-1 standard attachment editability policy.

    Editable: DRAFT / REJECTED
    Read-only: SUBMITTED / APPROVED
    Closing lock overrides every status.
    """
    if is_closed_locked:
        return AttachmentEditability(
            can_edit=False,
            reason="closing_locked",
        )

    normalized = normalize_status(status)
    if normalized in EDITABLE_STATUSES:
        return AttachmentEditability(can_edit=True, reason="editable_status")

    if normalized in LOCKED_STATUSES:
        return AttachmentEditability(can_edit=False, reason="submitted_or_approved")

    return AttachmentEditability(can_edit=False, reason="unknown_status")

