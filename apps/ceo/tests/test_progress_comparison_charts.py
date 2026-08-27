from datetime import date
from decimal import Decimal

import pytest
from django.contrib.auth import get_user_model
from django.test import Client

from apps.ceo.services.progress_comparison import build_portfolio_progress_comparison
from apps.core.rbac.models import Role, UserProfile
from apps.projects.models import Project
from apps.schedule.models import DailyProgress, SchedulePlan, ScheduleTask
from apps.kpi.timeline import build_timeline


@pytest.fixture(autouse=True)
def disable_two_factor(settings):
    settings.MIDDLEWARE = [m for m in settings.MIDDLEWARE if "two_factor_enforce" not in m]


@pytest.mark.django_db
def test_portfolio_comparison_and_project_timeline_render_for_multiple_projects():
    ceo = get_user_model().objects.create_user(username="chart-ceo", password="pass")
    UserProfile.objects.create(user=ceo, role=Role.CEO)
    projects = []
    for number, actual in ((1, "30"), (2, "60")):
        project = Project.objects.create(code=f"CHART-{number}", name=f"차트 현장 {number}", project_type="civil", is_active=True)
        plan = SchedulePlan.objects.create(project=project, version_no=1, name="기준선")
        task = ScheduleTask.objects.create(plan=plan, name="공정", weight_percent=Decimal("100"), start_date=date(2026, 8, 1), end_date=date(2026, 8, 31))
        DailyProgress.objects.create(project=project, plan=plan, task=task, report_date=date(2026, 8, 16), progress_percent=Decimal(actual), status="approved", reporter=ceo)
        projects.append(project)

    rows = build_portfolio_progress_comparison(projects, date(2026, 8, 16))
    assert len(rows) == 2
    assert rows[0]["basis_status"] == "비교 가능"
    assert rows[0]["planned_progress_percent"] > Decimal("0")
    assert rows[1]["actual_progress_percent"] == Decimal("60")

    cost_timeline = build_timeline(
        projects[0], granularity="month", end=date(2026, 8, 31), metrics="actual_cost"
    )
    assert cost_timeline["series"]
    assert "actual_cost" in cost_timeline["series"][-1]["metrics"]

    client = Client()
    client.force_login(ceo)
    response = client.get(f"/app/ceo/projects/{projects[0].id}/?as_of_date=2026-08-16")
    content = response.content.decode("utf-8")
    assert response.status_code == 200
    assert "projectProgressTimeline" in content
    assert "이전 화면" in content
