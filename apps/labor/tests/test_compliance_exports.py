from datetime import date

import pytest
from django.contrib.auth import get_user_model
from openpyxl import load_workbook

from apps.closing.models import ClosingPeriod, ClosingStatus
from apps.core.rbac.models import Role, UserProfile
from apps.labor.models import LaborComplianceExportType, LaborRole, Timesheet, TimesheetLine, TimesheetStatus, WorkerMaster
from apps.labor.services import generate_labor_compliance_export
from apps.projects.models import Project


@pytest.mark.django_db
def test_closed_month_generates_both_labor_compliance_workbooks(settings, tmp_path):
    settings.MEDIA_ROOT = tmp_path / "media"
    user = get_user_model().objects.create_user(username="hq-compliance", password="pass")
    UserProfile.objects.create(user=user, role=Role.HQ)
    project = Project.objects.create(code="COMP-001", name="노무 신고 검증 현장")
    role = LaborRole.objects.create(code="701", name="보통인부", is_active=True)
    worker = WorkerMaster(name="홍길동", comwel_job_code="701", active=True, default_labor_role=role)
    worker.set_rrn("900101-1234567")
    worker.set_account_number("123-456-7890")
    worker.save()
    sheet = Timesheet.objects.create(sheet_no="TS-COMP-001", project=project, work_date=date(2026, 8, 14), status=TimesheetStatus.APPROVED, created_by=user)
    TimesheetLine.objects.create(timesheet=sheet, worker=worker, labor_role=role, headcount=1, hours=8, rate_type="DAY", unit_rate=200000, amount=200000)
    ClosingPeriod.objects.create(year=2026, month=8, status=ClosingStatus.CLOSED)

    confirmation = generate_labor_compliance_export(project=project, year=2026, month=8, export_type=LaborComplianceExportType.WORK_CONFIRMATION, actor=user)
    payment = generate_labor_compliance_export(project=project, year=2026, month=8, export_type=LaborComplianceExportType.DAILY_WAGE_STATEMENT, actor=user)

    assert confirmation.generated_file.name.endswith(".xlsx")
    assert payment.generated_file.name.endswith(".xlsx")
    assert confirmation.source_summary["approved_daily_rows"] == 1
    assert payment.source_summary["rates"]["employment_employee_rate"] == "0.009"
    payment.generated_file.open("rb")
    workbook = load_workbook(payment.generated_file, data_only=False)
    statement = workbook["8월"]
    assert statement["A1"].value == "일용 노무비 지급 명세서 (2026년 08월)"
    assert statement["C4"].value == "주민번호"
    assert statement["E4"].value == "주소"
    assert statement["C5"].value == "연락처"
    assert statement["E5"].value == "은행명"
    assert statement["G5"].value == "계좌번호"
    assert statement["AB4"].value == "소득세"
    assert statement["AC4"].value == "건강보험"
    assert statement["AD4"].value == "국민연금"
    assert statement["AE4"].value == "공제소계"
    assert statement["AB5"].value == "지방소득세"
    assert statement["AC5"].value == "노인장기"
    assert statement["AD5"].value == "고용보험"
    assert statement["AE5"].value == "기타"
    assert statement["AA2"].value == "청구금액"
    assert statement["AB2"].value == "소득세+지방소득세"
    assert statement["AC2"].value == "건강보험+노인장기"
    assert statement["AD2"].value == "국민연금+고용보험"
    assert statement["AE2"].value == "공제계"
    assert statement["AF2"].value == "실 지급액"
    assert statement["AA6"].value == 200000
    assert statement["AF6"].value == 196720
    assert statement["AA8"].value == "=SUM(AA6)"
    assert "C6:D6" in {str(item) for item in statement.merged_cells.ranges}
    assert "E6:H6" in {str(item) for item in statement.merged_cells.ranges}
    assert "G7:H7" in {str(item) for item in statement.merged_cells.ranges}
    assert "A8:H9" in {str(item) for item in statement.merged_cells.ranges}
