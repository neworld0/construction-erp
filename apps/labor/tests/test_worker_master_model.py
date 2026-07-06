import pytest

from apps.labor.models import WorkerMaster


@pytest.mark.django_db
def test_worker_master_direct_create_protects_sensitive_values():
    raw_rrn = "900101-1234567"
    raw_account = "12345678901234"

    worker = WorkerMaster.objects.create(
        name="홍길동",
        rrn_encrypted=raw_rrn,
        account_number_encrypted=raw_account,
    )

    assert worker.rrn_encrypted != raw_rrn
    assert worker.rrn_masked == "900101-1******"
    assert worker.identity_hash
    assert worker.account_number_encrypted != raw_account
    assert worker.account_number_masked == "***1234"


@pytest.mark.django_db
def test_worker_master_same_rrn_has_same_identity_hash():
    worker_a = WorkerMaster.objects.create(
        name="근로자A",
        rrn_encrypted="900101-1234567",
    )
    worker_b = WorkerMaster.objects.create(
        name="근로자B",
        rrn_encrypted="9001011234567",
    )

    assert worker_a.identity_hash
    assert worker_a.identity_hash == worker_b.identity_hash


@pytest.mark.django_db
def test_worker_master_rrn_mask_hides_back_digits():
    worker = WorkerMaster.objects.create(
        name="마스킹확인",
        rrn_encrypted="900101-1234567",
    )

    assert worker.rrn_masked == "900101-1******"
    assert "234567" not in worker.rrn_masked
