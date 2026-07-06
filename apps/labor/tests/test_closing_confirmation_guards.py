from datetime import date
from decimal import Decimal

import pytest
from django.contrib.auth import get_user_model
from django.core.exceptions import ValidationError
from django.utils import timezone

from apps.core.rbac.models import Role, UserProfile
from apps.labor.models import (
    ElectronicCardImportBatch,
    ElectronicCardImportBatchStatus,
    ElectronicCardMatchStatus,
    ElectronicCardWorkDay,
    ElectronicCardWorkRaw,
    LaborConfirmedWorkDay,
    LaborExcelExportBatch,
    LaborReconciliationResult,
    LaborReconciliationStatus,
    WorkerMaster,
)
from apps.labor.services import (
    bulk_resolve_labor_reconciliation_results,
    generate_cwma_card_reupload_excel,
    match_reconciliation_worker,
    parse_electronic_card_import_batch,
    reconcile_electronic_card_import_batch,
    resolve_labor_reconciliation_result,
)
from apps.projects.models import Project


def _hq_user(username="ecard-guard-hq"):
    user = get_user_model().objects.create_user(username=username, password="pass")
    UserProfile.objects.create(user=user, role=Role.HQ)
    return user


def _project(code="PRJ-ECARD-GUARD-001"):
    return Project.objects.create(code=code, name=code)


def _worker(name="Ecard Worker", rrn="910101-1234567"):
    worker = WorkerMaster(name=name, active=True)
    worker.set_rrn(rrn)
    worker.save()
    return worker


def _batch(project, *, status=ElectronicCardImportBatchStatus.CONFIRMED):
    return ElectronicCardImportBatch.objects.create(
        year_month=date(2026, 5, 1),
        project=project,
        status=status,
        original_filename="guard.xlsx",
    )


def _unmatched_result(batch, project):
    raw = ElectronicCardWorkRaw.objects.create(
        batch=batch,
        row_no=1,
        work_month=batch.year_month,
        worker_name_raw="Unmatched Worker",
        match_status=ElectronicCardMatchStatus.UNMATCHED,
    )
    day = ElectronicCardWorkDay.objects.create(
        raw=raw,
        batch=batch,
        worker=None,
        work_date=date(2026, 5, 1),
        card_value=Decimal("1"),
        is_worked=True,
        card_project=project,
        match_status=ElectronicCardMatchStatus.UNMATCHED,
    )
    return LaborReconciliationResult.objects.create(
        batch=batch,
        year_month=batch.year_month,
        project=project,
        worker=None,
        work_date=date(2026, 5, 1),
        erp_work_unit=Decimal("0"),
        card_work_unit=Decimal("1"),
        difference=Decimal("-1"),
        status=LaborReconciliationStatus.UNMATCHED,
        card_day=day,
    )


@pytest.mark.django_db
def test_confirmed_e_card_batch_blocks_parse_and_reconcile():
    actor = _hq_user("ecard-parse-reconcile")
    project = _project("PRJ-ECARD-GUARD-001")
    batch = _batch(project)

    with pytest.raises(ValidationError):
        parse_electronic_card_import_batch(batch, actor)
    with pytest.raises(ValidationError):
        reconcile_electronic_card_import_batch(batch, actor)

    assert batch.raw_rows.count() == 0
    assert batch.day_rows.count() == 0
    assert batch.reconciliation_results.count() == 0


@pytest.mark.django_db
def test_confirmed_e_card_batch_blocks_resolve_match_and_bulk_resolve():
    actor = _hq_user("ecard-resolve-match")
    project = _project("PRJ-ECARD-GUARD-002")
    batch = _batch(project)
    result = _unmatched_result(batch, project)
    worker = _worker()
    LaborConfirmedWorkDay.objects.create(
        batch=batch,
        year_month=batch.year_month,
        worker=None,
        actual_project=project,
        report_project=project,
        card_project=project,
        work_date=result.work_date,
        final_work_unit=Decimal("0"),
        source_basis="EXCLUDED",
        reconciliation_result=result,
        export_included=False,
        export_value=Decimal("0"),
        confirmed_by=actor,
        confirmed_at=timezone.now(),
    )

    with pytest.raises(ValidationError):
        resolve_labor_reconciliation_result(result, "CARD", actor, comment="blocked")
    with pytest.raises(ValidationError):
        match_reconciliation_worker(result, worker, actor)
    with pytest.raises(ValidationError):
        bulk_resolve_labor_reconciliation_results([result.id], "EXCLUDED", actor, "blocked")

    result.refresh_from_db()
    assert result.status == LaborReconciliationStatus.UNMATCHED
    assert result.resolution == ""
    assert LaborConfirmedWorkDay.objects.filter(batch=batch).count() == 1


@pytest.mark.django_db
def test_generate_cwma_export_before_confirmed_is_blocked():
    actor = _hq_user("ecard-export-before")
    project = _project("PRJ-ECARD-GUARD-003")
    batch = _batch(project, status=ElectronicCardImportBatchStatus.PARSE_READY)

    with pytest.raises(ValidationError):
        generate_cwma_card_reupload_excel(batch, actor)

    assert LaborExcelExportBatch.objects.count() == 0
