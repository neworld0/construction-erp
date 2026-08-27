from datetime import date

import pytest
from django.contrib.auth import get_user_model
from django.core.files.uploadedfile import SimpleUploadedFile
from django.test import Client

from apps.audit.models import AuditLog
from apps.core.rbac.forms import LegalEntityLicenseConstructionPerformanceForm
from apps.core.rbac.models import (
    LegalEntity,
    LegalEntityAccessScope,
    LegalEntityCreditRating,
    LegalEntityCreditRatingEvidence,
    LegalEntityLicense,
    LegalEntityLicenseConstructionPerformance,
    LegalEntityLicenseConstructionPerformanceEvidence,
    Role,
    UserLegalEntityMembership,
    UserProfile,
)


@pytest.fixture(autouse=True)
def _disable_two_factor_enforce(settings):
    settings.MIDDLEWARE = [
        middleware
        for middleware in settings.MIDDLEWARE
        if middleware != "apps.core.middleware.two_factor_enforce.TwoFactorEnforceMiddleware"
    ]


@pytest.mark.django_db
def test_hq_can_store_entity_scoped_license_performance_with_audit_log():
    asan = LegalEntity.objects.get(code="ASAN")
    license_obj = LegalEntityLicense.objects.filter(legal_entity=asan, is_active=True).first()
    user = get_user_model().objects.create_user(username="license-performance-hq", password="pass")
    UserProfile.objects.create(user=user, role=Role.HQ)
    UserLegalEntityMembership.objects.create(
        user=user, legal_entity=asan, access_scope=LegalEntityAccessScope.ENTITY_HQ
    )
    client = Client()
    client.force_login(user)
    session = client.session
    session["current_legal_entity_id"] = asan.id
    session.save()

    initial_page = client.get("/app/hq/legal-entity/licenses/")
    assert initial_page.status_code == 200
    assert b'name="evidence_file"' not in initial_page.content
    entry_page = client.get("/app/hq/legal-entity/licenses/performances/new/")
    assert entry_page.status_code == 200
    assert b'name="evidence_file"' in entry_page.content

    initial_upload = SimpleUploadedFile("최초실적증명서.pdf", b"%PDF-1.4 initial", content_type="application/pdf")
    response = client.post(
        "/app/hq/legal-entity/licenses/",
        {
            "action": "performance",
            "license": license_obj.id,
            "work_category": "도로·포장",
            "external_category_code": "",
            "as_of_date": "2026-08-31",
            "three_year_amount": "1000000000",
            "five_year_amount": "1500000000",
            "source": "CERTIFICATE",
            "evidence_note": "실적증명서 기준",
            "evidence_file": initial_upload,
        },
    )

    assert response.status_code == 302
    performance = LegalEntityLicenseConstructionPerformance.objects.get(
        license=license_obj, work_category="도로·포장", as_of_date=date(2026, 8, 31)
    )
    assert performance.three_year_amount == 1_000_000_000
    assert performance.five_year_amount == 1_500_000_000
    assert AuditLog.objects.filter(
        action="LEGAL_ENTITY_LICENSE_PERFORMANCE_CREATED", object_id=performance.id
    ).exists()
    evidence = LegalEntityLicenseConstructionPerformanceEvidence.objects.get(
        performance=performance, original_name="최초실적증명서.pdf"
    )
    assert len(evidence.sha256) == 64

    upload = SimpleUploadedFile("추가실적증명서.pdf", b"%PDF-1.4 test", content_type="application/pdf")
    upload_response = client.post(
        "/app/hq/legal-entity/licenses/",
        {"action": "performance_evidence", "performance_id": performance.id, "file": upload},
    )
    assert upload_response.status_code == 302
    assert LegalEntityLicenseConstructionPerformanceEvidence.objects.filter(performance=performance).count() == 2
    assert AuditLog.objects.filter(
        action="LEGAL_ENTITY_LICENSE_PERFORMANCE_EVIDENCE_ADDED", object_id=performance.id
    ).exists()

    download_response = client.get(
        f"/app/hq/legal-entity/licenses/performances/evidence/{evidence.id}/download/"
    )
    assert download_response.status_code == 200
    assert b"".join(download_response.streaming_content) == b"%PDF-1.4 initial"

    credit_upload = SimpleUploadedFile("신용평가서.pdf", b"%PDF-1.4 credit", content_type="application/pdf")
    credit_response = client.post(
        "/app/hq/legal-entity/licenses/",
        {
            "action": "credit_rating",
            "rating_agency": "한국기업평가",
            "rating_grade": "A-",
            "assessed_on": "2026-08-01",
            "valid_until": "2027-07-31",
            "evidence_note": "신용평가서 기준",
            "evidence_file": credit_upload,
        },
    )
    assert credit_response.status_code == 302
    rating = LegalEntityCreditRating.objects.get(legal_entity=asan, rating_agency="한국기업평가")
    assert rating.rating_grade == "A-"
    assert AuditLog.objects.filter(
        action="LEGAL_ENTITY_CREDIT_RATING_CREATED", object_id=rating.id
    ).exists()
    credit_evidence = LegalEntityCreditRatingEvidence.objects.get(credit_rating=rating)
    assert credit_evidence.original_name == "신용평가서.pdf"
    credit_download_response = client.get(
        f"/app/hq/legal-entity/licenses/credit-ratings/evidence/{credit_evidence.id}/download/"
    )
    assert credit_download_response.status_code == 200
    assert b"".join(credit_download_response.streaming_content) == b"%PDF-1.4 credit"


@pytest.mark.django_db
def test_performance_rejects_invalid_amount_relation_and_other_entity_license():
    asan = LegalEntity.objects.get(code="ASAN")
    misan = LegalEntity.objects.get(code="MISAN")
    asan_license = LegalEntityLicense.objects.filter(legal_entity=asan, is_active=True).first()
    misan_license = LegalEntityLicense.objects.filter(legal_entity=misan, is_active=True).first()
    form = LegalEntityLicenseConstructionPerformanceForm(
        data={
            "license": asan_license.id,
            "work_category": "토목",
            "as_of_date": "2026-08-31",
            "three_year_amount": "100",
            "five_year_amount": "99",
            "source": "MANUAL",
        },
        legal_entity=asan,
    )
    assert not form.is_valid()
    assert "5년 실적" in str(form.errors)

    scope_form = LegalEntityLicenseConstructionPerformanceForm(
        data={
            "license": misan_license.id,
            "work_category": "조경",
            "as_of_date": "2026-08-31",
            "three_year_amount": "100",
            "five_year_amount": "100",
            "source": "MANUAL",
        },
        legal_entity=asan,
    )
    assert not scope_form.is_valid()
    assert "license" in scope_form.errors
