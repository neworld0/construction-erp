from datetime import date
from decimal import Decimal

import pytest
from django.contrib.auth import get_user_model
from rest_framework.test import APIClient

from apps.core.rbac.models import UserProfile
from apps.projects.models import Project
from apps.schedule.models import DailyProgress, SchedulePlan, ScheduleTask


@pytest.fixture
def auth_client(db):
    client = APIClient()
    user = get_user_model().objects.create_user(username="tester", password="pass")
    UserProfile.objects.create(user=user, role="hq")
    client.force_authenticate(user=user)
    return client


@pytest.fixture
def project(db):
    return Project.objects.create(code="PRJ-PG-001", name="Progress Project")


@pytest.fixture
def active_plan(project, db):
    return SchedulePlan.objects.create(project=project, version_no=1, is_active=True)


@pytest.fixture
def tasks(active_plan, db):
    task_a = ScheduleTask.objects.create(
        plan=active_plan, name="Task A", weight_percent=Decimal("40.000"), sort_order=1
    )
    task_b = ScheduleTask.objects.create(
        plan=active_plan, name="Task B", weight_percent=Decimal("60.000"), sort_order=2
    )
    return task_a, task_b


def test_no_project_returns_zero(auth_client):
    response = auth_client.get("/api/progress/")
    data = response.json()

    assert response.status_code == 200
    assert data["overall_progress_percent"] == "0"
    assert data["tasks"] == []


def test_single_task_progress_reflected(auth_client, project, active_plan, tasks):
    task_a, _task_b = tasks
    user = get_user_model().objects.get(username="tester")
    DailyProgress.objects.create(
        project=project,
        plan=active_plan,
        task=task_a,
        report_date="2024-01-01",
        progress_percent=Decimal("50.000"),
        reporter=user,
    )

    response = auth_client.get(f"/api/progress/?project_id={project.id}")
    data = response.json()

    assert Decimal(data["overall_progress_percent"]) == Decimal("20.000")


def test_weighted_progress_correct(auth_client, project, active_plan, tasks):
    task_a, task_b = tasks
    user = get_user_model().objects.get(username="tester")
    DailyProgress.objects.create(
        project=project,
        plan=active_plan,
        task=task_a,
        report_date="2024-01-01",
        progress_percent=Decimal("50.000"),
        reporter=user,
    )
    DailyProgress.objects.create(
        project=project,
        plan=active_plan,
        task=task_b,
        report_date="2024-01-01",
        progress_percent=Decimal("25.000"),
        reporter=user,
    )

    response = auth_client.get(f"/api/progress/?project_id={project.id}")
    data = response.json()

    assert Decimal(data["overall_progress_percent"]).quantize(Decimal("0.001")) == Decimal("35.000")


def test_as_of_date_uses_latest(auth_client, project, active_plan, tasks):
    task_a, _task_b = tasks
    user = get_user_model().objects.get(username="tester")
    DailyProgress.objects.create(
        project=project,
        plan=active_plan,
        task=task_a,
        report_date="2024-01-01",
        progress_percent=Decimal("10.000"),
        reporter=user,
    )
    DailyProgress.objects.create(
        project=project,
        plan=active_plan,
        task=task_a,
        report_date="2024-01-02",
        progress_percent=Decimal("40.000"),
        reporter=user,
    )

    response = auth_client.get(
        f"/api/progress/?project_id={project.id}&as_of_date=2024-01-01"
    )
    data = response.json()

    assert Decimal(data["overall_progress_percent"]) == Decimal("4.000")
