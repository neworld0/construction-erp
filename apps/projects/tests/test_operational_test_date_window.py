from datetime import timedelta

import pytest
from django.contrib.auth import get_user_model
from django.utils import timezone

from apps.core.rbac.models import Role, UserProfile
from apps.projects.models import Project, ProjectOperationalTestDateWindow
from apps.projects.test_date_window import (
    allows_future_operational_test_date,
    allows_operational_test_date,
)


@pytest.mark.django_db
def test_operational_test_window_allows_only_configured_project_future_dates():
    hq = get_user_model().objects.create_user(username="window-hq", password="pass")
    UserProfile.objects.create(user=hq, role=Role.HQ)
    project = Project.objects.create(code="DATE-WINDOW-1", name="테스트 허용 현장", project_type="civil")
    other = Project.objects.create(code="DATE-WINDOW-2", name="일반 현장", project_type="civil")
    today = timezone.localdate()
    ProjectOperationalTestDateWindow.objects.create(
        project=project, start_date=today, end_date=today + timedelta(days=5),
        expires_on=today, reason="운영 검증", configured_by=hq,
    )

    assert allows_future_operational_test_date(project, today + timedelta(days=3))
    assert not allows_future_operational_test_date(other, today + timedelta(days=3))
    assert not allows_future_operational_test_date(project, today + timedelta(days=6))


@pytest.mark.django_db
def test_operational_test_window_authorizes_past_and_future_dates_inside_uat_scope():
    hq = get_user_model().objects.create_user(username="window-scope-hq", password="pass")
    UserProfile.objects.create(user=hq, role=Role.HQ)
    project = Project.objects.create(code="DATE-WINDOW-3", name="전체 기간 테스트 현장", project_type="civil")
    today = timezone.localdate()
    ProjectOperationalTestDateWindow.objects.create(
        project=project,
        start_date=today - timedelta(days=7),
        end_date=today + timedelta(days=7),
        expires_on=today,
        reason="프로젝트 기간 전체 운영 검증",
        configured_by=hq,
    )

    assert allows_operational_test_date(project, today - timedelta(days=7))
    assert allows_operational_test_date(project, today + timedelta(days=7))
    assert not allows_operational_test_date(project, today - timedelta(days=8))
    assert not allows_operational_test_date(project, today + timedelta(days=8))
