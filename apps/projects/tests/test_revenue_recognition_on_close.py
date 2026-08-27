from datetime import date
from decimal import Decimal

import pytest
from django.contrib.auth import get_user_model
from django.core.exceptions import ValidationError

from apps.closing.revenue_recognition import recognize_revenue_and_cost_for_close
from apps.closing.services import close_month
from apps.core.rbac.models import Role, UserProfile
from apps.cost.models import CostActual, CostActualLine, CostActualStatus, CostItem, CostItemCategory, RevenueRecognitionClose, RevenueRecognitionTrigger
from apps.projects.models import Project
from apps.schedule.models import DailyProgress, SchedulePlan, ScheduleTask


def user(role, username):
    account = get_user_model().objects.create_user(username=username, password="pass")
    UserProfile.objects.create(user=account, role=role)
    return account


@pytest.mark.django_db
def test_month_close_recognition_is_incremental_and_duplicate_is_blocked():
    hq = user(Role.HQ, "revenue-close-hq")
    ceo = user(Role.CEO, "revenue-close-ceo")
    project = Project.objects.create(code="REV-CLOSE", name="월마감 매출 현장", project_type="civil", status="active", contract_amount=Decimal("132000000"))
    plan = SchedulePlan.objects.create(project=project, version_no=1, name="기준선")
    task = ScheduleTask.objects.create(plan=plan, name="포장", weight_percent=Decimal("100"))
    DailyProgress.objects.create(project=project, plan=plan, task=task, report_date=date(2026, 8, 18), progress_percent=Decimal("18.36"), status="approved", reporter=ceo)
    item = CostItem.objects.create(code="REV-CLOSE-COST", name="실행원가", category=CostItemCategory.OTHER)
    actual = CostActual.objects.create(project=project, report_date=date(2026, 8, 18), status=CostActualStatus.APPROVED)
    CostActualLine.objects.create(cost_actual=actual, cost_item=item, quantity=Decimal("1"), unit_price=Decimal("6801000"))
    close_month(2026, 8, ceo)

    snapshot = recognize_revenue_and_cost_for_close(project=project, close_date=date(2026, 8, 31), trigger_type=RevenueRecognitionTrigger.MONTHLY_CLOSE, actor=hq)

    assert snapshot.recognized_revenue_amount == Decimal("24235200.00")
    assert snapshot.recognized_cost_amount == Decimal("6801000.00")
    assert RevenueRecognitionClose.objects.filter(project=project).count() == 1
    with pytest.raises(ValidationError, match="이미 매출 인식이 완료된 마감"):
        recognize_revenue_and_cost_for_close(project=project, close_date=date(2026, 8, 31), trigger_type=RevenueRecognitionTrigger.MONTHLY_CLOSE, actor=hq)
