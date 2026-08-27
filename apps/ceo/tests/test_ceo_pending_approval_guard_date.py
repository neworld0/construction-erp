from datetime import date
from types import SimpleNamespace

from apps.ceo.app_views import _resolve_guard_context


def test_pending_daily_progress_uses_report_date_for_month_close_guard():
    project = SimpleNamespace(id=19)
    progress = SimpleNamespace(project=project, report_date=date(2026, 9, 2))
    approval = SimpleNamespace(object_type="DAILY_PROGRESS", object_id=91)

    resolved_project, target_date = _resolve_guard_context(
        {
            "object_type": "APPROVAL_REQUEST",
            "object_id": 301,
            "project": project,
            "_obj": approval,
            "_target_obj": progress,
        }
    )

    assert resolved_project is project
    assert target_date == date(2026, 9, 2)


def test_pending_report_and_cost_items_use_their_own_report_dates():
    project = SimpleNamespace(id=19)
    for object_type in ("DAILY_REPORT", "FIELD_REPORT", "COST_ACTUAL"):
        target = SimpleNamespace(project=project, report_date=date(2026, 9, 13))
        resolved_project, target_date = _resolve_guard_context(
            {"object_type": object_type, "project": project, "_obj": target}
        )
        assert resolved_project is project
        assert target_date == date(2026, 9, 13)
