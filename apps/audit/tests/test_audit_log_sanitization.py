import json

import pytest
from django.contrib.auth import get_user_model

from apps.audit.models import AuditLog
from apps.audit.services.logger import REDACTED, log_action, sanitize_audit_payload
from apps.core.rbac.models import Role, UserProfile
from apps.labor.services import create_worker_master


@pytest.fixture
def hq_user(db):
    user = get_user_model().objects.create_user(username="audit-hq", password="pass")
    UserProfile.objects.create(user=user, role=Role.HQ)
    return user


def _dump_payload(*parts):
    return json.dumps(parts, ensure_ascii=False, sort_keys=True, default=str)


def test_sanitize_audit_payload_masks_sensitive_keys_recursively():
    payload = {
        "token": "abc",
        "identity_hash": "hash-value",
        "nested": {
            "rrn_masked": "900101-1******",
            "account_number_encrypted": "enc1:secret",
            "items": [
                {"password": "secret"},
                ("safe", {"raw_phone": "010-1234-5678"}),
            ],
        },
        "safe": {"sha256": "abc123", "project_id": 7},
    }

    sanitized = sanitize_audit_payload(payload)

    assert sanitized["token"] == REDACTED
    assert sanitized["identity_hash"] == REDACTED
    assert sanitized["nested"]["rrn_masked"] == REDACTED
    assert sanitized["nested"]["account_number_encrypted"] == REDACTED
    assert sanitized["nested"]["items"][0]["password"] == REDACTED
    assert sanitized["nested"]["items"][1][1]["raw_phone"] == REDACTED
    assert sanitized["safe"]["sha256"] == "abc123"
    assert sanitized["safe"]["project_id"] == 7


def test_log_action_sanitizes_before_after_and_meta(hq_user):
    log = log_action(
        actor=hq_user,
        action="AUDIT_SANITIZE_TEST",
        object_type="WorkerMaster",
        object_id=1,
        before={"resident_no": "900101-1234567", "name": "홍길동"},
        after={"account_number": "123-456-789012", "status": "updated"},
        meta={"authorization": "Bearer abc.def.ghi", "ip": "127.0.0.1"},
    )

    assert log.before_json["resident_no"] == REDACTED
    assert log.before_json["name"] == "홍길동"
    assert log.after_json["account_number"] == REDACTED
    assert log.after_json["status"] == "updated"
    assert log.meta_json["authorization"] == REDACTED
    assert log.meta_json["ip"] == "127.0.0.1"


def test_worker_master_audit_snapshot_does_not_store_rrn_or_account_identifiers(hq_user):
    worker = create_worker_master(
        {
            "name": "김현장",
            "rrn": "900101-1234567",
            "phone": "010-1111-2222",
            "bank_name": "테스트은행",
            "account_number": "123-456-789012",
            "account_holder": "김현장",
        },
        actor=hq_user,
    )

    log = AuditLog.objects.get(action="LABOR_WORKER_CREATE", object_id=worker.id)
    dumped = _dump_payload(log.before_json, log.after_json, log.meta_json)

    assert log.after_json["rrn_masked"] == REDACTED
    assert log.after_json["account_number_masked"] == REDACTED
    assert log.after_json["identity_hash"] == REDACTED
    assert "900101-1234567" not in dumped
    assert "900101-1" not in dumped
    assert "123-456-789012" not in dumped
    assert worker.identity_hash not in dumped
    assert "김현장" in dumped


def test_non_sensitive_audit_metadata_is_preserved(hq_user):
    log = log_action(
        actor=hq_user,
        action="AUDIT_METADATA_TEST",
        object_type="Evidence",
        object_id=3,
        meta={
            "sha256": "ab12cd34",
            "project_id": 12,
            "file_name": "증빙.pdf",
            "amount": "100000",
        },
    )

    assert log.meta_json == {
        "sha256": "ab12cd34",
        "project_id": 12,
        "file_name": "증빙.pdf",
        "amount": "100000",
    }
