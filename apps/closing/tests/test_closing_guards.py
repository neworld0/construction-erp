from datetime import date

import pytest
from django.contrib.auth import get_user_model
from django.core.exceptions import PermissionDenied, ValidationError

from apps.closing.guards import assert_month_open as guard_assert_month_open
from apps.closing.guards import guard_write
from apps.closing.models import ProjectClose, ProjectCloseStatus
from apps.closing.services import close_month
from apps.projects.models import Project


def _user(username="closing-hq"):
    return get_user_model().objects.create_user(username=username, password="pass")


@pytest.mark.django_db
def test_close_month_is_idempotency_safe():
    actor = _user()

    close_month(2026, 5, actor)

    with pytest.raises(ValidationError):
        close_month(2026, 5, actor)


@pytest.mark.django_db
def test_assert_month_open_blocks_closed_month():
    actor = _user("closing-month")
    close_month(2026, 5, actor)

    with pytest.raises(PermissionDenied):
        guard_assert_month_open(date(2026, 5, 10))


@pytest.mark.django_db
def test_guard_write_blocks_closed_project():
    project = Project.objects.create(code="PRJ-CLOSE-001", name="Closed Project")
    ProjectClose.objects.create(project=project, status=ProjectCloseStatus.CLOSED)

    with pytest.raises(PermissionDenied):
        guard_write(project=project, target_date=date(2026, 5, 10))
