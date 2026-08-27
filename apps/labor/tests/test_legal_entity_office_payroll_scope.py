import pytest
from django.contrib.auth import get_user_model
from django.core.exceptions import ValidationError

from apps.core.rbac.models import LegalEntity, LegalEntityAccessScope, Role, UserLegalEntityMembership, UserProfile
from apps.labor.models import OfficeEmployeeProfile, OfficePayrollRun
from apps.labor.services import create_payroll_batch, upsert_payroll_lines
from apps.projects.models import Project


@pytest.mark.django_db
def test_office_payroll_and_allocation_stay_with_the_employing_entity():
    asan = LegalEntity.objects.get(code="ASAN")
    misan = LegalEntity.objects.get(code="MISAN")
    hq = get_user_model().objects.create_user(username="entity-payroll-hq", password="pass")
    UserProfile.objects.create(user=hq, role=Role.HQ)
    UserLegalEntityMembership.objects.create(
        user=hq, legal_entity=asan, access_scope=LegalEntityAccessScope.GROUP_HQ
    )
    UserLegalEntityMembership.objects.create(
        user=hq, legal_entity=misan, access_scope=LegalEntityAccessScope.GROUP_HQ
    )
    employee_user = get_user_model().objects.create_user(username="asan-office-employee", password="pass")
    employee = OfficeEmployeeProfile.objects.create(
        user=employee_user,
        employee_no="ASAN-HQ-2026-9001",
        employment_legal_entity=asan,
    )
    run = OfficePayrollRun.objects.create(
        period_year=2026,
        period_month=10,
        legal_entity=asan,
        created_by=hq,
    )
    assert employee.employment_legal_entity_id == run.legal_entity_id

    asan_project = Project.objects.create(code="ASAN-CIV-PAY-SCOPE", name="아산 원가 현장", legal_entity=asan)
    misan_project = Project.objects.create(code="MISAN-LAND-PAY-SCOPE", name="미산 운영지원 현장", legal_entity=misan)
    batch = create_payroll_batch(
        year=2026,
        month=10,
        total_amount=100_000,
        legal_entity=asan,
        actor=hq,
    )

    upsert_payroll_lines(batch, [{"project_id": asan_project.id, "amount": 100_000}], actor=hq)
    with pytest.raises(ValidationError, match="고용 법인과 같은 법인 프로젝트"):
        upsert_payroll_lines(batch, [{"project_id": misan_project.id, "amount": 100_000}], actor=hq)
