from datetime import date
from decimal import Decimal

import pytest
from django.contrib.auth import get_user_model
from django.core.exceptions import ValidationError
from django.test import Client

from apps.core.rbac.models import (
    LegalEntity,
    LegalEntityAccessScope,
    ProjectAssignment,
    Role,
    UserLegalEntityMembership,
    UserProfile,
)
from apps.cost.models import CostActual
from apps.field.models import SiteDailyLog, SiteDailyLogStatus, SiteDailyLogWorkLine
from apps.field.site_daily_log_services import decide_site_daily_log, submit_site_daily_log
from apps.inventory.models import UoM
from apps.projects.models import (
    Project,
    ProjectWorkProgressMapping,
    WBSItem,
    WorkProgressCalculationMode,
)
from apps.schedule.models import DailyProgress, SchedulePlan, ScheduleTask


def _user(username, role, entity):
    user = get_user_model().objects.create_user(username=username)
    UserProfile.objects.create(user=user, role=role)
    UserLegalEntityMembership.objects.create(
        user=user,
        legal_entity=entity,
        access_scope=(
            LegalEntityAccessScope.FIELD
            if role == Role.FIELD
            else LegalEntityAccessScope.ENTITY_HQ
        ),
    )
    return user


def _context():
    entity = LegalEntity.objects.get(code="ASAN")
    field_user = _user("daily-log-field", Role.FIELD, entity)
    hq_user = _user("daily-log-hq", Role.HQ, entity)
    project = Project.objects.create(
        code="DSL-TEST-01", name="공사일보 테스트", legal_entity=entity
    )
    ProjectAssignment.objects.create(user=field_user, project=project, is_active=True)
    wbs = WBSItem.objects.create(project=project, name="포장", weight=Decimal("100"))
    plan = SchedulePlan.objects.create(project=project)
    task = ScheduleTask.objects.create(plan=plan, name="포장", weight_percent=Decimal("100"))
    uom = UoM.objects.create(code="DSL-M2", name="제곱미터")
    mapping = ProjectWorkProgressMapping.objects.create(
        project=project,
        wbs_item=wbs,
        schedule_task=task,
        calculation_mode=WorkProgressCalculationMode.QUANTITY,
        uom=uom,
        planned_qty=Decimal("100"),
    )
    return field_user, hq_user, project, uom, mapping


@pytest.mark.django_db
def test_approved_daily_log_snapshots_quantity_without_creating_progress_or_cost():
    field_user, hq_user, project, uom, mapping = _context()
    log = SiteDailyLog.objects.create(
        project=project,
        report_date=date(2026, 8, 14),
        reporter=field_user,
        today_work="아스콘 포장",
    )
    SiteDailyLogWorkLine.objects.create(
        site_daily_log=log,
        progress_mapping=mapping,
        uom=uom,
        today_qty=Decimal("25"),
    )

    submit_site_daily_log(log_id=log.id, actor=field_user)
    decide_site_daily_log(log_id=log.id, actor=hq_user, approve=True)

    log.refresh_from_db()
    line = log.work_lines.get()
    assert log.status == SiteDailyLogStatus.APPROVED
    assert line.prior_approved_qty == Decimal("0")
    assert line.cumulative_qty == Decimal("25")
    assert log.approval_snapshot["work_lines"][0]["today_qty"] == "25.000"
    assert DailyProgress.objects.filter(project=project).count() == 0
    assert CostActual.objects.filter(project=project).count() == 0


@pytest.mark.django_db
def test_next_approved_daily_log_uses_prior_approved_quantity_only():
    field_user, hq_user, project, uom, mapping = _context()
    first = SiteDailyLog.objects.create(
        project=project, report_date=date(2026, 8, 14), reporter=field_user, today_work="포장"
    )
    SiteDailyLogWorkLine.objects.create(
        site_daily_log=first, progress_mapping=mapping, uom=uom, today_qty=Decimal("25")
    )
    submit_site_daily_log(log_id=first.id, actor=field_user)
    decide_site_daily_log(log_id=first.id, actor=hq_user, approve=True)

    second = SiteDailyLog.objects.create(
        project=project, report_date=date(2026, 8, 15), reporter=field_user, today_work="포장"
    )
    SiteDailyLogWorkLine.objects.create(
        site_daily_log=second, progress_mapping=mapping, uom=uom, today_qty=Decimal("15")
    )
    submit_site_daily_log(log_id=second.id, actor=field_user)
    decide_site_daily_log(log_id=second.id, actor=hq_user, approve=True)

    line = second.work_lines.get()
    assert line.prior_approved_qty == Decimal("25")
    assert line.cumulative_qty == Decimal("40")


@pytest.mark.django_db
def test_same_task_cannot_have_two_active_calculation_modes():
    field_user, _hq_user, project, uom, mapping = _context()
    with pytest.raises(ValidationError):
        conflicting = ProjectWorkProgressMapping(
            project=project,
            wbs_item=mapping.wbs_item,
            schedule_task=mapping.schedule_task,
            calculation_mode=WorkProgressCalculationMode.MANUAL,
            uom=uom,
            planned_qty=Decimal("100"),
        )
        conflicting.full_clean()


@pytest.mark.django_db
def test_field_can_create_and_submit_from_the_web_flow():
    field_user, _hq_user, project, _uom, _mapping = _context()
    field_client = Client()
    field_client.force_login(field_user)
    session = field_client.session
    session["current_legal_entity_id"] = project.legal_entity_id
    session.save()

    created = field_client.post(
        "/app/field/site-daily-logs/new/save/",
        {
            "project": project.id,
            "report_date": "2026-08-14",
            "today_work": "포장 작업",
            "tomorrow_work": "품질 확인",
            "special_notes": "",
        },
    )
    assert created.status_code == 302
    log = SiteDailyLog.objects.get(project=project)
    submitted = field_client.post(f"/app/field/site-daily-logs/{log.id}/submit/")
    assert submitted.status_code == 302
    log.refresh_from_db()
    assert log.status == SiteDailyLogStatus.SUBMITTED
