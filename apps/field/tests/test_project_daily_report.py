from datetime import date, datetime
from decimal import Decimal

import pytest
from django.contrib.auth import get_user_model
from django.test import Client
from django.utils import timezone

from apps.core.rbac.models import LegalEntity, LegalEntityAccessScope, ProjectAssignment, Role, UserLegalEntityMembership, UserProfile
from apps.field.daily_report_service import build_organization_daily_report, build_project_daily_report
from apps.field.daily_report_exports import project_daily_report_pdf
from apps.projects.models import Project
from apps.schedule.models import DailyProgress, SchedulePlan, ScheduleTask


def _user(username, role, entity):
    user = get_user_model().objects.create_user(username=username)
    UserProfile.objects.create(user=user, role=role)
    UserLegalEntityMembership.objects.create(
        user=user, legal_entity=entity,
        access_scope=LegalEntityAccessScope.FIELD if role == Role.FIELD else LegalEntityAccessScope.ENTITY_HQ,
    )
    return user


@pytest.mark.django_db
def test_project_daily_report_reads_approved_progress_without_creating_a_daily_log():
    entity = LegalEntity.objects.get(code="ASAN")
    field_user = _user("auto-report-field", Role.FIELD, entity)
    project = Project.objects.create(code="AUTO-REPORT-01", name="자동 공사일보", legal_entity=entity)
    ProjectAssignment.objects.create(user=field_user, project=project, is_active=True)
    plan = SchedulePlan.objects.create(project=project)
    task = ScheduleTask.objects.create(plan=plan, name="포장", weight_percent=Decimal("100"))
    DailyProgress.objects.create(
        project=project, plan=plan, task=task, report_date=date(2026, 8, 26),
        progress_percent=Decimal("30"), status="approved", reporter=field_user,
    )

    before = DailyProgress.objects.count()
    report = build_project_daily_report(project=project, as_of_date=date(2026, 8, 26))

    assert report["summary"]["progress_count"] == 1
    assert report["progress_rows"][0]["task"] == "포장"
    assert report["report_status"]["state"] == "READY"
    assert DailyProgress.objects.count() == before


@pytest.mark.django_db
def test_field_report_url_is_project_assignment_scoped():
    entity = LegalEntity.objects.get(code="ASAN")
    field_user = _user("auto-report-url-field", Role.FIELD, entity)
    project = Project.objects.create(code="AUTO-REPORT-02", name="배정 공사일보", legal_entity=entity)
    ProjectAssignment.objects.create(user=field_user, project=project, is_active=True)
    client = Client()
    client.force_login(field_user)
    session = client.session
    session["current_legal_entity_id"] = entity.id
    session.save()

    response = client.get(f"/app/field/site-daily-logs/projects/{project.id}/?as_of_date=2026-08-26")

    assert response.status_code == 200
    assert "원천 입력 자동취합" in response.content.decode()


@pytest.mark.django_db
def test_organization_total_equals_project_report_total():
    entity = LegalEntity.objects.get(code="ASAN")
    project = Project.objects.create(code="AUTO-REPORT-03", name="법인 취합", legal_entity=entity)
    report = build_organization_daily_report(projects=[project], as_of_date=date(2026, 8, 26))
    assert report["totals"]["project_count"] == 1
    assert report["totals"]["cost_amount"] == report["project_reports"][0]["summary"]["cost_amount"]


@pytest.mark.django_db
def test_project_report_separates_yesterday_today_and_month_to_date():
    entity = LegalEntity.objects.get(code="ASAN")
    field_user = _user("auto-report-period-field", Role.FIELD, entity)
    project = Project.objects.create(code="AUTO-REPORT-04", name="기간 공사일보", legal_entity=entity)
    plan = SchedulePlan.objects.create(project=project)
    task = ScheduleTask.objects.create(plan=plan, name="식재", weight_percent=Decimal("100"))
    DailyProgress.objects.create(
        project=project, plan=plan, task=task, report_date=date(2026, 8, 25),
        progress_percent=Decimal("20"), status="approved", reporter=field_user,
    )
    DailyProgress.objects.create(
        project=project, plan=plan, task=task, report_date=date(2026, 8, 26),
        progress_percent=Decimal("30"), status="approved", reporter=field_user,
        note="금일 식재 작업",
    )

    report = build_project_daily_report(project=project, as_of_date=date(2026, 8, 26))

    assert report["periods"]["yesterday"]["progress_count"] == 1
    assert report["periods"]["today"]["progress_count"] == 1
    assert report["periods"]["month_to_date"]["progress_count"] == 2
    assert report["work_items"][0]["title"] == "식재"


@pytest.mark.django_db
def test_ceo_attention_includes_only_rejected_and_overdue_submissions():
    entity = LegalEntity.objects.get(code="ASAN")
    field_user = _user("auto-report-ceo-attention", Role.FIELD, entity)
    project = Project.objects.create(code="AUTO-REPORT-CEO-01", name="CEO 예외 공사일보", legal_entity=entity)
    plan = SchedulePlan.objects.create(project=project)
    rejected_task = ScheduleTask.objects.create(plan=plan, name="반려 작업", weight_percent=Decimal("50"))
    waiting_task = ScheduleTask.objects.create(plan=plan, name="대기 작업", weight_percent=Decimal("50"))
    rejected = DailyProgress.objects.create(
        project=project, plan=plan, task=rejected_task, report_date=date(2026, 8, 26),
        progress_percent=Decimal("30"), status="rejected", reporter=field_user,
    )
    waiting = DailyProgress.objects.create(
        project=project, plan=plan, task=waiting_task, report_date=date(2026, 8, 26),
        progress_percent=Decimal("20"), status="submitted", reporter=field_user,
    )
    created_at = timezone.make_aware(datetime(2026, 8, 26, 9, 0))
    DailyProgress.objects.filter(id__in=[rejected.id, waiting.id]).update(created_at=created_at)

    report = build_project_daily_report(project=project, as_of_date=date(2026, 8, 31))

    assert report["ceo_attention"] == {
        "total": 2,
        "rejected_count": 1,
        "overdue_submission_count": 1,
        "wait_days": 2,
    }
    assert report["approved_work_items"] == []


@pytest.mark.django_db
def test_field_project_daily_report_pdf_is_scoped_and_is_a_pdf():
    entity = LegalEntity.objects.get(code="ASAN")
    field_user = _user("auto-report-pdf-field", Role.FIELD, entity)
    project = Project.objects.create(code="AUTO-REPORT-05", name="PDF 공사일보", legal_entity=entity)
    ProjectAssignment.objects.create(user=field_user, project=project, is_active=True)
    client = Client()
    client.force_login(field_user)
    session = client.session
    session["current_legal_entity_id"] = entity.id
    session.save()

    response = client.get(f"/app/field/site-daily-logs/projects/{project.id}/print.pdf?as_of_date=2026-08-26")

    assert response.status_code == 200
    assert response["Content-Type"] == "application/pdf"
    assert b"".join(response.streaming_content).startswith(b"%PDF")


@pytest.mark.django_db
def test_project_pdf_export_does_not_create_source_records():
    entity = LegalEntity.objects.get(code="ASAN")
    project = Project.objects.create(code="AUTO-REPORT-06", name="무변경 PDF", legal_entity=entity)
    before = DailyProgress.objects.count()

    stream = project_daily_report_pdf(build_project_daily_report(project=project, as_of_date=date(2026, 8, 26)))

    assert stream.read(4) == b"%PDF"
    assert DailyProgress.objects.count() == before
