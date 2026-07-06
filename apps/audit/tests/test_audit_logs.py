from decimal import Decimal

import pytest
from django.contrib.auth import get_user_model
from django.core.files.uploadedfile import SimpleUploadedFile
from rest_framework.test import APIClient

from apps.audit.constants import (
    APPROVAL_APPROVE,
    CONTRACT_APPROVE,
    EVIDENCE_FILE_ADD,
    RISK_ACK,
)
from apps.audit.models import AuditLog
from apps.audit.services.logger import log_action
from apps.contracts.models import ContractChange, ContractChangeStatus
from apps.core.rbac.models import UserProfile
from apps.cost.models import CostActual, CostActualStatus
from apps.evidence.models import Evidence
from apps.projects.models import Project
from apps.risk.models import RiskFinding, RiskFindingStatus, RiskRule


@pytest.fixture
def hq_user(db):
    user = get_user_model().objects.create_user(username="hq", password="pass")
    UserProfile.objects.create(user=user, role="hq")
    return user


@pytest.fixture
def field_user(db):
    user = get_user_model().objects.create_user(username="field", password="pass")
    UserProfile.objects.create(user=user, role="field")
    return user


@pytest.fixture
def auth_client(hq_user):
    client = APIClient()
    client.force_authenticate(user=hq_user)
    return client


@pytest.fixture
def project(db):
    return Project.objects.create(code="PRJ-AUD-001", name="Audit Project")


def _extract_results(response):
    data = response.json()
    if isinstance(data, dict) and "results" in data:
        return data["results"]
    return data


def test_approval_approve_creates_audit_log(auth_client, project):
    cost_actual = CostActual.objects.create(
        project=project, report_date="2024-01-01", status=CostActualStatus.DRAFT
    )
    submit_resp = auth_client.post(
        "/api/approvals/submit/",
        {"object_type": "COST_ACTUAL", "object_id": cost_actual.id},
        format="json",
    )
    approval_id = submit_resp.json()["id"]

    approve_resp = auth_client.post(f"/api/approvals/{approval_id}/approve/", format="json")
    assert approve_resp.status_code == 200
    assert AuditLog.objects.filter(action=APPROVAL_APPROVE).exists()


def test_contract_change_approve_creates_audit_log(auth_client, project):
    change = ContractChange.objects.create(
        project=project,
        change_no=1,
        change_type="design_change",
        reason="Scope update",
        contract_amount_delta=Decimal("5000"),
        time_extension_days=3,
        status=ContractChangeStatus.SUBMITTED,
    )

    response = auth_client.post(f"/api/contract-changes/{change.id}/approve/")
    assert response.status_code == 200
    assert AuditLog.objects.filter(action=CONTRACT_APPROVE, object_id=change.id).exists()


def test_evidence_file_upload_creates_audit_log(auth_client, project):
    evidence_resp = auth_client.post(
        "/api/evidence/",
        {
            "title": "Contract Evidence",
            "description": "",
            "object_type": "CONTRACT_CHANGE",
            "object_id": 999,
        },
        format="json",
    )
    evidence_id = evidence_resp.json()["id"]

    upload_file = SimpleUploadedFile("evidence.txt", b"evidence", content_type="text/plain")
    file_resp = auth_client.post(
        f"/api/evidence/{evidence_id}/files/",
        {"file": upload_file},
        format="multipart",
    )
    assert file_resp.status_code == 201

    log = AuditLog.objects.filter(action=EVIDENCE_FILE_ADD, object_id=evidence_id).first()
    assert log is not None
    assert log.meta_json.get("sha256")


def test_risk_ack_creates_audit_log(auth_client, project):
    rule = RiskRule.objects.create(
        key="AUDIT_RISK",
        name="Audit Risk",
        description="",
        severity="high",
        threshold_json={"max_daily_delta": 5},
        is_active=True,
    )
    finding = RiskFinding.objects.create(
        rule=rule,
        project=project,
        object_type="PROJECT",
        object_id=project.id,
        score=Decimal("1.000"),
        severity="high",
        title="Risk",
        details="",
        status=RiskFindingStatus.OPEN,
    )

    response = auth_client.post(f"/api/risk/findings/{finding.id}/ack/")
    assert response.status_code == 200
    log = AuditLog.objects.filter(action=RISK_ACK, object_id=finding.id).first()
    assert log is not None
    assert log.meta_json.get("previous_status") == "open"


def test_audit_logs_filter_by_project(auth_client, project):
    log_action(
        actor=get_user_model().objects.get(username="hq"),
        action="PROJECT_TEST",
        object_type="PROJECT",
        object_id=project.id,
        project=project,
        meta={"value": "ok"},
    )

    response = auth_client.get(f"/api/audit-logs/?project_id={project.id}")
    results = _extract_results(response)
    assert response.status_code == 200
    assert all(item["project"] == project.id for item in results)


def test_sensitive_keys_masked(db):
    log = log_action(
        actor=None,
        action="MASK_TEST",
        object_type="TEST",
        object_id=1,
        meta={"token": "abc", "nested": {"password": "secret"}},
    )
    assert log.meta_json["token"] == "[REDACTED]"
    assert log.meta_json["nested"]["password"] == "[REDACTED]"
