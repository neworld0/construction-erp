from decimal import Decimal

import pytest
from django.contrib.auth import get_user_model
from rest_framework.test import APIClient

from apps.core.rbac.models import UserProfile
from apps.finance.models import CashAccount, CashEvent
from apps.projects.models import Project


@pytest.fixture
def project(db):
    return Project.objects.create(code="PRJ-CASH-001", name="Cash Project")


@pytest.fixture
def hq_client(db):
    client = APIClient()
    user = get_user_model().objects.create_user(username="hq-cash", password="pass")
    UserProfile.objects.create(user=user, role="hq")
    client.force_authenticate(user=user)
    return client


@pytest.fixture
def field_client(db):
    client = APIClient()
    user = get_user_model().objects.create_user(username="field-cash", password="pass")
    UserProfile.objects.create(user=user, role="field")
    client.force_authenticate(user=user)
    return client


def _create_events(project, created_by):
    account = CashAccount.objects.create(name="Main")
    CashEvent.objects.create(
        project=project,
        account=account,
        event_type="in",
        status="confirmed",
        amount=Decimal("1000.00"),
        event_date="2024-01-05",
        description="Confirmed inflow",
        created_by=created_by,
    )
    CashEvent.objects.create(
        project=project,
        account=account,
        event_type="out",
        status="confirmed",
        amount=Decimal("200.00"),
        event_date="2024-01-10",
        description="Confirmed outflow",
        created_by=created_by,
    )
    CashEvent.objects.create(
        project=project,
        account=account,
        event_type="in",
        status="planned",
        amount=Decimal("300.00"),
        event_date="2024-01-15",
        description="Planned inflow",
        created_by=created_by,
    )
    CashEvent.objects.create(
        project=project,
        account=account,
        event_type="out",
        status="planned",
        amount=Decimal("50.00"),
        event_date="2024-01-20",
        description="Planned outflow",
        created_by=created_by,
    )


def test_field_unassigned_summary_forbidden(field_client, project):
    response = field_client.get(f"/api/ceo/projects/{project.id}/summary/")
    assert response.status_code == 403


def test_hq_summary_success(hq_client, project):
    response = hq_client.get(f"/api/ceo/projects/{project.id}/summary/")
    assert response.status_code == 200


def test_cash_summary_calculation(hq_client, project):
    user = get_user_model().objects.get(username="hq-cash")
    _create_events(project, user)

    response = hq_client.get(
        f"/api/ceo/projects/{project.id}/summary/?as_of_date=2024-01-20"
    )
    assert response.status_code == 200
    cash = response.json()["cash_summary"]
    assert Decimal(cash["inflow_confirmed"]) == Decimal("1000.00")
    assert Decimal(cash["outflow_confirmed"]) == Decimal("200.00")
    assert Decimal(cash["net_confirmed"]) == Decimal("800.00")
    assert Decimal(cash["inflow_planned"]) == Decimal("300.00")
    assert Decimal(cash["outflow_planned"]) == Decimal("50.00")
    assert Decimal(cash["net_planned"]) == Decimal("250.00")
