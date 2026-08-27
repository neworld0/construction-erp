from datetime import timedelta

import pytest
from django.contrib.auth import get_user_model
from django.test import Client
from django.utils import timezone

from apps.core.rbac.models import ProjectAssignment, Role, UserProfile
from apps.cost.models import CostActual, CostItem
from apps.projects.models import Project


@pytest.fixture(autouse=True)
def _disable_two_factor_enforce(settings):
    settings.MIDDLEWARE = [
        middleware
        for middleware in settings.MIDDLEWARE
        if middleware != "apps.core.middleware.two_factor_enforce.TwoFactorEnforceMiddleware"
    ]


@pytest.mark.django_db
def test_field_cost_accepts_selected_past_occurrence_date_and_renders_date_control():
    field_user = get_user_model().objects.create_user(username="field-cost-date", password="pass")
    UserProfile.objects.create(user=field_user, role=Role.FIELD)
    project = Project.objects.create(code="FIELD-COST-DATE", name="원가 일자 현장", project_type="civil")
    ProjectAssignment.objects.create(user=field_user, project=project, is_active=True)
    cbs = CostItem.objects.create(
        code="FIELD-COST-DATE-CBS", name="원가 일자 CBS", category="other", is_active=True
    )
    client = Client()
    client.force_login(field_user)

    page = client.get(f"/app/field/?tab=cost&project_id={project.id}")
    assert page.status_code == 200
    assert 'id="report_date"' in page.content.decode("utf-8")

    occurrence_date = timezone.localdate() - timedelta(days=2)
    saved = client.post(
        "/app/field/",
        {
            "tab": "cost",
            "project_id": project.id,
            "action": "draft",
            "report_date": occurrence_date.isoformat(),
            "cost_item_id": cbs.id,
            "quantity": "2",
            "unit_price": "12500",
            "memo": "선택 일자 원가",
        },
    )

    assert saved.status_code == 302
    cost = CostActual.objects.get(project=project)
    assert cost.report_date == occurrence_date
    assert cost.source_daily_report.report_date == occurrence_date


@pytest.mark.django_db
def test_field_cost_rejects_future_occurrence_date():
    field_user = get_user_model().objects.create_user(username="field-cost-future", password="pass")
    UserProfile.objects.create(user=field_user, role=Role.FIELD)
    project = Project.objects.create(code="FIELD-COST-FUTURE", name="미래 원가 차단 현장", project_type="civil")
    ProjectAssignment.objects.create(user=field_user, project=project, is_active=True)
    cbs = CostItem.objects.create(
        code="FIELD-COST-FUTURE-CBS", name="미래 원가 CBS", category="other", is_active=True
    )
    client = Client()
    client.force_login(field_user)

    response = client.post(
        "/app/field/",
        {
            "tab": "cost",
            "project_id": project.id,
            "action": "draft",
            "report_date": (timezone.localdate() + timedelta(days=1)).isoformat(),
            "cost_item_id": cbs.id,
            "quantity": "1",
            "unit_price": "1000",
        },
    )

    assert response.status_code == 200
    assert "미래 날짜의 원가는 입력할 수 없습니다." in response.content.decode("utf-8")
    assert not CostActual.objects.filter(project=project).exists()
