from __future__ import annotations

from copy import copy
from decimal import Decimal, ROUND_HALF_UP
from io import BytesIO
from pathlib import Path

from django.core.exceptions import PermissionDenied, ValidationError
from django.db import transaction
from django.utils import timezone

from apps.audit.services.logger import log_action
from apps.closing.guards import assert_month_open
from apps.closing.revenue_recognition import (
    get_approved_progress_percent,
    recognize_revenue_and_cost_for_close,
)
from apps.closing.reconciliation import build_project_reconciliation
from apps.core.rbac.models import Role
from apps.core.rbac.permissions import get_user_role, require_legal_entity_access
from apps.cost.models import RevenueRecognitionTrigger
from apps.finance.models import (
    AdvancePayment,
    BillingReport,
    BillingReportStatus,
    BillingReportType,
    OwnerConfirmationStatus,
    ProgressBilling,
    TaxInvoice,
)
from apps.finance.services.progress_billing import build_progress_billing_preview
from apps.projects.models import BudgetItem


PROGRESS_NOTE_FIELDS = ("금회 작업내용", "주요 시공 범위", "기성율 산정 사유", "현장 확인 의견", "검측 결과 요약", "품질시험 결과 요약", "안전관리 특이사항", "환경관리 특이사항", "설계변경/물량변경 여부", "미시공/부분시공 사유", "발주처·감리 협의사항", "사진대지 설명", "기타 비고")
COMPLETION_NOTE_FIELDS = ("준공 개요", "최종 시공내용", "준공 범위", "잔여공사 없음 확인", "최종 검측 결과", "품질시험 결과", "안전·환경관리 이행 결과", "하자보수/유지관리 유의사항", "발주처 확인사항", "준공사진 설명", "정산 제외/포함 항목", "기타 준공 특기사항")
ATTACHMENT_FIELDS = ("사진대지", "검측서", "품질시험성적서", "납품서·세금계산서", "발주처·감리 확인서")


def _hq(actor):
    if get_user_role(actor) != Role.HQ:
        raise PermissionDenied("HQ 사용자만 기성·준공 보고서를 관리할 수 있습니다.")


def _hq_for_project(actor, project):
    _hq(actor)
    require_legal_entity_access(actor, project.legal_entity)


def _ceo_for_project(actor, project):
    if get_user_role(actor) != Role.CEO:
        raise PermissionDenied("CEO 사용자만 기성·준공 보고서를 승인할 수 있습니다.")
    require_legal_entity_access(actor, project.legal_entity)


def requires_ceo_billing_approval(report) -> bool:
    return report.report_type == BillingReportType.COMPLETION or bool(
        getattr(report.project, "requires_ceo_billing_approval", False)
    )


def _check_report_evidence(report):
    missing = [field for field in ATTACHMENT_FIELDS if not report.attachment_checklist.get(field)]
    if missing:
        raise ValidationError("CEO 결재 요청 전 증빙 체크리스트를 모두 확인해 주세요: " + ", ".join(missing))


def review_billing_report(*, report, actor, request=None):
    _hq_for_project(actor, report.project)
    if report.status not in (BillingReportStatus.ENGINEER_INPUT_REQUIRED, BillingReportStatus.REJECTED):
        raise ValidationError("HQ 검토를 요청할 수 없는 보고서 상태입니다.")
    _check_report_evidence(report)
    report.hq_reviewed_by = actor
    report.hq_reviewed_at = timezone.now()
    report.reject_reason = ""
    report.ceo_rejected_by = None
    report.ceo_rejected_at = None
    report.status = BillingReportStatus.CEO_REVIEW if requires_ceo_billing_approval(report) else BillingReportStatus.HQ_APPROVED
    report.save(update_fields=["hq_reviewed_by", "hq_reviewed_at", "reject_reason", "ceo_rejected_by", "ceo_rejected_at", "status", "updated_at"])
    log_action(actor=actor, action="BILLING_REPORT_HQ_REVIEWED", object_type="BillingReport", object_id=report.id, project=report.project, request=request, meta={"requires_ceo_approval": requires_ceo_billing_approval(report), "billing_round": report.billing_round})
    return report


def approve_billing_report(*, report, actor, request=None):
    _ceo_for_project(actor, report.project)
    if report.status != BillingReportStatus.CEO_REVIEW:
        raise ValidationError("CEO 승인 대기 상태의 보고서만 승인할 수 있습니다.")
    report.status = BillingReportStatus.LOCKED
    report.ceo_approved_by = actor
    report.ceo_approved_at = timezone.now()
    report.locked_at = report.ceo_approved_at
    report.save(update_fields=["status", "ceo_approved_by", "ceo_approved_at", "locked_at", "updated_at"])
    log_action(actor=actor, action="BILLING_REPORT_CEO_APPROVED_LOCKED", object_type="BillingReport", object_id=report.id, project=report.project, request=request, meta={"billing_round": report.billing_round, "net_claim_amount": str(report.net_claim_amount)})
    return report


def reject_billing_report(*, report, actor, reason, request=None):
    _ceo_for_project(actor, report.project)
    if report.status != BillingReportStatus.CEO_REVIEW:
        raise ValidationError("CEO 승인 대기 상태의 보고서만 반려할 수 있습니다.")
    reason = (reason or "").strip()
    if not reason:
        raise ValidationError("반려 사유를 입력해 주세요.")
    report.status = BillingReportStatus.REJECTED
    report.ceo_rejected_by = actor
    report.ceo_rejected_at = timezone.now()
    report.reject_reason = reason
    report.save(update_fields=["status", "ceo_rejected_by", "ceo_rejected_at", "reject_reason", "updated_at"])
    log_action(actor=actor, action="BILLING_REPORT_CEO_REJECTED", object_type="BillingReport", object_id=report.id, project=report.project, request=request, meta={"billing_round": report.billing_round, "reason": reason})
    return report


def record_owner_confirmation(*, report, confirmation_date, reference, actor, note="", request=None):
    """Record the owner's formal confirmation before any tax invoice is issued."""
    _hq_for_project(actor, report.project)
    if report.status not in (BillingReportStatus.HQ_APPROVED, BillingReportStatus.LOCKED):
        raise ValidationError("HQ 확정 또는 CEO 승인·잠금된 보고서만 발주처 확정 통보를 등록할 수 있습니다.")
    if TaxInvoice.objects.filter(billing_report=report).exists():
        raise ValidationError("세금계산서가 이미 발행되어 발주처 확정 통보를 변경할 수 없습니다.")
    reference = (reference or "").strip()
    if confirmation_date is None or not reference:
        raise ValidationError("발주처 확정 통보일과 공문·통보번호를 입력해 주세요.")
    report.owner_confirmation_status = OwnerConfirmationStatus.CONFIRMED
    report.owner_confirmation_date = confirmation_date
    report.owner_confirmation_reference = reference
    report.owner_confirmation_note = (note or "").strip()
    report.owner_confirmed_by = actor
    report.owner_confirmed_at = timezone.now()
    report.save(
        update_fields=[
            "owner_confirmation_status",
            "owner_confirmation_date",
            "owner_confirmation_reference",
            "owner_confirmation_note",
            "owner_confirmed_by",
            "owner_confirmed_at",
            "updated_at",
        ]
    )
    log_action(
        actor=actor,
        action="BILLING_REPORT_OWNER_CONFIRMATION_RECORDED",
        object_type="BillingReport",
        object_id=report.id,
        project=report.project,
        request=request,
        meta={"confirmation_date": confirmation_date.isoformat(), "reference": reference},
    )
    return report


def issue_tax_invoice_and_recognize_revenue(*, report, invoice_number, supply_date, actor, memo="", request=None):
    """Issue an owner-confirmed tax invoice and create its same-day revenue snapshot."""
    _hq_for_project(actor, report.project)
    if report.owner_confirmation_status != OwnerConfirmationStatus.CONFIRMED:
        raise ValidationError("발주처의 기성·준공 확정 통보를 먼저 등록해 주세요.")
    if TaxInvoice.objects.filter(billing_report=report).exists():
        raise ValidationError("이 보고서의 세금계산서는 이미 발행되었습니다.")
    invoice_number = (invoice_number or "").strip()
    if supply_date is None or not invoice_number:
        raise ValidationError("세금계산서 번호와 공급일을 입력해 주세요.")
    if supply_date < report.owner_confirmation_date:
        raise ValidationError("세금계산서 공급일은 발주처 확정 통보일보다 빠를 수 없습니다.")
    assert_month_open(
        supply_date,
        legal_entity=report.project.legal_entity,
        message_context="세금계산서 공급일입니다.",
        exc=PermissionDenied,
    )
    billing_total = Decimal(report.current_gross_billing_amount)
    supply_amount = (billing_total / Decimal("1.10")).quantize(Decimal("0.01"))
    tax_amount = billing_total - supply_amount
    with transaction.atomic():
        invoice = TaxInvoice.objects.create(
            billing_report=report,
            invoice_number=invoice_number,
            supply_date=supply_date,
            supply_amount=supply_amount,
            tax_amount=tax_amount,
            issued_by=actor,
            memo=(memo or "").strip(),
        )
        snapshot = recognize_revenue_and_cost_for_close(
            project=report.project,
            close_date=supply_date,
            trigger_type=RevenueRecognitionTrigger.TAX_INVOICE,
            actor=actor,
            memo=f"세금계산서 {invoice.invoice_number}",
            request=request,
        )
        log_action(
            actor=actor,
            action="TAX_INVOICE_ISSUED_REVENUE_RECOGNIZED",
            object_type="TaxInvoice",
            object_id=invoice.id,
            project=report.project,
            request=request,
            meta={
                "billing_report_id": report.id,
                "invoice_number": invoice.invoice_number,
                "supply_date": supply_date.isoformat(),
                "supply_amount": str(supply_amount),
                "tax_amount": str(tax_amount),
                "revenue_recognition_close_id": snapshot.id,
            },
        )
    return invoice


def build_billing_report_preview(project, *, report_type, billing_date):
    preview = build_progress_billing_preview(project, billing_date=billing_date)
    approved_progress = get_approved_progress_percent(project, billing_date)
    if report_type == BillingReportType.COMPLETION and approved_progress != Decimal("100"):
        preview["blocks"] = list(preview["blocks"]) + ["준공 보고서는 승인 진행률 100%에서만 생성할 수 있습니다."]
        preview["ready"] = False
    existing = ProgressBilling.objects.filter(project=project, billing_date=billing_date).first()
    if existing:
        preview.update({
            "approved_progress_percent": existing.approved_progress_percent,
            "contract_amount": existing.contract_amount_snapshot,
            "previously_billed_amount": existing.previously_billed_amount,
            "gross_claim_amount": existing.gross_claim_amount,
            "cumulative_earned_amount": existing.cumulative_earned_amount,
            "advance_deduction_amount": existing.advance_deduction_amount,
            "advance_balance_after": existing.advance_balance_after,
            "net_claim_amount": existing.net_claim_amount,
        })
        preview["blocks"] = [block for block in preview["blocks"] if "기성청구가 이미" not in block]
        preview["ready"] = not preview["blocks"]
    preview["remaining_billing_amount"] = Decimal(preview["contract_amount"]) - Decimal(preview["cumulative_earned_amount"])
    advance = AdvancePayment.objects.filter(project=project).first()
    preview["advance_received_amount"] = Decimal(advance.received_amount) if advance else Decimal("0")
    preview["previous_advance_deduction"] = Decimal(preview["cumulative_advance_deduction"]) - Decimal(preview["advance_deduction_amount"])
    return preview


def create_billing_report(*, project, report_type, billing_date, billing_round, actor, request=None):
    if project is None:
        raise ValidationError("프로젝트를 선택해 주세요.")
    _hq_for_project(actor, project)
    if BillingReport.objects.filter(project=project, report_type=report_type, billing_round=billing_round).exists():
        raise ValidationError("동일 프로젝트·보고 차수의 보고서가 이미 있습니다.")
    if report_type == BillingReportType.COMPLETION:
        reconciliation = build_project_reconciliation(
            project=project, as_of_date=billing_date, require_completion=True
        )
        if not reconciliation["ready"]:
            raise ValidationError(
                "준공 청구가 차단되었습니다. 준공·월마감 대사에서 확인해 주세요: "
                + reconciliation["blocking_issues"][0]
            )
    preview = build_billing_report_preview(project, report_type=report_type, billing_date=billing_date)
    if not preview["ready"]:
        raise ValidationError(preview["blocks"][0])
    fields = COMPLETION_NOTE_FIELDS if report_type == BillingReportType.COMPLETION else PROGRESS_NOTE_FIELDS
    with transaction.atomic():
        report = BillingReport.objects.create(
            project=project, report_type=report_type, billing_round=billing_round, billing_date=billing_date,
            approved_progress_percent=preview["approved_progress_percent"], contract_amount_snapshot=preview["contract_amount"],
            previous_billing_amount=preview["previously_billed_amount"], current_gross_billing_amount=preview["gross_claim_amount"],
            cumulative_billing_amount=preview["cumulative_earned_amount"], remaining_billing_amount=preview["remaining_billing_amount"],
            advance_received_amount=preview["advance_received_amount"], previous_advance_deduction=preview["previous_advance_deduction"],
            current_advance_deduction=preview["advance_deduction_amount"], remaining_advance_balance=preview["advance_balance_after"],
            net_claim_amount=preview["net_claim_amount"], status=BillingReportStatus.ENGINEER_INPUT_REQUIRED,
            engineer_notes={field: "" for field in fields}, attachment_checklist={field: False for field in ATTACHMENT_FIELDS}, generated_by=actor,
        )
        log_action(actor=actor, action="BILLING_REPORT_CREATED", object_type="BillingReport", object_id=report.id, project=project, request=request, meta={"report_type": report_type, "billing_round": billing_round, "net_claim_amount": str(report.net_claim_amount)})
        return report


def update_billing_report_content(*, report, notes, checklist, actor, request=None):
    _hq_for_project(actor, report.project)
    if report.status in (BillingReportStatus.HQ_APPROVED, BillingReportStatus.CEO_REVIEW, BillingReportStatus.LOCKED):
        raise ValidationError("승인 또는 잠금된 보고서는 정정 절차 없이 수정할 수 없습니다.")
    report.engineer_notes = notes
    report.attachment_checklist = checklist
    report.save(update_fields=["engineer_notes", "attachment_checklist", "updated_at"])
    log_action(actor=actor, action="BILLING_REPORT_ENGINEER_NOTE_UPDATED", object_type="BillingReport", object_id=report.id, project=report.project, request=request, meta={"report_type": report.report_type})
    return report


def _allocate_report_amount(items, total_amount):
    """Allocate a report total across contract lines and keep the rounded sum exact."""
    total_amount = Decimal(total_amount or 0)
    weights = [Decimal(item.planned_amount or 0) for item in items]
    weight_total = sum(weights, Decimal("0"))
    if not items or weight_total <= 0:
        return [Decimal("0") for _item in items]

    allocated = []
    remaining = total_amount
    for index, weight in enumerate(weights):
        if index == len(weights) - 1:
            amount = remaining
        else:
            amount = (total_amount * weight / weight_total).quantize(
                Decimal("1"), rounding=ROUND_HALF_UP
            )
            remaining -= amount
        allocated.append(amount)
    return allocated


def _billing_line_rows(report):
    """Return immutable amounts aggregated by the displayed cost account name."""
    items = list(
        BudgetItem.objects.filter(project=report.project)
        .select_related("cost_item")
        .order_by("id")
    )
    previous = _allocate_report_amount(items, report.previous_billing_amount)
    current = _allocate_report_amount(items, report.current_gross_billing_amount)
    cumulative = _allocate_report_amount(items, report.cumulative_billing_amount)
    grouped = {}
    for item, previous_amount, current_amount, cumulative_amount in zip(
        items, previous, current, cumulative
    ):
        planned = Decimal(item.planned_amount or 0)
        name = item.name or item.cost_item.name
        row = grouped.setdefault(
            name,
            {"name": name, "planned": Decimal("0"), "previous": Decimal("0"), "current": Decimal("0"), "cumulative": Decimal("0"), "remaining": Decimal("0")},
        )
        row["planned"] += planned
        row["previous"] += previous_amount
        row["current"] += current_amount
        row["cumulative"] += cumulative_amount
        row["remaining"] += planned - cumulative_amount
    return list(grouped.values())


def export_billing_report_excel(report):
    """Create the downloadable report using the office's standard bill-of-work style.

    The data in a report remains the immutable snapshot held by ``BillingReport``.
    The sample workbook is used only as a visual reference (print setup, fonts,
    borders and alignment); it is never used as a source of report data.
    """
    from openpyxl import Workbook, load_workbook
    from openpyxl.styles import Alignment, Border, Font, PatternFill, Side

    template_path = Path(__file__).resolve().parents[3] / "sample_files" / "제1회 기성내역서(토목).xlsx"
    reference_sheet = None
    if template_path.exists():
        # The third worksheet is the bill-of-work sheet in the approved civil
        # template.  Index-based lookup avoids relying on a user-renamable tab.
        reference_workbook = load_workbook(template_path, read_only=False, data_only=False)
        if len(reference_workbook.worksheets) > 2:
            reference_sheet = reference_workbook.worksheets[2]

    thin = Side(style="thin", color="000000")
    fallback_header = {
        "font": Font(name="맑은 고딕", bold=True, size=10),
        "fill": PatternFill("solid", fgColor="D9EAD3"),
        "alignment": Alignment(horizontal="center", vertical="center", wrap_text=True),
        "border": Border(left=thin, right=thin, top=thin, bottom=thin),
    }
    fallback_body = {
        "font": Font(name="맑은 고딕", size=10),
        "alignment": Alignment(vertical="center", wrap_text=True),
        "border": Border(left=thin, right=thin, top=thin, bottom=thin),
    }

    def apply_style(target, reference_cell=None, fallback=None):
        """Copy complete visual style without copying a reference value/formula."""
        if reference_cell is not None:
            # A StyleArray belongs to the source workbook's style table, so
            # assigning ``_style`` directly makes the generated workbook point
            # at invalid style indexes.  Copy each public component instead.
            target.font = copy(reference_cell.font)
            target.fill = copy(reference_cell.fill)
            target.border = copy(reference_cell.border)
            target.alignment = copy(reference_cell.alignment)
            target.protection = copy(reference_cell.protection)
            target.number_format = reference_cell.number_format
        elif fallback:
            target.font = copy(fallback["font"])
            target.alignment = copy(fallback["alignment"])
            target.border = copy(fallback["border"])
            if "fill" in fallback:
                target.fill = copy(fallback["fill"])

    title_style = reference_sheet["A1"] if reference_sheet else None
    header_style = reference_sheet["A2"] if reference_sheet else None
    subheader_style = reference_sheet["A3"] if reference_sheet else None
    body_style = reference_sheet["A14"] if reference_sheet else None
    total_style = reference_sheet["A9"] if reference_sheet else None

    def setup_sheet(sheet, title, columns, *, landscape=True):
        sheet.sheet_view.showGridLines = False
        if reference_sheet:
            sheet.page_margins = copy(reference_sheet.page_margins)
            sheet.page_setup.paperSize = reference_sheet.page_setup.paperSize
            sheet.page_setup.orientation = reference_sheet.page_setup.orientation if landscape else "portrait"
        else:
            sheet.page_setup.paperSize = sheet.PAPERSIZE_A4
            sheet.page_setup.orientation = "landscape" if landscape else "portrait"
        sheet.page_setup.fitToWidth = 1
        sheet.page_setup.fitToHeight = 0
        sheet.sheet_properties.pageSetUpPr.fitToPage = True
        sheet.merge_cells(start_row=1, start_column=1, end_row=1, end_column=columns)
        cell = sheet.cell(1, 1, title)
        apply_style(cell, title_style, fallback_header)
        title_font = copy(cell.font)
        title_font.bold = True
        title_font.sz = max(title_font.sz or 0, 16)
        cell.font = title_font
        cell.alignment = Alignment(horizontal="center", vertical="center")
        sheet.row_dimensions[1].height = 28
        sheet.freeze_panes = "A4"

    def write_table_header(sheet, row, values):
        for column, value in enumerate(values, 1):
            cell = sheet.cell(row, column, value)
            apply_style(cell, header_style if row == 3 else subheader_style, fallback_header)
            cell.alignment = Alignment(horizontal="center", vertical="center", wrap_text=True)
        sheet.row_dimensions[row].height = 30

    def write_data_row(sheet, row, values, *, total=False):
        for column, value in enumerate(values, 1):
            cell = sheet.cell(row, column, value)
            apply_style(cell, total_style if total else body_style, fallback_body)
            if isinstance(value, Decimal) or isinstance(value, (int, float)):
                cell.number_format = "#,##0"
                cell.alignment = Alignment(horizontal="right", vertical="center")
        sheet.row_dimensions[row].height = 20

    def set_widths(sheet, widths):
        for column, width in enumerate(widths, 1):
            sheet.column_dimensions[chr(64 + column)].width = width

    wb = Workbook()
    cover = wb.active
    cover.title = "갑지"
    setup_sheet(cover, "기성 보고서" if report.report_type == BillingReportType.PROGRESS else "준공 보고서", 2, landscape=False)
    write_table_header(cover, 3, ["구분", "내용"])
    rows = [("공사명", report.project.name), ("프로젝트 코드", report.project.code), ("보고 차수", report.billing_round), ("기준일", report.billing_date), ("도급금액", report.contract_amount_snapshot), ("전회기성", report.previous_billing_amount), ("금회기성", report.current_gross_billing_amount), ("누계기성", report.cumulative_billing_amount), ("미기성", report.remaining_billing_amount), ("승인 진행률", report.approved_progress_percent / Decimal("100"))]
    for row_number, row in enumerate(rows, 4):
        write_data_row(cover, row_number, row)
    cover["B13"].number_format = "0.0%"
    set_widths(cover, [26, 42])

    billing_lines = _billing_line_rows(report)

    cost = wb.create_sheet("원가계산서")
    setup_sheet(cost, "기성 원가계산서", 5)
    write_table_header(cost, 3, ["비목", "도급금액", "전회기성", "금회기성", "누계기성"])
    for row_number, item in enumerate(billing_lines, 4):
        write_data_row(cost, row_number, [item["name"], item["planned"], item["previous"], item["current"], item["cumulative"]])
    set_widths(cost, [34, 18, 18, 18, 18])

    detail = wb.create_sheet("내역서")
    setup_sheet(detail, f"제{report.billing_round}회 기성내역서", 6)
    write_table_header(detail, 3, ["공종명", "도급금액", "전회기성", "금회기성", "누계기성", "미기성"])
    for row_number, item in enumerate(billing_lines, 4):
        write_data_row(detail, row_number, [item["name"], item["planned"], item["previous"], item["current"], item["cumulative"], item["remaining"]])
    set_widths(detail, [34, 18, 18, 18, 18, 18])

    advance = wb.create_sheet("선급금정산")
    setup_sheet(advance, "선급금 정산서", 2, landscape=False)
    write_table_header(advance, 3, ["구분", "금액"])
    for row_number, row in enumerate([("계약금액", report.contract_amount_snapshot), ("선급금 수령액", report.advance_received_amount), ("전회 선금공제", report.previous_advance_deduction), ("금회 선금공제", report.current_advance_deduction), ("선급금 잔액", report.remaining_advance_balance), ("선금정산 후 청구금액", report.net_claim_amount)], 4):
        write_data_row(advance, row_number, row, total=row_number == 9)
    set_widths(advance, [30, 30])

    notes = wb.create_sheet("엔지니어작성사항")
    setup_sheet(notes, "엔지니어 작성사항", 2, landscape=False)
    write_table_header(notes, 3, ["항목", "내용"])
    for row_number, (key, value) in enumerate(report.engineer_notes.items(), 4):
        write_data_row(notes, row_number, [key, value])
    set_widths(notes, [30, 70])

    checklist = wb.create_sheet("증빙체크리스트")
    setup_sheet(checklist, "증빙 체크리스트", 2, landscape=False)
    write_table_header(checklist, 3, ["증빙", "확인"])
    for row_number, (key, value) in enumerate(report.attachment_checklist.items(), 4):
        write_data_row(checklist, row_number, [key, "확인" if value else "미확인"])
    set_widths(checklist, [44, 18])

    buffer = BytesIO()
    wb.save(buffer)
    return buffer.getvalue()
