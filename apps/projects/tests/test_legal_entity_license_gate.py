from datetime import date

import pytest

from apps.core.rbac.models import LegalEntity, LegalEntityLicense
from apps.projects.forms import ProjectOnboardingForm
from apps.projects.hq_views import _build_budget_initial_from_templates


def _form_data(*, entity, license_objs, work_types):
    return {
        "legal_entity": entity.id,
        "contracting_licenses": [license_obj.id for license_obj in license_objs],
        "name": "면허 검증 공사",
        "work_types": work_types,
        "start_date": "2026-08-20",
        "end_date": "2026-11-20",
        "status": "draft",
        "client_name": "발주처",
        "site_address": "현장 주소",
    }


@pytest.mark.django_db
def test_project_onboarding_accepts_matching_entity_license_and_preserves_selection():
    asan = LegalEntity.objects.get(code="ASAN")
    civil_license = LegalEntityLicense.objects.get(legal_entity=asan, license_type="토목공사업")

    form = ProjectOnboardingForm(
        data=_form_data(entity=asan, license_objs=[civil_license], work_types=["civil"])
    )

    assert form.is_valid(), form.errors
    project = form.save(commit=False)
    assert list(form.cleaned_data["contracting_licenses"]) == [civil_license]


@pytest.mark.django_db
def test_project_onboarding_blocks_other_entity_or_wrong_work_license():
    asan = LegalEntity.objects.get(code="ASAN")
    misan = LegalEntity.objects.get(code="MISAN")
    misan_license = LegalEntityLicense.objects.get(legal_entity=misan, license_type="조경식재공사업")
    landscape_license = LegalEntityLicense.objects.get(legal_entity=asan, license_type="조경공사업")

    other_entity_form = ProjectOnboardingForm(
        data=_form_data(entity=asan, license_objs=[misan_license], work_types=["landscape"])
    )
    wrong_type_form = ProjectOnboardingForm(
        data=_form_data(entity=asan, license_objs=[landscape_license], work_types=["civil"])
    )

    assert not other_entity_form.is_valid()
    assert "계약 법인" in str(other_entity_form.errors["contracting_licenses"])
    assert not wrong_type_form.is_valid()
    assert "토목" in str(wrong_type_form.errors["contracting_licenses"])


@pytest.mark.django_db
def test_project_onboarding_blocks_expired_license():
    asan = LegalEntity.objects.get(code="ASAN")
    expired = LegalEntityLicense.objects.create(
        legal_entity=asan,
        license_type="토목공사업",
        registration_number="TEST-EXPIRED-01",
        registered_on=date(2020, 1, 1),
        registered_by="테스트 등록처",
        valid_to=date(2026, 8, 19),
    )
    form = ProjectOnboardingForm(data=_form_data(entity=asan, license_objs=[expired], work_types=["civil"]))

    assert not form.is_valid()
    assert "유효기간" in str(form.errors["contracting_licenses"])


@pytest.mark.django_db
def test_project_onboarding_accepts_combined_work_types_and_both_required_licenses():
    asan = LegalEntity.objects.get(code="ASAN")
    civil = LegalEntityLicense.objects.get(legal_entity=asan, license_type="토목공사업")
    landscape = LegalEntityLicense.objects.get(legal_entity=asan, license_type="조경공사업")
    form = ProjectOnboardingForm(
        data=_form_data(entity=asan, license_objs=[civil, landscape], work_types=["civil", "landscape"])
    )

    assert form.is_valid(), form.errors
    assert set(form.cleaned_data["work_types"]) == {"civil", "landscape"}


@pytest.mark.django_db
def test_empty_template_selection_returns_budget_rows_not_a_tuple_row():
    rows, warnings = _build_budget_initial_from_templates([])

    assert isinstance(rows, list)
    assert all(isinstance(row, dict) for row in rows)
    assert isinstance(warnings, list)
