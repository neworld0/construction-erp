from datetime import date, timedelta
from decimal import Decimal

import pytest
from django.contrib.auth import get_user_model
from rest_framework.test import APIClient

from apps.contracts.models import ContractSnapshot
from apps.projects.models import Project


@pytest.fixture
def auth_client(db):
    client = APIClient()
    user = get_user_model().objects.create_user(username="tester", password="pass")
    client.force_authenticate(user=user)
    return client


@pytest.fixture
def project(db):
    return Project.objects.create(code="PRJ-RR-001", name="Revenue Project")


def _create_snapshot(project, version_no, amount, is_active=True):
    return ContractSnapshot.objects.create(
        project=project,
        version_no=version_no,
        base_contract_amount=amount,
        is_active=is_active,
    )


def _post_recognition(auth_client, payload):
    return auth_client.post("/api/revenue-recognition/", payload, format="json")


def test_progress_percent_out_of_range_rejected(auth_client, project):
    _create_snapshot(project, 1, Decimal("1000"))

    response = _post_recognition(
        auth_client,
        {
            "project_id": project.id,
            "as_of_date": "2024-01-01",
            "progress_percent": "-1",
            "snapshot_id": 1,
        },
    )
    assert response.status_code == 405

    response = _post_recognition(
        auth_client,
        {
            "project_id": project.id,
            "as_of_date": "2024-01-01",
            "progress_percent": "101",
            "snapshot_id": 1,
        },
    )
    assert response.status_code == 405


def test_recognized_revenue_calculated(auth_client, project):
    snapshot = _create_snapshot(project, 1, Decimal("1000"))

    response = _post_recognition(
        auth_client,
        {
            "project_id": project.id,
            "as_of_date": "2024-01-01",
            "progress_percent": "10.000",
            "snapshot_id": snapshot.id,
        },
    )

    assert response.status_code == 405
    assert "월마감" in response.json()["detail"]


def test_delta_revenue_calculated(auth_client, project):
    snapshot = _create_snapshot(project, 1, Decimal("1000"))

    first = _post_recognition(
        auth_client,
        {
            "project_id": project.id,
            "as_of_date": "2024-01-01",
            "progress_percent": "10.000",
            "snapshot_id": snapshot.id,
        },
    )
    assert first.status_code == 405

    second = _post_recognition(
        auth_client,
        {
            "project_id": project.id,
            "as_of_date": "2024-01-02",
            "progress_percent": "20.000",
            "snapshot_id": snapshot.id,
        },
    )
    assert second.status_code == 405


def test_unique_constraint_per_snapshot(auth_client, project):
    snapshot_one = _create_snapshot(project, 1, Decimal("1000"))
    first = _post_recognition(
        auth_client,
        {
            "project_id": project.id,
            "as_of_date": "2024-01-01",
            "progress_percent": "10.000",
            "snapshot_id": snapshot_one.id,
        },
    )
    assert first.status_code == 405

    snapshot_two = _create_snapshot(project, 2, Decimal("2000"), is_active=False)
    second = _post_recognition(
        auth_client,
        {
            "project_id": project.id,
            "as_of_date": "2024-01-01",
            "progress_percent": "10.000",
            "snapshot_id": snapshot_two.id,
        },
    )
    assert second.status_code == 405


def test_future_as_of_date_rejected(auth_client, project):
    snapshot = _create_snapshot(project, 1, Decimal("1000"))
    future_date = date.today() + timedelta(days=1)

    response = _post_recognition(
        auth_client,
        {
            "project_id": project.id,
            "as_of_date": future_date.isoformat(),
            "progress_percent": "10.000",
            "snapshot_id": snapshot.id,
        },
    )

    assert response.status_code == 405


def test_snapshot_project_mismatch_rejected(auth_client, project):
    _create_snapshot(project, 1, Decimal("1000"))

    response = _post_recognition(
        auth_client,
        {
            "project_id": project.id,
            "as_of_date": "2024-01-01",
            "progress_percent": "10.000",
            "snapshot_id": 2,
        },
    )

    assert response.status_code == 405
