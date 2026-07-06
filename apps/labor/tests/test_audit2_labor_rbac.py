from datetime import date
from decimal import Decimal

import pytest
from django.contrib.auth import get_user_model
from django.core.exceptions import PermissionDenied
from django.core.files.base import ContentFile
from django.test import Client

from apps.core.rbac.models import Role, UserProfile
from apps.labor.models import (
    ElectronicCardImportBatch,
    ElectronicCardImportBatchStatus,
    LaborExcelExportBatch,
    LaborExcelExportStatus,
    LaborExcelExportType,
    WorkerMaster,
)
from apps.labor.services import (
    parse_electronic_card_import_batch,
    reconcile_electronic_card_import_batch,
)
from apps.projects.models import Project


@pytest.fixture(autouse=True)
def _disable_two_factor_enforce(settings):
    settings.MIDDLEWARE = [
        middleware
        for middleware in settings.MIDDLEWARE
        if middleware != "apps.core.middleware.two_factor_enforce.TwoFactorEnforceMiddleware"
    ]


def _user(role, username):
    user = get_user_model().objects.create_user(username=username, password="pass")
    UserProfile.objects.create(user=user, role=role)
    return user


def _client(user):
    client = Client()
    client.force_login(user)
    return client


def _project(code="PRJ-LAB-RBAC-001"):
    return Project.objects.create(code=code, name=code)


def _worker(name="RBAC Worker", rrn="910101-1234567"):
    worker = WorkerMaster(name=name, active=True)
    worker.set_rrn(rrn)
    worker.save()
    return worker


def _batch(project):
    return ElectronicCardImportBatch.objects.create(
        year_month=date(2026, 5, 1),
        project=project,
        status=ElectronicCardImportBatchStatus.PARSE_READY,
        source_file=ContentFile(b"not-a-real-workbook", name="source.xlsx"),
        original_filename="source.xlsx",
    )


def _export(project, batch):
    return LaborExcelExportBatch.objects.create(
        export_type=LaborExcelExportType.CWMA_CARD_REUPLOAD,
        year_month=date(2026, 5, 1),
        project=project,
        source_batch=batch,
        generated_file=ContentFile(b"export-bytes", name="export.xlsx"),
        original_filename="source.xlsx",
        generated_filename="export.xlsx",
        status=LaborExcelExportStatus.GENERATED,
        changed_count=1,
        included_count=1,
        excluded_count=0,
        total_export_work_unit=Decimal("1"),
    )


@pytest.mark.django_db
@pytest.mark.parametrize(
    "url",
    [
        "/app/hq/labor/e-card-imports/",
        "/app/hq/labor/workers/",
        "/app/hq/labor/work-ledger/",
        "/app/hq/labor/reporting-map/",
        "/app/hq/labor/monthly-payroll/",
        "/app/hq/labor/payroll-allocation/",
    ],
)
def test_field_cannot_open_hq_labor_pages(url):
    field_user = _user(Role.FIELD, f"field-labor-{abs(hash(url))}")

    response = _client(field_user).get(url)

    assert response.status_code == 403


@pytest.mark.django_db
def test_field_cannot_open_e_card_detail_or_download_export(settings, tmp_path):
    settings.MEDIA_ROOT = tmp_path
    field_user = _user(Role.FIELD, "field-labor-detail")
    project = _project()
    batch = _batch(project)
    export = _export(project, batch)

    detail_response = _client(field_user).get(f"/app/hq/labor/e-card-imports/{batch.id}/")
    download_response = _client(field_user).get(
        f"/app/hq/labor/excel-exports/{export.id}/download/"
    )

    assert detail_response.status_code == 403
    assert download_response.status_code == 403
    export.refresh_from_db()
    assert export.status == LaborExcelExportStatus.GENERATED
    assert export.downloaded_by_id is None


@pytest.mark.django_db
def test_field_cannot_create_or_delete_worker_master():
    field_user = _user(Role.FIELD, "field-worker-write")
    worker = _worker()

    create_response = _client(field_user).post(
        "/app/hq/labor/workers/new/",
        {"name": "Blocked Worker", "rrn": "920101-1234567"},
    )
    delete_response = _client(field_user).post(f"/app/hq/labor/workers/{worker.id}/delete/")

    assert create_response.status_code == 403
    assert delete_response.status_code == 403
    assert WorkerMaster.objects.filter(name="Blocked Worker").count() == 0
    assert WorkerMaster.objects.filter(id=worker.id).exists()


@pytest.mark.django_db
def test_field_cannot_parse_or_reconcile_e_card_batch_service():
    field_user = _user(Role.FIELD, "field-labor-service")
    project = _project("PRJ-LAB-RBAC-002")
    batch = _batch(project)

    with pytest.raises(PermissionDenied):
        parse_electronic_card_import_batch(batch, field_user)
    with pytest.raises(PermissionDenied):
        reconcile_electronic_card_import_batch(batch, field_user)


@pytest.mark.django_db
def test_hq_and_ceo_can_open_e_card_import_list():
    hq_user = _user(Role.HQ, "hq-labor-rbac")
    ceo_user = _user(Role.CEO, "ceo-labor-rbac")

    assert _client(hq_user).get("/app/hq/labor/e-card-imports/").status_code == 200
    assert _client(ceo_user).get("/app/hq/labor/e-card-imports/").status_code == 200


@pytest.mark.django_db
def test_hq_can_download_labor_excel_export(settings, tmp_path):
    settings.MEDIA_ROOT = tmp_path
    hq_user = _user(Role.HQ, "hq-labor-download")
    project = _project("PRJ-LAB-RBAC-003")
    batch = _batch(project)
    export = _export(project, batch)

    response = _client(hq_user).get(f"/app/hq/labor/excel-exports/{export.id}/download/")

    assert response.status_code == 200
    export.refresh_from_db()
    assert export.status == LaborExcelExportStatus.DOWNLOADED
    assert export.downloaded_by == hq_user
