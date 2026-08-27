from datetime import date
from decimal import Decimal

import pytest
from django.contrib.auth import get_user_model
from django.test import Client

from apps.core.rbac.models import LegalEntity, LegalEntityAccessScope, Role, UserLegalEntityMembership, UserProfile
from apps.cost.models import CostActual, CostActualLine, CostActualStatus, CostItem, CostItemCategory, RevenueRecognition, RevenueRecognitionClose
from apps.projects.models import Project
from apps.schedule.models import DailyProgress, SchedulePlan, ScheduleTask


@pytest.fixture(autouse=True)
def disable_two_factor(settings):
    settings.MIDDLEWARE = [m for m in settings.MIDDLEWARE if "two_factor_enforce" not in m]


def user(role, username):
    account = get_user_model().objects.create_user(username=username, password="pass")
    UserProfile.objects.create(user=account, role=role)
    UserLegalEntityMembership.objects.create(
        user=account,
        legal_entity=LegalEntity.objects.get(code="ASAN"),
        access_scope=LegalEntityAccessScope.CEO_VIEW if role == Role.CEO else LegalEntityAccessScope.ENTITY_HQ,
    )
    return account


def configured_project(reporter):
    project = Project.objects.create(code="REV-PREVIEW", name="매출 인식 검증 현장", project_type="civil", status="active", contract_amount=Decimal("132000000"))
    plan = SchedulePlan.objects.create(project=project, version_no=1, name="기준선")
    task = ScheduleTask.objects.create(plan=plan, name="포장", weight_percent=Decimal("100"))
    DailyProgress.objects.create(project=project, plan=plan, task=task, report_date=date(2026, 8, 18), progress_percent=Decimal("18.36"), status="approved", reporter=reporter)
    item = CostItem.objects.create(code="REV-PREVIEW-COST", name="실행원가", category=CostItemCategory.OTHER)
    actual = CostActual.objects.create(project=project, report_date=date(2026, 8, 18), status=CostActualStatus.APPROVED)
    CostActualLine.objects.create(cost_actual=actual, cost_item=item, quantity=Decimal("1"), unit_price=Decimal("6801000"))
    return project


@pytest.mark.django_db
def test_ceo_dashboard_shows_provisional_revenue_without_mutation():
    ceo = user(Role.CEO, "revenue-preview-ceo")
    project = configured_project(ceo)
    client = Client()
    client.force_login(ceo)

    response = client.get("/app/ceo/?as_of_date=2026-08-18")

    content = response.content.decode("utf-8")
    assert response.status_code == 200
    assert "실제 누적 매출(VAT 별도)" in content
    assert "잠정 진행률 매출(VAT 별도)" in content
    assert "22,032,000" in content
    assert "잠정 손익" in content
    assert "15,849,273" in content
    assert RevenueRecognition.objects.filter(project=project).count() == 0
    assert RevenueRecognitionClose.objects.filter(project=project).count() == 0


@pytest.mark.django_db
def test_metric_detail_lists_contributing_entries():
    ceo = user(Role.CEO, "metric-detail-ceo")
    project = configured_project(ceo)
    client = Client()
    client.force_login(ceo)

    list_response = client.get("/app/ceo/dashboard/metrics/cost/?as_of_date=2026-08-18")
    assert list_response.status_code == 200
    content = list_response.content.decode("utf-8")
    assert "원가 실적" in content
    assert "6,182,727원" in content
