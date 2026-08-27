from decimal import Decimal

import pytest
from django.contrib.auth import get_user_model
from django.contrib.messages.storage.fallback import FallbackStorage
from django.contrib.sessions.middleware import SessionMiddleware
from django.test import RequestFactory

from apps.core.rbac.models import UserProfile
from apps.projects.hq_views import (
    _build_wbs_initial_from_import_rows,
    hq_project_detail,
    resolve_wbs_sort_order,
)
from apps.projects.models import Project, ProjectStatus, WBSItem


def _hq_user():
    user = get_user_model().objects.create_user(username="wbs-sort-hq", password="pass")
    UserProfile.objects.create(user=user, role="hq")
    return user


def _post_request(user, project, data):
    request = RequestFactory().post(f"/app/hq/projects/{project.id}/", data)
    SessionMiddleware(lambda req: None).process_request(request)
    request.session.save()
    request.user = user
    request._messages = FallbackStorage(request)
    return request


@pytest.mark.django_db
def test_hq_wbs_baseline_save_auto_assigns_sort_order_when_missing():
    user = _hq_user()
    project = Project.objects.create(
        code="LOCAL-OPS-20260814-001",
        name="WBS sort order test",
        project_type="civil",
        status=ProjectStatus.DRAFT,
        start_date="2026-08-14",
        end_date="2026-09-13",
    )
    data = {
        "action": "save_wbs",
        "wbs-TOTAL_FORMS": "3",
        "wbs-INITIAL_FORMS": "0",
        "wbs-MIN_NUM_FORMS": "0",
        "wbs-MAX_NUM_FORMS": "1000",
        "wbs-0-name": "WBS-01 Preparation",
        "wbs-0-parent": "",
        "wbs-0-weight": "40.00",
        "wbs-0-plan_start_date": "2026-08-14",
        "wbs-0-plan_end_date": "2026-09-13",
        "wbs-1-name": "WBS-02 Paving",
        "wbs-1-parent": "",
        "wbs-1-weight": "40.00",
        "wbs-1-plan_start_date": "2026-08-14",
        "wbs-1-plan_end_date": "2026-09-13",
        "wbs-2-name": "WBS-99 Common cost",
        "wbs-2-parent": "",
        "wbs-2-weight": "20.00",
        "wbs-2-plan_start_date": "2026-08-14",
        "wbs-2-plan_end_date": "2026-09-13",
    }

    response = hq_project_detail(_post_request(user, project, data), project.id)

    assert response.status_code in (301, 302)
    assert dict(WBSItem.objects.filter(project=project).values_list("name", "sort_order")) == {
        "WBS-01 Preparation": 10,
        "WBS-02 Paving": 20,
        "WBS-99 Common cost": 990,
    }


def test_wbs_sort_order_preserves_explicit_value_and_uses_row_fallback():
    assert resolve_wbs_sort_order("WBS-02 Paving", 1, 123) == 123
    assert resolve_wbs_sort_order("TEMP-A", 1) == 10
    assert resolve_wbs_sort_order("TEMP-B", 2) == 20


def test_wbs_import_initial_auto_assigns_sort_order_from_wbs_code():
    initial, warnings = _build_wbs_initial_from_import_rows(
        [
            {"code": "WBS-01", "name": "Preparation", "weight": Decimal("50")},
            {"code": "WBS-99", "name": "Common cost", "weight": Decimal("50")},
        ]
    )

    assert warnings == []
    assert [row["sort_order"] for row in initial] == [10, 990]
