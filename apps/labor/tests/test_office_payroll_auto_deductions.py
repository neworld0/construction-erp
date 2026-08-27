from decimal import Decimal

import pytest
from django.contrib.auth import get_user_model

from apps.labor.models import IncomeTaxTableRow, IncomeTaxTableVersion, OfficeEmployeeProfile, OfficePayrollDeductionPolicy, OfficePayrollRun, OfficePayslip


@pytest.mark.django_db
def test_payslip_auto_deductions_are_reviewable_defaults():
    user = get_user_model().objects.create_user(username="office-payroll-employee")
    employee = OfficeEmployeeProfile.objects.create(user=user, employee_no="HQ-001")
    run = OfficePayrollRun.objects.create(period_year=2026, period_month=8, created_by=user)
    version = IncomeTaxTableVersion.objects.create(effective_from="2026-03-01", source_name="official.xlsx", is_active=True)
    IncomeTaxTableRow.objects.create(version=version, monthly_pay_from=0, monthly_pay_to=10_000_000, dependent_count=1, income_tax=159_000)
    policy = OfficePayrollDeductionPolicy.objects.create(
        year=2026, national_pension_rate=Decimal("0.045"), health_insurance_rate=Decimal("0.03595"),
        long_term_care_rate=Decimal("0.1314"), employment_insurance_rate=Decimal("0.009"), income_tax_rate=Decimal("0.03"),
    )
    slip = OfficePayslip.objects.create(run=run, employee=employee, base_pay=5_000_000, meal_allowance_pay=100_000, fuel_allowance_pay=0, site_allowance_pay=100_000, bonus_pay=100_000)
    slip.apply_auto_deductions(policy)
    slip.save()

    assert slip.gross_pay == 5_300_000
    assert slip.meal_allowance_pay == 100_000
    assert slip.site_allowance_pay == 100_000
    assert slip.national_pension == 234_000
    assert slip.health_insurance == 186_940
    assert slip.local_income_tax == int(slip.income_tax * 0.1)
    assert slip.net_pay == slip.gross_pay - slip.total_deduction


@pytest.mark.django_db
def test_official_income_tax_table_overrides_simple_income_tax_rate():
    user = get_user_model().objects.create_user(username="tax-table-employee")
    employee = OfficeEmployeeProfile.objects.create(user=user, employee_no="HQ-TAX", tax_dependent_count=2, tax_withholding_ratio=120)
    run = OfficePayrollRun.objects.create(period_year=2026, period_month=8, created_by=user)
    version = IncomeTaxTableVersion.objects.create(effective_from="2026-03-01", source_name="official.xlsx", is_active=True)
    IncomeTaxTableRow.objects.create(version=version, monthly_pay_from=0, monthly_pay_to=10_000_000, dependent_count=2, income_tax=10_000)
    policy = OfficePayrollDeductionPolicy.objects.create(year=2026, income_tax_rate=Decimal("0.99"))
    slip = OfficePayslip.objects.create(run=run, employee=employee, base_pay=3_000_000)

    slip.apply_auto_deductions(policy)

    assert slip.income_tax == 12_000
    assert slip.local_income_tax == 1_200
    assert slip.auto_tax_withholding_ratio == 120


@pytest.mark.django_db
def test_2026_social_insurance_matches_notice_rounding_units():
    user = get_user_model().objects.create_user(username="social-insurance-2026")
    employee = OfficeEmployeeProfile.objects.create(user=user, employee_no="HQ-SOCIAL")
    run = OfficePayrollRun.objects.create(period_year=2026, period_month=7, created_by=user)
    version = IncomeTaxTableVersion.objects.create(effective_from="2026-03-01", source_name="official.xlsx", is_active=True)
    IncomeTaxTableRow.objects.create(version=version, monthly_pay_from=0, monthly_pay_to=10_000_000, dependent_count=1, income_tax=0)
    policy = OfficePayrollDeductionPolicy.objects.create(
        year=2026,
        national_pension_rate=Decimal("0.0475"),
        health_insurance_rate=Decimal("0.03595"),
        long_term_care_rate=Decimal("0.1314"),
        employment_insurance_rate=Decimal("0.009"),
    )
    slip = OfficePayslip.objects.create(run=run, employee=employee, base_pay=3_100_000)

    slip.apply_auto_deductions(policy)

    assert slip.auto_national_pension == 147_250
    assert slip.auto_health_insurance == 111_440
    assert slip.auto_long_term_care == 14_640
    assert slip.auto_employment_insurance == 27_900


@pytest.mark.django_db
def test_national_pension_is_excluded_from_month_after_60th_birthday():
    user = get_user_model().objects.create_user(username="pension-age-limit")
    employee = OfficeEmployeeProfile.objects.create(user=user, employee_no="HQ-AGE")
    employee.set_birth_date("1966-08-15")
    employee.save(update_fields=["birth_date_encrypted", "birth_date_masked"])
    version = IncomeTaxTableVersion.objects.create(effective_from="2026-03-01", source_name="official.xlsx", is_active=True)
    IncomeTaxTableRow.objects.create(version=version, monthly_pay_from=0, monthly_pay_to=10_000_000, dependent_count=1, income_tax=0)
    policy = OfficePayrollDeductionPolicy.objects.create(year=2026, national_pension_rate=Decimal("0.0475"))
    birthday_month = OfficePayslip.objects.create(run=OfficePayrollRun.objects.create(period_year=2026, period_month=8, created_by=user), employee=employee, base_pay=3_100_000)
    after_birthday_month = OfficePayslip.objects.create(run=OfficePayrollRun.objects.create(period_year=2026, period_month=9, created_by=user), employee=employee, base_pay=3_100_000)

    birthday_month.apply_auto_deductions(policy)
    after_birthday_month.apply_auto_deductions(policy)

    assert birthday_month.auto_national_pension_eligible is True
    assert birthday_month.auto_national_pension == 147_250
    assert after_birthday_month.auto_national_pension_eligible is False
    assert after_birthday_month.auto_national_pension == 0


@pytest.mark.django_db
def test_fixed_meal_and_fuel_allowances_are_not_in_income_tax_base():
    user = get_user_model().objects.create_user(username="nontax-allowance-employee")
    employee = OfficeEmployeeProfile.objects.create(
        user=user,
        employee_no="HQ-NONTAX",
        tax_dependent_count=2,
        tax_withholding_ratio=120,
    )
    run = OfficePayrollRun.objects.create(period_year=2026, period_month=7, created_by=user)
    version = IncomeTaxTableVersion.objects.create(effective_from="2026-03-01", source_name="official.xlsx", is_active=True)
    IncomeTaxTableRow.objects.create(version=version, monthly_pay_from=0, monthly_pay_to=3_200_000, dependent_count=2, income_tax=65_400)
    slip = OfficePayslip.objects.create(
        run=run,
        employee=employee,
        base_pay=3_100_000,
        meal_allowance_pay=200_000,
        fuel_allowance_pay=100_000,
        site_allowance_pay=0,
    )

    slip.apply_auto_deductions(OfficePayrollDeductionPolicy.objects.create(year=2026))

    assert slip.gross_pay == 3_400_000
    assert slip.income_tax == 78_480


@pytest.mark.django_db
def test_child_tax_credit_is_deducted_before_withholding_ratio_and_snapshotted():
    user = get_user_model().objects.create_user(username="child-credit-employee")
    employee = OfficeEmployeeProfile.objects.create(
        user=user,
        employee_no="HQ-CHILD",
        tax_dependent_count=3,
        tax_child_count_8_to_20=3,
        tax_withholding_ratio=100,
    )
    run = OfficePayrollRun.objects.create(period_year=2026, period_month=8, created_by=user)
    version = IncomeTaxTableVersion.objects.create(
        effective_from="2026-03-01",
        source_name="official.xlsx",
        is_active=True,
        child_credit_two=29_160,
        child_credit_per_additional=25_000,
    )
    IncomeTaxTableRow.objects.create(
        version=version,
        monthly_pay_from=0,
        monthly_pay_to=10_000_000,
        dependent_count=3,
        income_tax=100_000,
    )
    policy = OfficePayrollDeductionPolicy.objects.create(year=2026)
    slip = OfficePayslip.objects.create(run=run, employee=employee, base_pay=3_000_000)

    slip.apply_auto_deductions(policy)
    slip.save()

    assert slip.income_tax == 45_840
    assert slip.auto_child_tax_credit == 54_160
    assert slip.auto_income_tax_table_version == version
    assert slip.auto_tax_child_count_8_to_20 == 3
