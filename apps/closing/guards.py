from __future__ import annotations

from datetime import date

from django.core.exceptions import PermissionDenied, ValidationError

from .services import is_month_closed


def _month_block_message(target_date: date) -> str:
    return (
        f"{target_date.year}년 {target_date.month}월은 마감되었습니다. "
        "마감 후 입력/수정은 정정 절차로 진행해야 합니다."
    )


def assert_month_open(
    target_date: date, *, message_context: str | None = None, exc=PermissionDenied
) -> None:
    if is_month_closed(target_date):
        message = _month_block_message(target_date)
        if message_context:
            message = f"{message_context} {message}"
        raise exc(message)


def assert_object_month_open(
    obj, date_field_name: str, *, message_context: str | None = None, exc=PermissionDenied
) -> None:
    target_date = getattr(obj, date_field_name)
    if not isinstance(target_date, date):
        raise ValidationError("Date field is missing or invalid.")
    assert_month_open(target_date, message_context=message_context, exc=exc)


def _project_block_message(project) -> str:
    return (
        f"프로젝트가 마감되었습니다. (프로젝트: {getattr(project, 'name', project)}) "
        "마감 후 입력/수정은 정정 절차로 진행해야 합니다."
    )


def assert_project_open(project, *, message_context: str | None = None, exc=PermissionDenied) -> None:
    if project is None:
        return
    close = getattr(project, "close", None)
    if close is None:
        return
    status = getattr(close, "status", None)
    if status == "CLOSED":
        message = _project_block_message(project)
        if message_context:
            message = f"{message_context} {message}"
        raise exc(message)


def guard_write(
    *,
    project,
    target_date: date,
    message_context: str | None = None,
    exc=PermissionDenied,
) -> None:
    assert_project_open(project, message_context=message_context, exc=exc)
    assert_month_open(target_date, message_context=message_context, exc=exc)
