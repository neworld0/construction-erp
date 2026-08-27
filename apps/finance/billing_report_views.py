from datetime import date

from django.contrib import messages
from django.contrib.auth.decorators import login_required
from django.core.exceptions import PermissionDenied, ValidationError
from django.http import HttpResponse
from django.shortcuts import get_object_or_404, redirect, render
from django.utils import timezone

from apps.audit.services.logger import log_action
from apps.core.rbac.models import Role
from apps.core.rbac.permissions import (
    get_current_legal_entity,
    get_user_legal_entities,
    get_user_role,
    require_legal_entity_access,
    require_role,
)
from apps.finance.models import BillingReport, BillingReportStatus, BillingReportType, TaxInvoice
from apps.finance.services.billing_reports import (
    ATTACHMENT_FIELDS, COMPLETION_NOTE_FIELDS, PROGRESS_NOTE_FIELDS,
    build_billing_report_preview, create_billing_report, export_billing_report_excel,
    update_billing_report_content, review_billing_report, approve_billing_report,
    reject_billing_report, requires_ceo_billing_approval,
    record_owner_confirmation, issue_tax_invoice_and_recognize_revenue,
)
from apps.projects.models import Project


def _date(value):
    try: return date.fromisoformat(value)
    except (TypeError, ValueError): return None


def _report_for_user(request, report_id, *relations):
    queryset = BillingReport.objects.select_related("project", *relations)
    report = get_object_or_404(queryset, id=report_id)
    require_legal_entity_access(request.user, report.project.legal_entity, request=request)
    return report


@login_required
def hq_billing_report_list(request):
    require_role(request.user, [Role.HQ], request=request)
    legal_entity = get_current_legal_entity(request)
    if legal_entity is None:
        raise PermissionDenied("선택 가능한 법인이 없습니다.")
    reports = BillingReport.objects.select_related("project").filter(project__legal_entity=legal_entity)
    return render(request, "app/hq/billing_report_list.html", {"reports": reports, "current_legal_entity": legal_entity})


@login_required
def hq_billing_report_settlement_list(request):
    require_role(request.user, [Role.HQ], request=request)
    legal_entity = get_current_legal_entity(request)
    if legal_entity is None:
        raise PermissionDenied("선택 가능한 법인이 없습니다.")
    reports = (
        BillingReport.objects.select_related("project", "owner_confirmed_by")
        .filter(project__legal_entity=legal_entity, status__in=[BillingReportStatus.HQ_APPROVED, BillingReportStatus.LOCKED])
        .order_by("-billing_date", "-id")
    )
    return render(request, "app/hq/billing_report_settlement_list.html", {"reports": reports})


@login_required
def hq_billing_report_settlement_detail(request, report_id):
    require_role(request.user, [Role.HQ], request=request)
    report = _report_for_user(request, report_id, "owner_confirmed_by")
    tax_invoice = TaxInvoice.objects.filter(billing_report=report).first()
    return render(request, "app/hq/billing_report_settlement_detail.html", {"report": report, "tax_invoice": tax_invoice})


@login_required
def hq_billing_report_new(request, report_type):
    require_role(request.user, [Role.HQ], request=request)
    report_type = BillingReportType(report_type)
    legal_entity = get_current_legal_entity(request)
    if legal_entity is None:
        raise PermissionDenied("선택 가능한 법인이 없습니다.")
    project_id = request.POST.get("project_id") if request.method == "POST" else request.GET.get("project_id")
    projects = Project.objects.filter(legal_entity=legal_entity, is_active=True).order_by("name")
    project = projects.filter(id=project_id).first() if str(project_id).isdigit() else None
    billing_date = _date(request.POST.get("billing_date") if request.method == "POST" else request.GET.get("billing_date")) or timezone.localdate()
    preview = build_billing_report_preview(project, report_type=report_type, billing_date=billing_date) if project else None
    if request.method == "POST":
        try:
            report = create_billing_report(project=project, report_type=report_type, billing_date=billing_date, billing_round=int(request.POST.get("billing_round") or 1), actor=request.user, request=request)
            messages.success(request, "보고서 초안이 생성되었습니다. 엔지니어 작성사항을 입력해 주세요.")
            return redirect(f"/app/hq/billing/reports/{report.id}/")
        except (PermissionDenied, ValidationError, TypeError, ValueError) as exc:
            messages.error(request, str(exc))
    return render(request, "app/hq/billing_report_new.html", {"report_type": report_type, "projects": projects, "selected_project": project, "billing_date": billing_date, "preview": preview, "current_legal_entity": legal_entity})


@login_required
def hq_billing_report_detail(request, report_id):
    require_role(request.user, [Role.HQ], request=request)
    report = _report_for_user(request, report_id)
    fields = COMPLETION_NOTE_FIELDS if report.report_type == BillingReportType.COMPLETION else PROGRESS_NOTE_FIELDS
    if request.method == "POST":
        try:
            notes = {field: (request.POST.get(f"note_{field}") or "").strip() for field in fields}
            checklist = {field: request.POST.get(f"check_{field}") == "on" for field in ATTACHMENT_FIELDS}
            update_billing_report_content(report=report, notes=notes, checklist=checklist, actor=request.user, request=request)
            messages.success(request, "엔지니어 작성사항과 증빙 체크리스트를 저장했습니다.")
        except (PermissionDenied, ValidationError) as exc: messages.error(request, str(exc))
        return redirect(f"/app/hq/billing/reports/{report.id}/")
    return render(request, "app/hq/billing_report_detail.html", {"report": report, "note_fields": fields, "attachment_fields": ATTACHMENT_FIELDS, "requires_ceo_approval": requires_ceo_billing_approval(report), "tax_invoice": TaxInvoice.objects.filter(billing_report=report).first()})


@login_required
def hq_billing_report_review(request, report_id):
    require_role(request.user, [Role.HQ], request=request)
    report = _report_for_user(request, report_id)
    if request.method != "POST":
        return redirect(f"/app/hq/billing/reports/{report.id}/")
    try:
        review_billing_report(report=report, actor=request.user, request=request)
        messages.success(request, "CEO 결재 요청을 등록했습니다." if requires_ceo_billing_approval(report) else "HQ 검토를 완료하고 공식본으로 확정했습니다.")
    except (PermissionDenied, ValidationError) as exc:
        messages.error(request, str(exc))
    return redirect(f"/app/hq/billing/reports/{report.id}/")


@login_required
def hq_billing_report_owner_confirmation(request, report_id):
    require_role(request.user, [Role.HQ], request=request)
    report = _report_for_user(request, report_id)
    if request.method == "POST":
        try:
            record_owner_confirmation(
                report=report,
                confirmation_date=_date(request.POST.get("confirmation_date")),
                reference=request.POST.get("confirmation_reference"),
                note=request.POST.get("confirmation_note"),
                actor=request.user,
                request=request,
            )
            messages.success(request, "발주처 확정 통보를 등록했습니다. 세금계산서를 발행할 수 있습니다.")
        except (PermissionDenied, ValidationError) as exc:
            messages.error(request, str(exc))
    return redirect(f"/app/hq/billing/reports/{report.id}/settlement/")


@login_required
def hq_billing_report_tax_invoice_issue(request, report_id):
    require_role(request.user, [Role.HQ], request=request)
    report = _report_for_user(request, report_id)
    if request.method == "POST":
        try:
            invoice = issue_tax_invoice_and_recognize_revenue(
                report=report,
                invoice_number=request.POST.get("invoice_number"),
                supply_date=_date(request.POST.get("supply_date")),
                memo=request.POST.get("invoice_memo"),
                actor=request.user,
                request=request,
            )
            messages.success(request, f"세금계산서 {invoice.invoice_number}를 발행하고 공급일 기준 매출을 인식했습니다.")
        except (PermissionDenied, ValidationError) as exc:
            messages.error(request, str(exc))
    return redirect(f"/app/hq/billing/reports/{report.id}/")


@login_required
def hq_billing_report_export(request, report_id):
    require_role(request.user, [Role.HQ], request=request)
    report = _report_for_user(request, report_id)
    if report.status not in (BillingReportStatus.HQ_APPROVED, BillingReportStatus.LOCKED):
        messages.error(request, "HQ 확정 또는 CEO 승인·잠금된 보고서만 공식본으로 다운로드할 수 있습니다.")
        return redirect(f"/app/hq/billing/reports/{report.id}/")
    log_action(actor=request.user, action="BILLING_REPORT_EXPORTED", object_type="BillingReport", object_id=report.id, project=report.project, request=request, meta={"report_type": report.report_type})
    response = HttpResponse(export_billing_report_excel(report), content_type="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet")
    response["Content-Disposition"] = f'attachment; filename="billing-report-{report.id}.xlsx"'
    return response


@login_required
def ceo_billing_report_list(request):
    require_role(request.user, [Role.CEO, Role.HQ], request=request)
    status = request.GET.get("status") or BillingReportStatus.CEO_REVIEW
    reports = BillingReport.objects.select_related("project", "hq_reviewed_by", "ceo_approved_by").filter(
        project__legal_entity__in=get_user_legal_entities(request.user)
    ).order_by("-billing_date", "-id")
    if status != "all":
        reports = reports.filter(status=status)
    return render(request, "ceo/billing_report_list.html", {"reports": reports, "status": status, "ceo_read_only": get_user_role(request.user) != Role.CEO})


@login_required
def ceo_billing_report_detail(request, report_id):
    require_role(request.user, [Role.CEO, Role.HQ], request=request)
    report = _report_for_user(request, report_id, "hq_reviewed_by", "ceo_approved_by", "ceo_rejected_by")
    fields = COMPLETION_NOTE_FIELDS if report.report_type == BillingReportType.COMPLETION else PROGRESS_NOTE_FIELDS
    return render(request, "ceo/billing_report_detail.html", {"report": report, "note_fields": fields, "attachment_fields": ATTACHMENT_FIELDS, "ceo_read_only": get_user_role(request.user) != Role.CEO})


@login_required
def ceo_billing_report_approve(request, report_id):
    require_role(request.user, [Role.CEO], request=request)
    report = _report_for_user(request, report_id)
    if request.method == "POST":
        try:
            approve_billing_report(report=report, actor=request.user, request=request)
            messages.success(request, "CEO 승인과 잠금 처리가 완료되었습니다.")
        except (PermissionDenied, ValidationError) as exc:
            messages.error(request, str(exc))
    return redirect(f"/app/ceo/billing/reports/{report.id}/")


@login_required
def ceo_billing_report_reject(request, report_id):
    require_role(request.user, [Role.CEO], request=request)
    report = _report_for_user(request, report_id)
    if request.method == "POST":
        try:
            reject_billing_report(report=report, actor=request.user, reason=request.POST.get("reason"), request=request)
            messages.success(request, "보고서를 반려하고 HQ 재검토로 돌려보냈습니다.")
        except (PermissionDenied, ValidationError) as exc:
            messages.error(request, str(exc))
    return redirect(f"/app/ceo/billing/reports/{report.id}/")
