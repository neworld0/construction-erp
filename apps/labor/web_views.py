import logging
from datetime import date
from decimal import Decimal, InvalidOperation

from django.contrib import messages
from django.contrib.auth.decorators import login_required
from django.core.exceptions import PermissionDenied, ValidationError
from django.http import FileResponse, Http404, JsonResponse
from django.db import models, transaction
from django.db.models import Q
from django.shortcuts import get_object_or_404, redirect, render
from django.utils import timezone

from apps.evidence.attachment_policy import can_edit_attachments
from apps.evidence.models import Evidence
from apps.evidence.services.resolve import is_project_or_month_locked
from apps.core.rbac.models import LegalEntity, ProjectAssignment, Role, UserProfile
from apps.core.rbac.permissions import get_current_legal_entity, get_user_legal_entities, get_user_role, require_legal_entity_access, require_project_access, require_role
from apps.cost.models import CostItem
from apps.projects.models import Project
from apps.audit.services.logger import log_action

from .forms import (
    ElectronicCardImportBatchFilterForm,
    ElectronicCardImportBatchUploadForm,
    LaborRateForm,
    LaborRoleForm,
    PayrollBatchForm,
    WorkerMasterForm,
    LaborWorkLedgerForm,
)
from .models import (
    ElectronicCardImportBatch,
    ElectronicCardImportBatchStatus,
    ElectronicCardWorkDay,
    ElectronicCardWorkRaw,
    LaborExcelExportBatch,
    LaborComplianceExport,
    LaborComplianceExportType,
    LaborConfirmedWorkDay,
    LaborConfirmedWorkSourceBasis,
    LaborReconciliationResult,
    LaborReconciliationStatus,
    LaborMonthlyPayroll,
    LaborMonthlyPayrollPaymentStatus,
    LaborWorkLedger,
    LaborWorkLedgerStatus,
    LaborRateTable,
    LaborRole,
    PayrollAllocationBatch,
    PayrollAllocationLine,
    PayrollAllocationStatus,
    OfficeEmployeeProfile,
    OfficeEmployeeNumberSequence,
    OfficePayrollDeductionPolicy,
    IncomeTaxTableVersion,
    OfficePayrollCorrection,
    OfficePayrollCorrectionStatus,
    OfficePayrollRun,
    OfficePayrollStatus,
    OfficePayslip,
    Timesheet,
    TimesheetStatus,
    WorkerMaster,
)
from .services import (
    approve_timesheet,
    create_electronic_card_import_batch,
    confirm_electronic_card_reconciliation_batch,
    delete_or_deactivate_worker_master,
    generate_cwma_card_reupload_excel,
    generate_labor_monthly_payroll,
    bulk_resolve_labor_reconciliation_results,
    match_reconciliation_worker,
    create_labor_role,
    create_labor_work_ledger,
    create_rate,
    create_timesheet,
    get_timesheet_workflow_state,
    create_payroll_batch,
    create_worker_master,
    reject_timesheet,
    submit_timesheet,
    parse_electronic_card_import_batch,
    reconcile_electronic_card_import_batch,
    register_labor_excel_export_download,
    generate_labor_compliance_export,
    register_labor_compliance_export_download,
    resolve_labor_reconciliation_result,
    update_labor_role,
    update_labor_reporting_project,
    update_labor_work_ledger,
    get_rate_scope,
    update_rate,
    update_worker_master,
    upsert_timesheet_lines,
    submit_payroll_batch,
    update_payroll_batch,
    upsert_payroll_lines,
    validate_payroll_batch,
)

logger = logging.getLogger(__name__)


@login_required
def hq_e_card_import_batch_list(request):
    require_role(request.user, [Role.HQ, Role.CEO], request=request)

    filter_form = ElectronicCardImportBatchFilterForm(request.GET or None)
    upload_form = ElectronicCardImportBatchUploadForm()
    if request.method == "POST":
        action = (request.POST.get("action") or "upload").strip().lower()
        if action == "parse":
            batch_id = request.POST.get("batch_id")
            batch = get_object_or_404(ElectronicCardImportBatch, id=batch_id)
            try:
                parse_electronic_card_import_batch(batch, request.user)
                messages.success(request, "전자카드 파일을 파싱했습니다.")
                return redirect("/app/hq/labor/e-card-imports/")
            except ValidationError as exc:
                messages.error(request, str(exc))
        elif action == "reconcile":
            batch_id = request.POST.get("batch_id")
            batch = get_object_or_404(ElectronicCardImportBatch, id=batch_id)
            try:
                reconcile_electronic_card_import_batch(batch, request.user)
                messages.success(request, "전자카드와 ERP 출역 대사를 완료했습니다.")
                return redirect("/app/hq/labor/e-card-imports/")
            except ValidationError as exc:
                messages.error(request, str(exc))
        else:
            upload_form = ElectronicCardImportBatchUploadForm(request.POST, request.FILES)
            if upload_form.is_valid():
                try:
                    create_electronic_card_import_batch(
                        upload_form.cleaned_data,
                        request.FILES["source_file"],
                        request.user,
                    )
                    messages.success(request, "전자카드 업로드 배치가 등록되었습니다.")
                    return redirect("/app/hq/labor/e-card-imports/")
                except ValidationError as exc:
                    if hasattr(exc, "message_dict"):
                        for field_name, errors in exc.message_dict.items():
                            for error in errors:
                                upload_form.add_error(field_name, error)
                    else:
                        upload_form.add_error(None, str(exc))
                    messages.error(request, "업로드 입력값을 확인해 주세요.")
            else:
                messages.error(request, "업로드 입력값을 확인해 주세요.")

    batches = ElectronicCardImportBatch.objects.select_related(
        "project", "uploaded_by"
    ).order_by("-uploaded_at", "-id")
    if filter_form.is_valid():
        month = (filter_form.cleaned_data.get("month") or "").strip()
        project = filter_form.cleaned_data.get("project")
        status = filter_form.cleaned_data.get("status") or ""
        if month:
            try:
                year, month_no = month.split("-", 1)
                batches = batches.filter(year_month__year=int(year), year_month__month=int(month_no))
            except ValueError:
                messages.error(request, "월 필터 형식은 YYYY-MM 이어야 합니다.")
        if project:
            batches = batches.filter(project=project)
        if status:
            batches = batches.filter(status=status)

    # Counting three reverse relations in one annotated query creates a
    # raw_rows x day_rows x reconciliation_results join per batch. Limit the
    # list first, then attach the same display counts from grouped queries.
    batches = list(batches[:50])
    batch_ids = [batch.id for batch in batches]
    counts_by_relation = {
        "raw_count": ElectronicCardWorkRaw.objects.filter(batch_id__in=batch_ids)
        .values("batch_id")
        .annotate(count=models.Count("id")),
        "day_count": ElectronicCardWorkDay.objects.filter(batch_id__in=batch_ids)
        .values("batch_id")
        .annotate(count=models.Count("id")),
        "reconciliation_count": LaborReconciliationResult.objects.filter(
            batch_id__in=batch_ids
        )
        .values("batch_id")
        .annotate(count=models.Count("id")),
    }
    for attribute, relation_counts in counts_by_relation.items():
        count_by_batch_id = {
            row["batch_id"]: row["count"] for row in relation_counts
        }
        for batch in batches:
            setattr(batch, attribute, count_by_batch_id.get(batch.id, 0))

    return render(
        request,
        "app/hq/e_card_imports.html",
        {
            "upload_form": upload_form,
            "filter_form": filter_form,
            "batches": batches,
            "status_choices": ElectronicCardImportBatchStatus.choices,
        },
    )


def _build_e_card_detail_redirect(batch_id, request):
    query = (request.POST.get("next_query") or request.GET.urlencode() or "").strip()
    base = f"/app/hq/labor/e-card-imports/{batch_id}/"
    return f"{base}?{query}" if query else base


def _filter_reconciliation_results(request, batch):
    status = (request.GET.get("status") or "").strip()
    resolution = (request.GET.get("resolution") or "").strip()
    worker_id = (request.GET.get("worker") or "").strip()
    only_unresolved = (request.GET.get("only_unresolved") or "").strip()
    q = (request.GET.get("q") or "").strip()

    qs = (
        batch.reconciliation_results.select_related(
            "worker",
            "card_day__raw",
            "resolved_by",
        )
        .order_by("work_date", "id")
    )
    if status:
        qs = qs.filter(status=status)
    if resolution:
        qs = qs.filter(resolution=resolution)
    if worker_id:
        qs = qs.filter(worker_id=worker_id)
    if only_unresolved == "1":
        qs = qs.filter(
            status__in=[
                LaborReconciliationStatus.ERP_ONLY,
                LaborReconciliationStatus.CARD_ONLY,
                LaborReconciliationStatus.DIFF,
                LaborReconciliationStatus.UNMATCHED,
            ],
            resolution="",
            final_work_unit__isnull=True,
        )
    if q:
        qs = qs.filter(
            Q(worker__name__icontains=q)
            | Q(card_day__raw__worker_name_raw__icontains=q)
            | Q(card_day__raw__phone__icontains=q)
            | Q(card_day__raw__rrn_masked__icontains=q)
        )
    return qs, {
        "status": status,
        "resolution": resolution,
        "worker_id": worker_id,
        "only_unresolved": only_unresolved,
        "q": q,
    }


@login_required
def hq_e_card_import_batch_detail(request, batch_id):
    require_role(request.user, [Role.HQ, Role.CEO], request=request)
    batch = get_object_or_404(
        ElectronicCardImportBatch.objects.select_related("project", "uploaded_by", "confirmed_by"),
        id=batch_id,
    )

    if request.method == "POST":
        try:
            if request.POST.get("resolve_result_id"):
                result_id = request.POST.get("resolve_result_id")
                action = request.POST.get(f"row_resolution__{result_id}")
                comment = request.POST.get(f"row_comment__{result_id}") or ""
                final_work_unit = request.POST.get(f"row_final_work_unit__{result_id}") or None
                export_note = request.POST.get(f"row_export_note__{result_id}") or ""
                resolve_labor_reconciliation_result(
                    result_id,
                    action,
                    request.user,
                    final_work_unit=final_work_unit,
                    comment=comment,
                    export_note=export_note,
                )
                messages.success(request, "대사 결과를 처리했습니다.")
                return redirect(_build_e_card_detail_redirect(batch.id, request))
            if request.POST.get("match_result_id"):
                result_id = request.POST.get("match_result_id")
                worker_id = request.POST.get(f"row_worker_id__{result_id}")
                match_reconciliation_worker(result_id, worker_id, request.user)
                messages.success(request, "근로자 매칭을 반영하고 대사를 다시 실행했습니다.")
                return redirect(_build_e_card_detail_redirect(batch.id, request))

            action = (request.POST.get("action") or "").strip().lower()
            if action == "resolve_bulk":
                selected_ids = request.POST.getlist("selected_result_ids")
                bulk_action = request.POST.get("bulk_resolution")
                bulk_comment = request.POST.get("bulk_comment") or ""
                bulk_final = request.POST.get("bulk_final_work_unit") or None
                count = bulk_resolve_labor_reconciliation_results(
                    selected_ids,
                    bulk_action,
                    request.user,
                    bulk_comment,
                    final_work_unit=bulk_final,
                )
                messages.success(request, f"대사 결과 {count}건을 일괄 처리했습니다.")
                return redirect(_build_e_card_detail_redirect(batch.id, request))
            if action == "confirm_batch":
                confirm_electronic_card_reconciliation_batch(batch, request.user)
                messages.success(request, "대사 결과를 확정했습니다.")
                return redirect(_build_e_card_detail_redirect(batch.id, request))
            if action == "generate_cwma_reupload":
                generate_cwma_card_reupload_excel(
                    batch,
                    request.user,
                    note=request.POST.get("export_note") or "",
                )
                messages.success(request, "CWMA 전자카드 재업로드용 엑셀을 생성했습니다.")
                return redirect(_build_e_card_detail_redirect(batch.id, request))
            if action == "reconcile_again":
                reconcile_electronic_card_import_batch(batch, request.user)
                messages.success(request, "전자카드와 ERP 출역 대사를 다시 실행했습니다.")
                return redirect(_build_e_card_detail_redirect(batch.id, request))
        except ValidationError as exc:
            messages.error(request, str(exc))

    result_qs, filter_values = _filter_reconciliation_results(request, batch)
    summary = batch.header_check_summary or {}
    unresolved_count = batch.reconciliation_results.filter(
        status__in=[
            LaborReconciliationStatus.ERP_ONLY,
            LaborReconciliationStatus.CARD_ONLY,
            LaborReconciliationStatus.DIFF,
            LaborReconciliationStatus.UNMATCHED,
        ],
        resolution="",
        final_work_unit__isnull=True,
    ).count()
    return render(
        request,
        "app/hq/e_card_import_detail.html",
        {
            "batch": batch,
            "summary": summary,
            "results": result_qs[:200],
            "filter_values": filter_values,
            "workers": WorkerMaster.objects.order_by("name", "id")[:300],
            "unresolved_count": unresolved_count,
            "current_query": request.GET.urlencode(),
            "status_choices": LaborReconciliationStatus.choices,
            "confirmed_work_days_count": batch.confirmed_work_days.count(),
            "excel_exports": batch.excel_exports.select_related("generated_by", "downloaded_by").order_by("-generated_at", "-id")[:20],
        },
    )


@login_required
def hq_labor_excel_export_download(request, export_id):
    require_role(request.user, [Role.HQ, Role.CEO], request=request)
    export_batch = get_object_or_404(
        LaborExcelExportBatch.objects.select_related("source_batch", "project"),
        id=export_id,
    )
    if (
        not export_batch.generated_file
        or not export_batch.generated_file.storage.exists(export_batch.generated_file.name)
    ):
        raise Http404("생성된 엑셀 파일을 찾을 수 없습니다.")
    try:
        register_labor_excel_export_download(export_batch, request.user)
    except ValidationError as exc:
        messages.error(request, str(exc))
        return redirect(f"/app/hq/labor/e-card-imports/{export_batch.source_batch_id}/")

    export_batch.generated_file.open("rb")
    return FileResponse(
        export_batch.generated_file,
        as_attachment=True,
        filename=export_batch.generated_filename
        or export_batch.original_filename
        or "cwma_card_reupload.xlsx",
    )


@login_required
def hq_confirmed_work_day_list(request):
    require_role(request.user, [Role.HQ, Role.CEO], request=request)
    qs = (
        LaborConfirmedWorkDay.objects.select_related(
            "batch",
            "worker",
            "actual_project",
            "report_project",
            "card_project",
            "confirmed_by",
        )
        .order_by("-work_date", "-id")
    )
    month = (request.GET.get("month") or "").strip()
    project_id = (request.GET.get("project") or "").strip()
    worker_id = (request.GET.get("worker") or "").strip()
    batch_id = (request.GET.get("batch_id") or "").strip()
    source_basis = (request.GET.get("source_basis") or "").strip()
    export_included = (request.GET.get("export_included") or "").strip()

    if month:
        try:
            year_str, month_str = month.split("-", 1)
            qs = qs.filter(year_month__year=int(year_str), year_month__month=int(month_str))
        except ValueError:
            messages.error(request, "기준월 형식은 YYYY-MM 이어야 합니다.")
    if project_id:
        qs = qs.filter(report_project_id=project_id)
    if worker_id:
        qs = qs.filter(worker_id=worker_id)
    if batch_id:
        qs = qs.filter(batch_id=batch_id)
    if source_basis:
        qs = qs.filter(source_basis=source_basis)
    if export_included in {"0", "1"}:
        qs = qs.filter(export_included=export_included == "1")

    return render(
        request,
        "app/hq/e_card_confirmed_work_days.html",
        {
            "rows": qs[:300],
            "month": month,
            "project_id": project_id,
            "worker_id": worker_id,
            "batch_id": batch_id,
            "source_basis": source_basis,
            "export_included": export_included,
            "projects": Project.objects.order_by("name"),
            "workers": WorkerMaster.objects.order_by("name", "id")[:300],
            "batches": ElectronicCardImportBatch.objects.order_by("-uploaded_at", "-id")[:100],
            "source_basis_choices": LaborConfirmedWorkSourceBasis.choices,
        },
    )


@login_required
def hq_worker_master_list(request):
    require_role(request.user, [Role.HQ, Role.CEO], request=request)
    q = (request.GET.get("q") or "").strip()
    active = request.GET.get("active")
    qs = WorkerMaster.objects.select_related("default_labor_role").order_by("name", "id")
    if q:
        qs = qs.filter(
            Q(name__icontains=q)
            | Q(phone__icontains=q)
            | Q(rrn_masked__icontains=q)
            | Q(account_holder__icontains=q)
            | Q(cwma_job_name__icontains=q)
            | Q(comwel_job_code__icontains=q)
        )
    if active in ("0", "1"):
        qs = qs.filter(active=active == "1")
    workers = list(qs[:100])
    for worker in workers:
        worker.usage_count = (
            worker.work_ledgers.count()
            + worker.electronic_card_raw_rows.count()
            + worker.electronic_card_day_rows.count()
            + worker.labor_reconciliation_results.count()
            + worker.confirmed_work_days.count()
            + worker.monthly_payrolls.count()
        )
    return render(
        request,
        "app/hq/labor_worker_list.html",
        {
            "workers": workers,
            "q": q,
            "active": active or "",
            "role": get_user_role(request.user),
        },
    )


@login_required
def hq_worker_master_new(request):
    require_role(request.user, [Role.HQ, Role.CEO], request=request)
    if request.method == "POST":
        form = WorkerMasterForm(request.POST)
        if form.is_valid():
            try:
                create_worker_master(form.cleaned_data, actor=request.user)
                messages.success(request, "근로자 마스터가 등록되었습니다.")
                return redirect("/app/hq/labor/workers/")
            except ValidationError as exc:
                form.add_error(None, str(exc))
        else:
            messages.error(request, "입력 오류가 있습니다. 아래 항목을 확인해 주세요.")
    else:
        form = WorkerMasterForm()
    return render(
        request,
        "app/hq/labor_worker_form.html",
        {"form": form, "mode": "create"},
    )


@login_required
def hq_worker_master_edit(request, worker_id):
    require_role(request.user, [Role.HQ, Role.CEO], request=request)
    worker = get_object_or_404(WorkerMaster, id=worker_id)
    if request.method == "POST":
        form = WorkerMasterForm(request.POST, instance=worker)
        if form.is_valid():
            try:
                update_worker_master(worker, form.cleaned_data, actor=request.user)
                messages.success(request, "근로자 마스터가 수정되었습니다.")
                return redirect("/app/hq/labor/workers/")
            except ValidationError as exc:
                form.add_error(None, str(exc))
        else:
            messages.error(request, "입력 오류가 있습니다. 아래 항목을 확인해 주세요.")
    else:
        form = WorkerMasterForm(instance=worker)
    return render(
        request,
        "app/hq/labor_worker_form.html",
        {"form": form, "mode": "edit", "worker": worker},
    )


@login_required
def hq_worker_master_delete(request, worker_id):
    require_role(request.user, [Role.HQ, Role.CEO], request=request)
    if request.method != "POST":
        raise PermissionDenied
    worker = get_object_or_404(WorkerMaster, id=worker_id)
    try:
        result = delete_or_deactivate_worker_master(worker, request.user)
    except ValidationError as exc:
        messages.error(request, str(exc))
        return redirect("/app/hq/labor/workers/")

    if result["action"] == "deleted":
        messages.success(request, "근로자 마스터를 삭제했습니다.")
    elif result["action"] == "deactivated":
        messages.warning(
            request,
            f"이 근로자는 사용 이력 {result['usage_count']}건이 있어 삭제할 수 없으며 비활성 처리되었습니다.",
        )
    else:
        messages.info(request, "이미 비활성 처리된 근로자입니다.")
    return redirect("/app/hq/labor/workers/")


@login_required
def hq_labor_work_ledger_list(request):
    require_role(request.user, [Role.HQ, Role.CEO], request=request)
    month = (request.GET.get("month") or "").strip()
    project_id = (request.GET.get("project") or "").strip()
    worker_id = (request.GET.get("worker") or "").strip()
    qs = (
        LaborWorkLedger.objects.select_related(
            "worker",
            "actual_project",
            "report_project",
            "labor_role",
            "timesheet_ref",
            "cost_ref",
        )
        .order_by("-work_date", "-id")
    )
    if month:
        try:
            year_str, month_str = month.split("-", 1)
            qs = qs.filter(work_month__year=int(year_str), work_month__month=int(month_str))
        except ValueError:
            messages.error(request, "월 필터 형식이 올바르지 않습니다.")
    if project_id:
        qs = qs.filter(Q(actual_project_id=project_id) | Q(report_project_id=project_id))
    if worker_id:
        qs = qs.filter(worker_id=worker_id)
    return render(
        request,
        "app/hq/labor_work_ledger_list.html",
        {
            "ledgers": qs[:100],
            "month": month,
            "project_id": project_id,
            "worker_id": worker_id,
            "projects": Project.objects.order_by("name"),
            "workers": WorkerMaster.objects.order_by("name", "id"),
        },
    )


@login_required
def hq_labor_work_ledger_form(request, ledger_id=None):
    require_role(request.user, [Role.HQ, Role.CEO], request=request)
    ledger = None
    if ledger_id is not None:
        ledger = get_object_or_404(
            LaborWorkLedger.objects.select_related(
                "worker",
                "actual_project",
                "report_project",
                "labor_role",
                "timesheet_ref",
                "cost_ref",
            ),
            id=ledger_id,
        )
    if request.method == "POST":
        form = LaborWorkLedgerForm(request.POST, instance=ledger)
        if form.is_valid():
            try:
                if ledger is None:
                    ledger = create_labor_work_ledger(form.cleaned_data, actor=request.user)
                    messages.success(request, "노무 작업 원장이 등록되었습니다.")
                else:
                    ledger = update_labor_work_ledger(ledger, form.cleaned_data, actor=request.user)
                    messages.success(request, "노무 작업 원장이 수정되었습니다.")
                return redirect(f"/app/hq/labor/work-ledger/{ledger.id}/")
            except (PermissionDenied, ValidationError) as exc:
                form.add_error(None, str(exc))
        else:
            messages.error(request, "입력 오류가 있습니다. 아래 항목을 확인해 주세요.")
    else:
        form = LaborWorkLedgerForm(instance=ledger)
    return render(
        request,
        "app/hq/labor_work_ledger_form.html",
        {"form": form, "ledger": ledger, "mode": "edit" if ledger else "create"},
    )


@login_required
def hq_labor_reporting_map(request):
    require_role(request.user, [Role.HQ, Role.CEO], request=request)
    params = request.POST if request.method == "POST" else request.GET
    month = (params.get("month") or date.today().strftime("%Y-%m")).strip()
    actual_project_id = (params.get("actual_project") or "").strip()
    report_project_id = (params.get("report_project") or "").strip()
    worker_id = (params.get("worker") or "").strip()
    only_different = "1" if (params.get("only_different") or "") == "1" else ""
    status = (params.get("status") or "").strip()

    if request.method == "POST":
        ledger_ids = request.POST.getlist("ledger_ids")
        target_report_project = (request.POST.get("target_report_project") or "").strip()
        reason = (request.POST.get("reason") or "").strip()
        if not ledger_ids:
            messages.error(request, "변경할 원장을 하나 이상 선택해 주세요.")
        elif not target_report_project:
            messages.error(request, "신고용 현장을 선택해 주세요.")
        else:
            try:
                updated = update_labor_reporting_project(
                    ledger_ids=ledger_ids,
                    report_project=target_report_project,
                    reason=reason,
                    actor=request.user,
                )
                messages.success(request, f"신고용 현장 {len(updated)}건을 변경했습니다.")
                return redirect(f"/app/hq/labor/reporting-map/?month={month}")
            except (PermissionDenied, ValidationError) as exc:
                messages.error(request, str(exc))

    qs = (
        LaborWorkLedger.objects.select_related(
            "worker",
            "actual_project",
            "report_project",
            "labor_role",
        )
        .order_by("-work_date", "-id")
    )
    try:
        year_str, month_str = month.split("-", 1)
        qs = qs.filter(work_month__year=int(year_str), work_month__month=int(month_str))
    except ValueError:
        messages.error(request, "월 형식은 YYYY-MM 이어야 합니다.")
        month = date.today().strftime("%Y-%m")
        year_str, month_str = month.split("-", 1)
        qs = qs.filter(work_month__year=int(year_str), work_month__month=int(month_str))
    if actual_project_id:
        qs = qs.filter(actual_project_id=actual_project_id)
    if report_project_id:
        qs = qs.filter(report_project_id=report_project_id)
    if worker_id:
        qs = qs.filter(worker_id=worker_id)
    if status:
        qs = qs.filter(status=status)
    if only_different:
        qs = qs.exclude(actual_project_id=models.F("report_project_id"))
    return render(
        request,
        "app/hq/labor_reporting_map.html",
        {
            "ledgers": qs[:200],
            "month": month,
            "actual_project_id": actual_project_id,
            "report_project_id": report_project_id,
            "worker_id": worker_id,
            "only_different": only_different,
            "status": status,
            "projects": Project.objects.order_by("name"),
            "workers": WorkerMaster.objects.order_by("name", "id"),
            "status_choices": LaborWorkLedgerStatus.choices,
        },
    )


@login_required
def hq_labor_role_list(request):
    require_role(request.user, [Role.HQ, Role.CEO], request=request)
    q = (request.GET.get("q") or "").strip()
    active = request.GET.get("active")
    qs = LaborRole.objects.all().order_by("sort_order", "code")
    if q:
        qs = qs.filter(Q(code__icontains=q) | Q(name__icontains=q))
    if active in ("0", "1"):
        qs = qs.filter(is_active=active == "1")
    return render(
        request,
        "app/hq/master_labor_role_list.html",
        {"roles": qs, "q": q, "active": active or "", "role": get_user_role(request.user)},
    )


@login_required
def hq_labor_role_new(request):
    require_role(request.user, [Role.HQ, Role.CEO], request=request)
    if request.method == "POST":
        form = LaborRoleForm(request.POST)
        if form.is_valid():
            try:
                create_labor_role(form.cleaned_data, actor=request.user)
                messages.success(request, "\uc9c1\uc885\uc774 \uc0dd\uc131\ub418\uc5c8\uc2b5\ub2c8\ub2e4.")
                return redirect("/app/hq/master/labor/roles/")
            except ValidationError as exc:
                form.add_error(None, str(exc))
        else:
            messages.error(
                request,
                "\uc785\ub825 \uc624\ub958\uac00 \uc788\uc2b5\ub2c8\ub2e4. \uc544\ub798 \ud56d\ubaa9\uc744 \ud655\uc778\ud574 \uc8fc\uc138\uc694.",
            )
    else:
        form = LaborRoleForm()
    return render(
        request,
        "app/hq/master_labor_role_form.html",
        {"form": form, "mode": "create"},
    )


@login_required
def hq_labor_role_edit(request, role_id):
    require_role(request.user, [Role.HQ, Role.CEO], request=request)
    role = get_object_or_404(LaborRole, id=role_id)
    if request.method == "POST":
        form = LaborRoleForm(request.POST, instance=role)
        if form.is_valid():
            try:
                update_labor_role(role, form.cleaned_data, actor=request.user)
                messages.success(request, "\uc9c1\uc885\uc774 \uc218\uc815\ub418\uc5c8\uc2b5\ub2c8\ub2e4.")
                return redirect("/app/hq/master/labor/roles/")
            except ValidationError as exc:
                form.add_error(None, str(exc))
        else:
            messages.error(
                request,
                "\uc785\ub825 \uc624\ub958\uac00 \uc788\uc2b5\ub2c8\ub2e4. \uc544\ub798 \ud56d\ubaa9\uc744 \ud655\uc778\ud574 \uc8fc\uc138\uc694.",
            )
    else:
        form = LaborRoleForm(instance=role)
    return render(
        request,
        "app/hq/master_labor_role_form.html",
        {"form": form, "mode": "edit", "role_obj": role},
    )


@login_required
def hq_labor_role_toggle(request, role_id):
    require_role(request.user, [Role.HQ, Role.CEO], request=request)
    if request.method != "POST":
        raise PermissionDenied
    role = get_object_or_404(LaborRole, id=role_id)
    try:
        update_labor_role(role, {"is_active": not role.is_active}, actor=request.user)
        messages.success(request, "\uc9c1\uc885 \ud65c\uc131 \uc0c1\ud0dc\uac00 \ubcc0\uacbd\ub418\uc5c8\uc2b5\ub2c8\ub2e4.")
    except ValidationError as exc:
        messages.error(request, str(exc))
    return redirect("/app/hq/master/labor/roles/")


@login_required
def hq_labor_rate_list(request):
    require_role(request.user, [Role.HQ, Role.CEO], request=request)
    q = (request.GET.get("q") or "").strip()
    active = request.GET.get("active")
    project_id = request.GET.get("project")
    role_id = request.GET.get("role")
    worker_id = request.GET.get("worker")
    qs = (
        LaborRateTable.objects.select_related("labor_role", "project", "worker__default_labor_role")
        .order_by("-effective_from", "labor_role_id")
    )
    if q:
        qs = qs.filter(
            Q(labor_role__code__icontains=q)
            | Q(labor_role__name__icontains=q)
        )
    if project_id:
        qs = qs.filter(project_id=project_id)
    if role_id:
        qs = qs.filter(labor_role_id=role_id)
    if worker_id:
        qs = qs.filter(worker_id=worker_id)
    if active in ("0", "1"):
        qs = qs.filter(is_active=active == "1")
    roles = LaborRole.objects.order_by("code")
    projects = Project.objects.order_by("name")
    workers = WorkerMaster.objects.filter(active=True).select_related("default_labor_role").order_by(
        "name", "id"
    )
    rate_scope_labels = {
        "PROJECT_WORKER": "프로젝트+근로자 단가",
        "PROJECT_ROLE": "프로젝트별 직종단가",
        "WORKER": "근로자별 단가",
        "ROLE_BASE": "기본 직종단가",
    }
    rate_scope_priority = {
        "PROJECT_WORKER": 100,
        "PROJECT_ROLE": 80,
        "WORKER": 60,
        "ROLE_BASE": 40,
    }
    for rate in qs:
        rate.rate_scope = get_rate_scope(rate)
        rate.rate_scope_label = rate_scope_labels[rate.rate_scope]
        rate.rate_priority = rate_scope_priority[rate.rate_scope]
    return render(
        request,
        "app/hq/master_labor_rate_list.html",
        {
            "rates": qs,
            "roles": roles,
            "projects": projects,
            "workers": workers,
            "q": q,
            "active": active or "",
            "role_id": role_id or "",
            "project_id": project_id or "",
            "worker_id": worker_id or "",
        },
    )


@login_required
def hq_labor_compliance_export_list(request):
    require_role(request.user, [Role.HQ, Role.CEO], request=request)
    projects = Project.objects.order_by("name", "id")
    if request.method == "POST":
        project_id = request.POST.get("project_id")
        month_value = (request.POST.get("month") or "").strip()
        export_type = request.POST.get("export_type")
        try:
            year_text, month_text = month_value.split("-", 1)
            export = generate_labor_compliance_export(
                project=get_object_or_404(Project, id=project_id), year=int(year_text),
                month=int(month_text), export_type=export_type, actor=request.user,
            )
            messages.success(request, f"{export.get_export_type_display()} 엑셀을 생성했습니다.")
            return redirect("/app/hq/labor/compliance-exports/")
        except (ValueError, ValidationError, PermissionDenied) as exc:
            messages.error(request, str(exc))
    exports = LaborComplianceExport.objects.select_related("project", "generated_by", "downloaded_by").order_by("-generated_at")[:100]
    return render(request, "app/hq/labor_compliance_exports.html", {
        "projects": projects, "exports": exports,
        "export_types": LaborComplianceExportType.choices,
    })


@login_required
def hq_labor_compliance_export_download(request, export_id):
    require_role(request.user, [Role.HQ, Role.CEO], request=request)
    export = get_object_or_404(LaborComplianceExport.objects.select_related("project"), id=export_id)
    if not export.generated_file or not export.generated_file.storage.exists(export.generated_file.name):
        raise Http404("생성된 엑셀 파일을 찾을 수 없습니다.")
    register_labor_compliance_export_download(export, request.user)
    export.generated_file.open("rb")
    return FileResponse(export.generated_file, as_attachment=True, filename=export.generated_filename)


@login_required
def hq_labor_rate_new(request):
    require_role(request.user, [Role.HQ, Role.CEO], request=request)
    if request.method == "POST":
        form = LaborRateForm(request.POST)
        if form.is_valid():
            try:
                create_rate(form.cleaned_data, actor=request.user)
                messages.success(request, "\ub2e8\uac00\uac00 \ub4f1\ub85d\ub418\uc5c8\uc2b5\ub2c8\ub2e4.")
                return redirect("/app/hq/labor/rates/")
            except ValidationError as exc:
                form.add_error(None, str(exc))
        else:
            messages.error(
                request,
                "\uc785\ub825 \uc624\ub958\uac00 \uc788\uc2b5\ub2c8\ub2e4. \uc544\ub798 \ud56d\ubaa9\uc744 \ud655\uc778\ud574 \uc8fc\uc138\uc694.",
            )
    else:
        form = LaborRateForm()
    return render(
        request,
        "app/hq/master_labor_rate_form.html",
        {"form": form, "mode": "create"},
    )


@login_required
def hq_labor_rate_edit(request, rate_id):
    require_role(request.user, [Role.HQ, Role.CEO], request=request)
    rate = get_object_or_404(LaborRateTable, id=rate_id)
    if request.method == "POST":
        form = LaborRateForm(request.POST, instance=rate)
        if form.is_valid():
            try:
                update_rate(rate, form.cleaned_data, actor=request.user)
                messages.success(request, "\ub2e8\uac00\uac00 \uc218\uc815\ub418\uc5c8\uc2b5\ub2c8\ub2e4.")
                return redirect("/app/hq/labor/rates/")
            except ValidationError as exc:
                form.add_error(None, str(exc))
        else:
            messages.error(
                request,
                "\uc785\ub825 \uc624\ub958\uac00 \uc788\uc2b5\ub2c8\ub2e4. \uc544\ub798 \ud56d\ubaa9\uc744 \ud655\uc778\ud574 \uc8fc\uc138\uc694.",
            )
    else:
        form = LaborRateForm(instance=rate)
    return render(
        request,
        "app/hq/master_labor_rate_form.html",
        {"form": form, "mode": "edit", "rate_obj": rate},
    )


@login_required
def hq_labor_rate_toggle(request, rate_id):
    require_role(request.user, [Role.HQ, Role.CEO], request=request)
    if request.method != "POST":
        raise PermissionDenied
    rate = get_object_or_404(LaborRateTable, id=rate_id)
    try:
        update_rate(rate, {"is_active": not rate.is_active}, actor=request.user)
        messages.success(request, "\ub2e8\uac00 \ud65c\uc131 \uc0c1\ud0dc\uac00 \ubcc0\uacbd\ub418\uc5c8\uc2b5\ub2c8\ub2e4.")
    except ValidationError as exc:
        messages.error(request, str(exc))
    return redirect("/app/hq/labor/rates/")


def _get_assigned_projects(user):
    return Project.objects.filter(
        projectassignment__user=user,
        projectassignment__is_active=True,
        legal_entity__in=get_user_legal_entities(user),
    ).distinct()


def _parse_work_date(value):
    if not value:
        return None
    try:
        return date.fromisoformat(value)
    except ValueError:
        return None


def _build_lines_payload_from_post(post_data, max_rows=12):
    lines = []
    for idx in range(max_rows):
        worker_id = post_data.get(f"lines-{idx}-worker_id")
        role_id = post_data.get(f"lines-{idx}-role_id")
        headcount = post_data.get(f"lines-{idx}-headcount")
        hours = post_data.get(f"lines-{idx}-hours")
        rate_type = post_data.get(f"lines-{idx}-rate_type") or "DAY"
        memo = post_data.get(f"lines-{idx}-memo") or ""
        if not worker_id and not role_id and not headcount and not hours and not memo:
            continue
        lines.append(
            {
                "worker_id": worker_id,
                "labor_role_id": role_id,
                "headcount": headcount,
                "hours": hours,
                "rate_type": rate_type,
                "memo": memo,
            }
        )
    return lines


def _worker_safe_option_label(worker):
    role_name = worker.default_labor_role.name if worker.default_labor_role else "역할 미설정"
    return f"{worker.name} / {role_name}"


@login_required
def field_worker_search(request):
    require_role(request.user, [Role.FIELD], request=request)
    project_id = (request.GET.get("project_id") or "").strip()
    if project_id and not _get_assigned_projects(request.user).filter(id=project_id).exists():
        return JsonResponse({"results": []}, status=403)

    query = (request.GET.get("q") or "").strip()
    if not query:
        return JsonResponse({"results": []})

    workers = (
        WorkerMaster.objects.filter(active=True)
        .select_related("default_labor_role")
        .filter(
            Q(name__icontains=query)
            | Q(default_labor_role__name__icontains=query)
            | Q(default_labor_role__code__icontains=query)
        )
        .order_by("name", "id")[:20]
    )
    return JsonResponse(
        {
            "results": [
                {
                    "id": worker.id,
                    "text": _worker_safe_option_label(worker),
                    "role_id": worker.default_labor_role_id,
                }
                for worker in workers
            ]
        }
    )


@login_required
def field_timesheet_list(request):
    require_role(request.user, [Role.FIELD], request=request)
    projects = _get_assigned_projects(request.user).filter(legal_entity=get_current_legal_entity(request))
    timesheets = (
        Timesheet.objects.select_related("project")
        .filter(created_by=request.user, project__in=projects)
        .order_by("-work_date", "-id")[:50]
    )
    attachments_map = {}
    timesheet_ids = [sheet.id for sheet in timesheets]
    if timesheet_ids:
        evidences = (
            Evidence.objects.filter(
                object_type="TIMESHEET",
                object_id__in=timesheet_ids,
            )
            .prefetch_related("files")
            .order_by("-created_at")
        )
        for evidence in evidences:
            attachments_map.setdefault(evidence.object_id, []).extend(
                list(evidence.files.all().order_by("-created_at"))
            )
    for sheet in timesheets:
        sheet.attachments = attachments_map.get(sheet.id, [])
    return render(
        request,
        "app/field/timesheet_list.html",
        {"projects": projects, "timesheets": timesheets},
    )


@login_required
def field_timesheet_form(request, timesheet_id=None):
    require_role(request.user, [Role.FIELD], request=request)
    form_error = ""
    projects = _get_assigned_projects(request.user).filter(legal_entity=get_current_legal_entity(request))
    if not projects.exists():
        messages.error(request, "\ubc30\uc815\ub41c \ud504\ub85c\uc81d\ud2b8\uac00 \uc5c6\uc2b5\ub2c8\ub2e4.")
        return render(request, "app/field/timesheet_form.html", {"projects": []})
    timesheet = None
    if timesheet_id:
        timesheet = get_object_or_404(
            Timesheet.objects.select_related("project").prefetch_related(
                "lines", "lines__labor_role", "lines__worker"
            ),
            id=timesheet_id,
            created_by=request.user,
            project__in=projects,
        )
    roles = LaborRole.objects.filter(is_active=True).order_by("sort_order", "code")
    workers = WorkerMaster.objects.filter(active=True).select_related(
        "default_labor_role"
    ).order_by("name", "id")
    line_rows = []
    if timesheet:
        for line in timesheet.lines.all():
            line_rows.append(
                {
                    "worker_id": line.worker_id,
                    "worker_label": _worker_safe_option_label(line.worker) if line.worker else "",
                    "role_id": line.labor_role_id,
                    "headcount": line.headcount,
                    "hours": line.hours,
                    "rate_type": line.rate_type,
                    "memo": line.memo,
                }
            )
    while len(line_rows) < 8:
        line_rows.append(
            {
                "worker_id": "",
                "role_id": "",
                "headcount": "",
                "hours": "",
                "rate_type": "DAY",
                "memo": "",
            }
        )
    if request.method == "POST":
        project_id = request.POST.get("project_id")
        work_date = _parse_work_date(request.POST.get("work_date"))
        note = request.POST.get("note") or ""
        action = request.POST.get("action") or "draft"
        if not project_id or not work_date:
            messages.error(request, "\ud504\ub85c\uc81d\ud2b8\uc640 \uc791\uc131\uc77c\uc744 \ud655\uc778\ud574 \uc8fc\uc138\uc694.")
        else:
            project = get_object_or_404(Project, id=project_id)
            require_project_access(request.user, project.id)
            try:
                if timesheet is None:
                    timesheet = create_timesheet(
                        project=project,
                        work_date=work_date,
                        actor=request.user,
                        note=note,
                    )
                lines_payload = _build_lines_payload_from_post(request.POST)
                upsert_timesheet_lines(
                    timesheet=timesheet, lines_payload=lines_payload, actor=request.user
                )
                if timesheet.note != note:
                    timesheet.note = note
                    timesheet.save(update_fields=["note", "updated_at"])
                if action in ("submit", "resubmit"):
                    submit_timesheet(timesheet=timesheet, actor=request.user)
                    messages.success(
                        request,
                        "출역부를 다시 제출했습니다. HQ 검토 대기 상태입니다."
                        if action == "resubmit"
                        else "출역부가 제출되었습니다. 승인 대기 상태입니다.",
                    )
                    return redirect("/app/field/labor/timesheets/")
                messages.success(request, "\ucd9c\uc5ed\ubd80\uac00 \uc784\uc2dc\uc800\uc7a5\ub418\uc5c8\uc2b5\ub2c8\ub2e4.")
                return redirect(f"/app/field/labor/timesheets/{timesheet.id}/")
            except (PermissionDenied, ValidationError) as exc:
                message = str(exc)
                if hasattr(exc, "message_dict"):
                    message = " ".join(
                        [", ".join(values) if isinstance(values, (list, tuple)) else str(values) for values in exc.message_dict.values()]
                    )
                elif getattr(exc, "messages", None):
                    message = " ".join(str(item) for item in exc.messages)
                form_error = message
                messages.error(request, message)
    workflow = (
        get_timesheet_workflow_state(timesheet, user=request.user)
        if timesheet is not None
        else None
    )
    form_disabled = bool(workflow and not workflow["can_field_edit"])
    timesheet_attachments = []
    timesheet_can_edit_attachments = False
    timesheet_attachment_help_text = "출역부 첨부는 읽기 전용으로 표시됩니다."
    if timesheet is not None:
        evidences = list(
            Evidence.objects.filter(
                object_type="TIMESHEET",
                object_id=timesheet.id,
            )
            .prefetch_related("files")
            .order_by("-created_at")
        )
        for evidence in evidences:
            timesheet_attachments.extend(evidence.files.all().order_by("-created_at"))
        timesheet_can_edit_attachments = can_edit_attachments(
            status=timesheet.status,
            is_closed_locked=is_project_or_month_locked(
                project=timesheet.project,
                target_date=timesheet.work_date,
            ),
        )
        if timesheet_can_edit_attachments:
            timesheet_attachment_help_text = (
                "임시저장/반려 상태입니다. 출역부 첨부 업로드는 현재 지원 예정입니다."
            )
        else:
            timesheet_attachment_help_text = (
                "제출/승인/마감 상태에서는 첨부를 수정할 수 없습니다."
            )
    return render(
        request,
        "app/field/timesheet_form.html",
        {
            "projects": projects,
            "timesheet": timesheet,
            "roles": roles,
            "workers": workers,
            "line_rows": line_rows,
            "form_disabled": form_disabled,
            "workflow": workflow,
            "form_error": form_error,
            "timesheet_existing_files": timesheet_attachments,
            "timesheet_can_edit_attachments": timesheet_can_edit_attachments,
            "timesheet_attachment_upload_url": None,
            "timesheet_attachment_delete_url": None,
            "timesheet_attachment_help_text": timesheet_attachment_help_text,
        },
    )


@login_required
def hq_timesheet_list(request):
    require_role(request.user, [Role.HQ, Role.CEO], request=request)
    status = request.GET.get("status") or TimesheetStatus.SUBMITTED
    qs = (
        Timesheet.objects.select_related("project", "created_by")
        .filter(project__legal_entity=get_current_legal_entity(request))
        .order_by("-work_date", "-id")
    )
    if status:
        qs = qs.filter(status=status)
    return render(
        request,
        "app/hq/timesheet_list.html",
        {"timesheets": qs[:100], "status": status},
    )


@login_required
def hq_timesheet_detail(request, timesheet_id):
    require_role(request.user, [Role.HQ, Role.CEO], request=request)
    timesheet = get_object_or_404(
        Timesheet.objects.select_related("project", "created_by", "approved_by", "rejected_by")
        .prefetch_related("lines", "lines__labor_role"),
        id=timesheet_id,
        project__legal_entity=get_current_legal_entity(request),
    )
    total_amount = sum([line.amount for line in timesheet.lines.all()])
    return render(
        request,
        "app/hq/timesheet_detail.html",
        {"timesheet": timesheet, "total_amount": total_amount},
    )


@login_required
def hq_timesheet_approve(request, timesheet_id):
    require_role(request.user, [Role.HQ, Role.CEO], request=request)
    if request.method != "POST":
        raise PermissionDenied
    timesheet = get_object_or_404(Timesheet, id=timesheet_id)
    try:
        approve_timesheet(timesheet=timesheet, actor=request.user)
        messages.success(request, "\ucd9c\uc5ed\ubd80\uac00 \uc2b9\uc778\ub418\uc5c8\uc2b5\ub2c8\ub2e4.")
    except (PermissionDenied, ValidationError) as exc:
        messages.error(request, str(exc))
    return redirect(f"/app/hq/labor/timesheets/{timesheet_id}/")


@login_required
def hq_timesheet_reject(request, timesheet_id):
    require_role(request.user, [Role.HQ, Role.CEO], request=request)
    if request.method != "POST":
        raise PermissionDenied
    timesheet = get_object_or_404(Timesheet, id=timesheet_id)
    reason = request.POST.get("reason") or ""
    try:
        reject_timesheet(timesheet=timesheet, actor=request.user, reason=reason)
        messages.success(request, "\ucd9c\uc5ed\ubd80\uac00 \ubc18\ub824\ub418\uc5c8\uc2b5\ub2c8\ub2e4.")
    except (PermissionDenied, ValidationError) as exc:
        messages.error(request, str(exc))
    return redirect(f"/app/hq/labor/timesheets/{timesheet_id}/")


def _build_payroll_lines_payload_from_post(post_data, max_rows=20):
    lines = []
    for idx in range(max_rows):
        project_id = post_data.get(f"lines-{idx}-project_id")
        amount = post_data.get(f"lines-{idx}-amount")
        cbs_id = post_data.get(f"lines-{idx}-cbs_id")
        memo = post_data.get(f"lines-{idx}-memo") or ""
        if not project_id and not amount and not memo and not cbs_id:
            continue
        lines.append(
            {
                "project_id": project_id,
                "amount": amount,
                "cbs_id": cbs_id,
                "memo": memo,
            }
        )
    return lines


def _build_payroll_line_rows(lines, max_rows=12):
    rows = []
    for line in lines:
        rows.append(
            {
                "project_id": line.project_id,
                "cbs_id": line.cbs_id,
                "amount": line.amount,
                "memo": line.memo,
            }
        )
    while len(rows) < max_rows:
        rows.append({"project_id": "", "cbs_id": "", "amount": "", "memo": ""})
    return rows


@login_required
def hq_payroll_list(request):
    require_role(request.user, [Role.HQ, Role.CEO], request=request)
    month = (request.GET.get("month") or "").strip()
    project_id = (request.GET.get("project") or "").strip()
    worker_id = (request.GET.get("worker") or "").strip()
    payment_status = (request.GET.get("payment_status") or "").strip()
    if request.method == "POST":
        generate_month = (request.POST.get("month") or "").strip()
        if not generate_month:
            messages.error(request, "집계할 월을 선택해 주세요.")
        else:
            try:
                year_str, month_str = generate_month.split("-", 1)
                result = generate_labor_monthly_payroll(
                    year=int(year_str),
                    month=int(month_str),
                    actor=request.user,
                )
                messages.success(
                    request,
                    f"{result['year_month']:%Y-%m} 급여 요약 {result['row_count']}건을 생성했습니다.",
                )
                return redirect(f"/app/hq/labor/monthly-payroll/?month={generate_month}")
            except (PermissionDenied, ValidationError, ValueError) as exc:
                messages.error(request, str(exc))
    qs = (
        LaborMonthlyPayroll.objects.select_related("worker", "project", "report_project")
        .order_by("-year_month", "worker__name", "project__name", "id")
    )
    if month:
        try:
            year_str, month_str = month.split("-", 1)
            qs = qs.filter(year_month__year=int(year_str), year_month__month=int(month_str))
        except ValueError:
            messages.error(request, "월 형식은 YYYY-MM 이어야 합니다.")
    if project_id:
        qs = qs.filter(Q(project_id=project_id) | Q(report_project_id=project_id))
    if worker_id:
        qs = qs.filter(worker_id=worker_id)
    if payment_status:
        qs = qs.filter(payment_status=payment_status)
    return render(
        request,
        "app/hq/payroll_list.html",
        {
            "month": month,
            "project_id": project_id,
            "worker_id": worker_id,
            "payment_status": payment_status,
            "rows": qs[:200],
            "projects": Project.objects.order_by("name"),
            "workers": WorkerMaster.objects.order_by("name", "id"),
            "payment_statuses": LaborMonthlyPayrollPaymentStatus.choices,
        },
    )


@login_required
def hq_payroll_allocation_list(request):
    require_role(request.user, [Role.HQ, Role.CEO], request=request)
    year = request.GET.get("year") or ""
    month = request.GET.get("month") or ""
    status = request.GET.get("status") or ""
    qs = PayrollAllocationBatch.objects.filter(
        legal_entity__in=get_user_legal_entities(request.user)
    ).select_related("legal_entity").order_by("-period_year", "-period_month", "-id")
    if year:
        qs = qs.filter(period_year=year)
    if month:
        qs = qs.filter(period_month=month)
    if status:
        qs = qs.filter(status=status)
    totals = (
        PayrollAllocationLine.objects.filter(batch__in=qs)
        .values("batch_id")
        .annotate(total=models.Sum("amount"))
    )
    totals_map = {item["batch_id"]: item["total"] or 0 for item in totals}
    batches = []
    for batch in qs[:100]:
        sum_lines = totals_map.get(batch.id, 0)
        batches.append(
            {
                "obj": batch,
                "sum_lines": sum_lines,
                "diff": batch.total_amount - sum_lines,
            }
        )
    return render(
        request,
        "app/hq/payroll_allocation_list.html",
        {
            "batches": batches,
            "year": year,
            "month": month,
            "status": status,
        },
    )


@login_required
def hq_payroll_new(request):
    require_role(request.user, [Role.HQ, Role.CEO], request=request)
    if request.method == "POST":
        form = PayrollBatchForm(request.POST, actor=request.user)
        if form.is_valid():
            try:
                batch = create_payroll_batch(
                    year=form.cleaned_data["period_year"],
                    month=form.cleaned_data["period_month"],
                    total_amount=form.cleaned_data["total_amount"],
                    legal_entity=form.cleaned_data["legal_entity"],
                    actor=request.user,
                    note=form.cleaned_data.get("note") or "",
                )
                messages.success(request, "급여 배부 배치가 생성되었습니다.")
                return redirect(f"/app/hq/labor/payroll-allocation/{batch.id}/")
            except ValidationError as exc:
                form.add_error(None, str(exc))
        else:
            messages.error(
                request,
                "입력 오류가 있습니다. 아래 항목을 확인해 주세요.",
            )
    else:
        form = PayrollBatchForm(actor=request.user)
    return render(
        request,
        "app/hq/payroll_form.html",
        {
            "form": form,
            "mode": "create",
            "line_rows": _build_payroll_line_rows([]),
            "sum_lines": 0,
            "diff": 0,
            "status": PayrollAllocationStatus.DRAFT,
            "projects": Project.objects.filter(legal_entity__in=get_user_legal_entities(request.user)).order_by("name"),
            "cost_items": CostItem.objects.filter(is_active=True).order_by("code"),
        },
    )


@login_required
def hq_payroll_detail(request, batch_id):
    require_role(request.user, [Role.HQ, Role.CEO], request=request)
    batch = get_object_or_404(PayrollAllocationBatch.objects.select_related("legal_entity"), id=batch_id)
    require_legal_entity_access(request.user, batch.legal_entity, request=request)
    lines = list(
        PayrollAllocationLine.objects.select_related("project", "cbs")
        .filter(batch=batch)
        .order_by("id")
    )
    if request.method == "POST":
        form = PayrollBatchForm(request.POST, instance=batch, actor=request.user)
        action = request.POST.get("action") or "save"
        if form.is_valid():
            try:
                update_payroll_batch(batch, form.cleaned_data, actor=request.user)
                payload = _build_payroll_lines_payload_from_post(request.POST)
                upsert_payroll_lines(batch, payload, actor=request.user)
                if action == "submit":
                    submit_payroll_batch(batch, actor=request.user)
                    messages.success(request, "급여 배부가 제출되었습니다.")
                else:
                    messages.success(request, "급여 배부가 임시저장되었습니다.")
                return redirect(f"/app/hq/labor/payroll-allocation/{batch.id}/")
            except ValidationError as exc:
                form.add_error(None, str(exc))
            except PermissionDenied as exc:
                messages.error(request, str(exc))
        else:
            messages.error(
                request,
                "입력 오류가 있습니다. 아래 항목을 확인해 주세요.",
            )
    else:
        form = PayrollBatchForm(instance=batch, actor=request.user)
    ok, diff, sum_lines = validate_payroll_batch(batch)
    return render(
        request,
        "app/hq/payroll_form.html",
        {
            "form": form,
            "mode": "edit",
            "batch": batch,
            "line_rows": _build_payroll_line_rows(lines),
            "sum_lines": sum_lines,
            "diff": diff,
            "status": batch.status,
            "projects": Project.objects.filter(legal_entity=batch.legal_entity).order_by("name"),
            "cost_items": CostItem.objects.filter(is_active=True).order_by("code"),
            "form_disabled": batch.status
            in (PayrollAllocationStatus.SUBMITTED, PayrollAllocationStatus.APPROVED),
        },
    )


def _previous_office_payroll_period(run):
    if run.period_month == 1:
        return run.period_year - 1, 12
    return run.period_year, run.period_month - 1


def _get_or_create_seeded_office_payslip(run, employee):
    """Seed recurring payroll inputs from the immediately preceding month."""
    previous_year, previous_month = _previous_office_payroll_period(run)
    previous = (
        OfficePayslip.objects.filter(
            employee=employee,
            run__period_year=previous_year,
            run__period_month=previous_month,
        )
        .order_by("-id")
        .first()
    )
    policy, _ = OfficePayrollDeductionPolicy.objects.get_or_create(year=run.period_year)
    defaults = {
        "meal_allowance_pay": policy.meal_allowance_default,
        "fuel_allowance_pay": policy.fuel_allowance_default,
    }
    if previous is not None:
        # A new monthly register starts as a faithful copy of the immediately
        # preceding register.  HQ can then run automatic deductions to refresh
        # statutory amounts for the new month, or amend any carried value.
        for field in (
            "base_pay", "meal_allowance_pay", "fuel_allowance_pay",
            "site_allowance_pay", "overtime_pay", "bonus_pay",
            "income_tax", "local_income_tax", "national_pension",
            "health_insurance", "long_term_care", "employment_insurance",
            "other_deduction",
        ):
            defaults[field] = getattr(previous, field)
        # These are company-wide recurring non-taxable benefits. Preserve a
        # valid preceding value while restoring the standard value for legacy
        # records created before the two fields existed.
        defaults["meal_allowance_pay"] = previous.meal_allowance_pay or policy.meal_allowance_default
        defaults["fuel_allowance_pay"] = previous.fuel_allowance_pay or policy.fuel_allowance_default
    return OfficePayslip.objects.get_or_create(run=run, employee=employee, defaults=defaults)


@login_required
def hq_office_payroll_list(request):
    require_role(request.user, [Role.HQ], request=request)

    def _birth_date_from_request():
        value = (request.POST.get("birth_date") or "").strip()
        if not value:
            return None
        try:
            return date.fromisoformat(value)
        except ValueError as exc:
            raise ValidationError("생년월일은 YYYY-MM-DD 형식으로 입력해 주세요.") from exc

    if request.method == "POST":
        try:
            if request.POST.get("action") == "add_employee_profile":
                from django.contrib.auth import get_user_model
                username = (request.POST.get("username") or "").strip()
                account = get_user_model().objects.filter(username=username).first()
                if account is None:
                    messages.error(
                        request,
                        f"로그인 아이디 '{username}'의 사용자 계정이 없습니다. "
                        "먼저 사용자 계정을 등록한 뒤 본사 직원으로 등록해 주세요.",
                    )
                    return redirect("/app/hq/labor/office-payroll/")
                with transaction.atomic():
                    employment_legal_entity = get_object_or_404(
                        LegalEntity,
                        id=request.POST.get("employment_legal_entity_id"),
                        is_active=True,
                    )
                    require_legal_entity_access(request.user, employment_legal_entity, request=request)
                    year = timezone.localdate().year
                    sequence, _ = OfficeEmployeeNumberSequence.objects.select_for_update().get_or_create(year=year)
                    sequence.last_number += 1
                    sequence.save(update_fields=["last_number"])
                    employee_no = f"{employment_legal_entity.code}-HQ-{year:04d}-{sequence.last_number:04d}"
                    dependent_count = int(request.POST.get("tax_dependent_count") or 1)
                    withholding_ratio = int(request.POST.get("tax_withholding_ratio") or 100)
                    if not 1 <= dependent_count <= 11 or withholding_ratio not in (80, 100, 120):
                        raise ValidationError("공제대상 가족 수와 원천징수 선택비율을 확인해 주세요.")
                    child_count = int(request.POST.get("tax_child_count_8_to_20") or 0)
                    if child_count < 0:
                        raise ValidationError("자녀 수를 확인해 주세요.")
                    employee = OfficeEmployeeProfile(user=account, employee_no=employee_no, employment_legal_entity=employment_legal_entity, department=(request.POST.get("department") or "").strip(), tax_dependent_count=dependent_count, tax_child_count_8_to_20=child_count, tax_withholding_ratio=withholding_ratio)
                    employee.set_birth_date(_birth_date_from_request())
                    employee.save()
                messages.success(request, "본사 직원으로 등록했습니다.")
                return redirect("/app/hq/labor/office-payroll/")
            if request.POST.get("action") == "save_tax_profile":
                employee = get_object_or_404(OfficeEmployeeProfile, id=request.POST.get("employee_id"), active=True)
                dependent_count = int(request.POST.get("tax_dependent_count") or 1)
                child_count = int(request.POST.get("tax_child_count_8_to_20") or 0)
                withholding_ratio = int(request.POST.get("tax_withholding_ratio") or 100)
                birth_date = _birth_date_from_request()
                if not 1 <= dependent_count <= 11 or child_count < 0 or withholding_ratio not in (80, 100, 120):
                    raise ValidationError("공제대상 가족 수는 1~11명, 선택비율은 80/100/120%만 가능합니다.")
                before = {"birth_date_registered": bool(employee.birth_date), "dependent_count": employee.tax_dependent_count, "child_count": employee.tax_child_count_8_to_20, "withholding_ratio": employee.tax_withholding_ratio}
                employee.tax_dependent_count, employee.tax_child_count_8_to_20, employee.tax_withholding_ratio = dependent_count, child_count, withholding_ratio
                employee.set_birth_date(birth_date)
                employee.save(update_fields=["birth_date_encrypted", "birth_date_masked", "tax_dependent_count", "tax_child_count_8_to_20", "tax_withholding_ratio", "updated_at"])
                log_action(actor=request.user, action="OFFICE_EMPLOYEE_TAX_PROFILE_UPDATE", object_type="OfficeEmployeeProfile", object_id=employee.id, before=before, after={"birth_date_registered": bool(birth_date), "dependent_count": dependent_count, "child_count": child_count, "withholding_ratio": withholding_ratio})
                messages.success(request, "직원별 세무·국민연금 적용 정보를 저장했습니다.")
                return redirect("/app/hq/labor/office-payroll/")
            year, month = int(request.POST["period_year"]), int(request.POST["period_month"])
            legal_entity = get_object_or_404(
                LegalEntity, id=request.POST.get("legal_entity_id"), is_active=True
            )
            require_legal_entity_access(request.user, legal_entity, request=request)
            if not 1 <= month <= 12:
                raise ValueError
            with transaction.atomic():
                run = OfficePayrollRun.objects.create(
                    period_year=year,
                    period_month=month,
                    legal_entity=legal_entity,
                    created_by=request.user,
                )
                OfficePayrollDeductionPolicy.objects.get_or_create(year=year)
                seeded_count = 0
                for employee in OfficeEmployeeProfile.objects.filter(
                    active=True, employment_legal_entity=legal_entity
                ):
                    _get_or_create_seeded_office_payslip(run, employee)
                    seeded_count += 1
            log_action(actor=request.user, action="OFFICE_PAYROLL_RUN_CREATE", object_type="OfficePayrollRun", object_id=run.id, after={"year": year, "month": month, "legal_entity": legal_entity.code, "seeded_employee_count": seeded_count})
            return redirect(f"/app/hq/labor/office-payroll/{run.id}/")
        except (KeyError, ValueError):
            messages.error(request, "연도와 월을 확인해 주세요.")
        except Exception as exc:
            messages.error(request, str(exc))
    context = {
        "runs": OfficePayrollRun.objects.exclude(status=OfficePayrollStatus.VOID).filter(legal_entity__in=get_user_legal_entities(request.user)).select_related("legal_entity")[:36],
        "today": timezone.localdate(),
        "employees": OfficeEmployeeProfile.objects.filter(active=True, employment_legal_entity__in=get_user_legal_entities(request.user)).select_related("user", "employment_legal_entity"),
        "legal_entities": get_user_legal_entities(request.user),
    }
    return render(request, "app/hq/office_payroll_list_tax.html", context)


@login_required
def hq_office_payroll_account_new(request):
    """Create a least-privilege login account for an office employee."""
    require_role(request.user, [Role.HQ], request=request)
    if request.method == "POST":
        from django.contrib.auth import get_user_model
        from django.contrib.auth.password_validation import validate_password

        username = (request.POST.get("username") or "").strip()
        password = request.POST.get("password") or ""
        password_confirm = request.POST.get("password_confirm") or ""
        first_name = (request.POST.get("first_name") or "").strip()
        last_name = (request.POST.get("last_name") or "").strip()
        user_model = get_user_model()
        if not username:
            messages.error(request, "로그인 아이디를 입력해 주세요.")
        elif user_model.objects.filter(username=username).exists():
            messages.error(request, "이미 사용 중인 로그인 아이디입니다.")
        elif password != password_confirm:
            messages.error(request, "비밀번호와 비밀번호 확인이 일치하지 않습니다.")
        else:
            try:
                validate_password(password)
                with transaction.atomic():
                    account = user_model.objects.create_user(
                        username=username,
                        password=password,
                        first_name=first_name,
                        last_name=last_name,
                    )
                    # New office accounts are not granted HQ/CEO authority.  They can
                    # only access self-service data until a manager grants another role.
                    UserProfile.objects.get_or_create(user=account, defaults={"role": Role.FIELD})
                    log_action(
                        actor=request.user,
                        action="OFFICE_EMPLOYEE_LOGIN_CREATE",
                        object_type="User",
                        object_id=account.id,
                        after={"username": account.username},
                    )
                messages.success(request, "로그인 계정을 등록했습니다. 이어서 본사 직원으로 등록해 주세요.")
                return redirect("/app/hq/labor/office-payroll/")
            except ValidationError as exc:
                messages.error(request, " ".join(exc.messages))
    return render(request, "app/hq/office_payroll_account_new.html")


@login_required
def hq_office_payroll_deduction_policy_list(request):
    """HQ maintenance screen for annual, reviewable employee deduction defaults."""
    require_role(request.user, [Role.HQ], request=request)
    current_year = timezone.localdate().year
    selected_year = int(request.GET.get("year") or current_year)
    rate_fields = (
        "national_pension_rate",
        "health_insurance_rate",
        "long_term_care_rate",
        "employment_insurance_rate",
    )

    if request.method == "POST" and request.POST.get("action") == "save_child_tax_credit":
        try:
            child_credit_one = int(request.POST.get("child_credit_one") or 0)
            child_credit_two = int(request.POST.get("child_credit_two") or 0)
            child_credit_per_additional = int(request.POST.get("child_credit_per_additional") or 0)
            if min(child_credit_one, child_credit_two, child_credit_per_additional) < 0:
                raise ValidationError("자녀 세액공제액은 0원 이상으로 입력해 주세요.")
            with transaction.atomic():
                version = get_object_or_404(
                    IncomeTaxTableVersion.objects.select_for_update(),
                    id=request.POST.get("income_tax_table_version_id"),
                    is_active=True,
                )
                before = {
                    "child_credit_one": version.child_credit_one,
                    "child_credit_two": version.child_credit_two,
                    "child_credit_per_additional": version.child_credit_per_additional,
                }
                version.child_credit_one = child_credit_one
                version.child_credit_two = child_credit_two
                version.child_credit_per_additional = child_credit_per_additional
                version.save(
                    update_fields=[
                        "child_credit_one",
                        "child_credit_two",
                        "child_credit_per_additional",
                    ]
                )
            log_action(
                actor=request.user,
                action="OFFICE_PAYROLL_CHILD_TAX_CREDIT_UPDATE",
                object_type="IncomeTaxTableVersion",
                object_id=version.id,
                before=before,
                after={
                    "effective_from": version.effective_from.isoformat(),
                    "child_credit_one": child_credit_one,
                    "child_credit_two": child_credit_two,
                    "child_credit_per_additional": child_credit_per_additional,
                },
            )
            messages.success(request, "적용 중인 간이세액표의 자녀 세액공제 기준을 저장했습니다.")
            return redirect(f"/app/hq/labor/office-payroll/deduction-policies/?year={selected_year}")
        except (ValueError, ValidationError) as exc:
            messages.error(request, str(exc))

    if request.method == "POST":
        try:
            year = int(request.POST.get("year") or current_year)
            if not 2000 <= year <= 2100:
                raise ValidationError("적용 연도는 2000년부터 2100년 사이로 입력해 주세요.")
            posted_rates = {}
            for field in rate_fields:
                percent = Decimal((request.POST.get(field) or "0").strip())
                if not Decimal("0") <= percent <= Decimal("100"):
                    raise ValidationError("공제율은 0% 이상 100% 이하로 입력해 주세요.")
                posted_rates[field] = percent / Decimal("100")

            with transaction.atomic():
                policy, created = OfficePayrollDeductionPolicy.objects.select_for_update().get_or_create(year=year)
                before = None if created else {field: str(getattr(policy, field)) for field in rate_fields}
                for field, value in posted_rates.items():
                    setattr(policy, field, value)
                policy.save(update_fields=[*rate_fields, "updated_at"])
                log_action(
                    actor=request.user,
                    action="OFFICE_PAYROLL_DEDUCTION_POLICY_CREATE" if created else "OFFICE_PAYROLL_DEDUCTION_POLICY_UPDATE",
                    object_type="OfficePayrollDeductionPolicy",
                    object_id=policy.id,
                    before=before,
                    after={field: str(getattr(policy, field)) for field in rate_fields},
                )
            messages.success(request, f"{year}년 자동 공제 정책을 저장했습니다.")
            return redirect(f"/app/hq/labor/office-payroll/deduction-policies/?year={year}")
        except (InvalidOperation, ValueError, ValidationError) as exc:
            messages.error(request, str(exc))
            selected_year = int(request.POST.get("year") or current_year)

    policy = OfficePayrollDeductionPolicy.objects.filter(year=selected_year).first()
    if policy is None:
        policy = OfficePayrollDeductionPolicy(year=selected_year)
    rate_percentages = {field: (getattr(policy, field) * Decimal("100")) for field in rate_fields}
    return render(
        request,
        "app/hq/office_payroll_deduction_policy_list.html",
        {
            "policy": policy,
            "rate_percentages": rate_percentages,
            "policies": OfficePayrollDeductionPolicy.objects.all(),
            "selected_year": selected_year,
            "active_tax_table": IncomeTaxTableVersion.objects.filter(is_active=True).order_by("-effective_from").first(),
        },
    )


_PAYSLIP_AMOUNT_FIELDS = (
    "base_pay", "meal_allowance_pay", "fuel_allowance_pay", "site_allowance_pay", "overtime_pay", "bonus_pay",
    "income_tax", "local_income_tax", "national_pension", "health_insurance",
    "long_term_care", "employment_insurance", "other_deduction",
)
from .office_payroll_exports import payslip_pdf, payslip_workbook, payroll_pdf, payroll_workbook


def _office_payslip_snapshot(run):
    return [
        {
            "slip_id": slip.id,
            "employee_no": slip.employee.employee_no,
            "employee_name": slip.employee.user.get_full_name() or slip.employee.user.username,
            **{field: getattr(slip, field) for field in _PAYSLIP_AMOUNT_FIELDS},
            "gross_pay": slip.gross_pay,
            "total_deduction": slip.total_deduction,
            "net_pay": slip.net_pay,
        }
        for slip in run.slips.select_related("employee__user")
    ]


def _calculate_correction_snapshot(rows):
    calculated = []
    for row in rows:
        amounts = {field: int(row.get(field) or 0) for field in _PAYSLIP_AMOUNT_FIELDS}
        if any(value < 0 for value in amounts.values()):
            raise ValidationError("급여와 공제액은 0 이상이어야 합니다.")
        gross = sum(amounts[field] for field in _PAYSLIP_AMOUNT_FIELDS[:6])
        deduction = sum(amounts[field] for field in _PAYSLIP_AMOUNT_FIELDS[6:])
        calculated.append({
            "slip_id": int(row["slip_id"]),
            "employee_no": row["employee_no"],
            "employee_name": row["employee_name"],
            **amounts,
            "gross_pay": gross,
            "total_deduction": deduction,
            "net_pay": gross - deduction,
        })
    return calculated


def _normalized_correction_snapshot(correction):
    """Read legacy correction snapshots using the current payslip schema.

    Older requests stored a single ``allowance_pay`` value before meal, fuel,
    and site allowances were separated.  Preserve that amount as a site
    allowance and use the original slip for fields that did not exist yet.
    """
    slips_by_id = {
        slip.id: slip
        for slip in correction.run.slips.select_related("employee__user")
    }
    rows = []
    for row in correction.proposed_snapshot:
        slip = slips_by_id.get(int(row["slip_id"]))
        if slip is None:
            raise ValidationError("정정 요청의 원본 급여명세서를 찾을 수 없습니다.")
        amounts = {}
        for field in _PAYSLIP_AMOUNT_FIELDS:
            if field in row:
                amounts[field] = row[field]
            elif field == "site_allowance_pay" and "allowance_pay" in row:
                amounts[field] = row["allowance_pay"]
            else:
                amounts[field] = getattr(slip, field)
        rows.append(
            {
                "slip_id": slip.id,
                "employee_no": row.get("employee_no") or slip.employee.employee_no,
                "employee_name": row.get("employee_name") or slip.employee.user.get_full_name() or slip.employee.user.username,
                **amounts,
            }
        )
    return _calculate_correction_snapshot(rows)


@login_required
def hq_office_payroll_correction_new(request, run_id):
    require_role(request.user, [Role.HQ], request=request)
    run = get_object_or_404(OfficePayrollRun, id=run_id)
    if run.status not in {OfficePayrollStatus.APPROVED, OfficePayrollStatus.PAID}:
        messages.error(request, "확정 또는 지급 완료된 급여대장만 정정 요청으로 처리할 수 있습니다.")
        return redirect(f"/app/hq/labor/office-payroll/{run.id}/")
    snapshot = _office_payslip_snapshot(run)
    correction = OfficePayrollCorrection.objects.create(
        run=run,
        original_snapshot=snapshot,
        proposed_snapshot=snapshot,
        requested_by=request.user,
    )
    log_action(actor=request.user, action="OFFICE_PAYROLL_CORRECTION_CREATE", object_type="OfficePayrollCorrection", object_id=correction.id, after={"run_id": run.id, "status": correction.status})
    return redirect(f"/app/hq/labor/office-payroll/corrections/{correction.id}/")


@login_required
def hq_office_payroll_correction_detail(request, correction_id):
    require_role(request.user, [Role.HQ, Role.CEO], request=request)
    correction = get_object_or_404(OfficePayrollCorrection.objects.select_related("run", "requested_by", "approved_by"), id=correction_id)
    can_edit = correction.status in {OfficePayrollCorrectionStatus.DRAFT, OfficePayrollCorrectionStatus.REJECTED} and correction.requested_by_id == request.user.id
    can_approve = correction.status == OfficePayrollCorrectionStatus.SUBMITTED and correction.requested_by_id != request.user.id
    can_apply = correction.status == OfficePayrollCorrectionStatus.APPROVED and get_user_role(request.user) == Role.HQ
    correction_rows = _normalized_correction_snapshot(correction)
    if request.method == "POST":
        action = request.POST.get("action")
        try:
            if action == "delete":
                if correction.status != OfficePayrollCorrectionStatus.DRAFT or not can_edit:
                    raise PermissionDenied("임시저장 상태의 본인 정정 요청만 삭제할 수 있습니다.")
                correction_id, run_id = correction.id, correction.run_id
                correction.delete()
                log_action(
                    actor=request.user,
                    action="OFFICE_PAYROLL_CORRECTION_DELETE",
                    object_type="OfficePayrollCorrection",
                    object_id=correction_id,
                    before={"run_id": run_id, "status": OfficePayrollCorrectionStatus.DRAFT},
                    after={"deleted": True},
                )
                messages.success(request, "임시저장 급여 정정 요청을 삭제했습니다.")
                return redirect(f"/app/hq/labor/office-payroll/{run_id}/")
            if action in {"save", "submit"}:
                if not can_edit:
                    raise PermissionDenied("요청자만 임시저장 또는 제출할 수 있습니다.")
                proposed_rows = []
                for row in correction_rows:
                    proposed_rows.append({
                        **row,
                        **{field: int(str(request.POST.get(f"line-{row['slip_id']}-{field}", "0")).replace(",", "") or 0) for field in _PAYSLIP_AMOUNT_FIELDS},
                    })
                correction.proposed_snapshot = _calculate_correction_snapshot(proposed_rows)
                correction.reason = (request.POST.get("reason") or "").strip()
                if action == "submit":
                    if not correction.reason:
                        raise ValidationError("정정 사유를 입력해 주세요.")
                    correction.status, correction.submitted_at = OfficePayrollCorrectionStatus.SUBMITTED, timezone.now()
                else:
                    correction.status = OfficePayrollCorrectionStatus.DRAFT
                correction.save(update_fields=["proposed_snapshot", "reason", "status", "submitted_at", "updated_at"])
                log_action(actor=request.user, action=f"OFFICE_PAYROLL_CORRECTION_{action.upper()}", object_type="OfficePayrollCorrection", object_id=correction.id, after={"status": correction.status})
                messages.success(request, "정정 요청을 제출했습니다." if action == "submit" else "정정 요청을 임시저장했습니다.")
                return redirect(f"/app/hq/labor/office-payroll/corrections/{correction.id}/")
            if action == "approve":
                if not can_approve:
                    raise PermissionDenied("요청자와 다른 HQ 또는 CEO만 승인할 수 있습니다.")
                correction.status, correction.approved_by, correction.approved_at = OfficePayrollCorrectionStatus.APPROVED, request.user, timezone.now()
                correction.save(update_fields=["status", "approved_by", "approved_at", "updated_at"])
                log_action(actor=request.user, action="OFFICE_PAYROLL_CORRECTION_APPROVE", object_type="OfficePayrollCorrection", object_id=correction.id, after={"status": correction.status})
                messages.success(request, "급여 정정 요청을 승인했습니다. HQ가 적용 처리할 수 있습니다.")
                return redirect(f"/app/hq/labor/office-payroll/corrections/{correction.id}/")
            if action == "reject":
                if not can_approve:
                    raise PermissionDenied("요청자와 다른 HQ 또는 CEO만 반려할 수 있습니다.")
                correction.status = OfficePayrollCorrectionStatus.REJECTED
                correction.rejection_reason = (request.POST.get("rejection_reason") or "").strip()
                correction.save(update_fields=["status", "rejection_reason", "updated_at"])
                log_action(actor=request.user, action="OFFICE_PAYROLL_CORRECTION_REJECT", object_type="OfficePayrollCorrection", object_id=correction.id, after={"status": correction.status})
                messages.success(request, "급여 정정 요청을 반려했습니다.")
                return redirect(f"/app/hq/labor/office-payroll/corrections/{correction.id}/")
            if action == "apply":
                if not can_apply:
                    raise PermissionDenied("승인 완료된 정정 요청만 HQ가 적용할 수 있습니다.")
                with transaction.atomic():
                    correction = OfficePayrollCorrection.objects.select_for_update().get(id=correction.id)
                    if correction.status != OfficePayrollCorrectionStatus.APPROVED:
                        raise ValidationError("이미 처리되었거나 적용할 수 없는 정정 요청입니다.")
                    for row in _normalized_correction_snapshot(correction):
                        slip = OfficePayslip.objects.select_for_update().get(id=row["slip_id"], run=correction.run)
                        for field in _PAYSLIP_AMOUNT_FIELDS:
                            setattr(slip, field, int(row[field]))
                        slip.save()
                    correction.status, correction.applied_by, correction.applied_at = OfficePayrollCorrectionStatus.APPLIED, request.user, timezone.now()
                    correction.save(update_fields=["status", "applied_by", "applied_at", "updated_at"])
                log_action(actor=request.user, action="OFFICE_PAYROLL_CORRECTION_APPLY", object_type="OfficePayrollCorrection", object_id=correction.id, before={"original": correction.original_snapshot}, after={"proposed": correction.proposed_snapshot, "status": correction.status})
                messages.success(request, "승인된 급여 정정을 적용했습니다. 지급 완료 건은 차액 지급·환수 업무를 별도로 확인해 주세요.")
                return redirect(f"/app/hq/labor/office-payroll/{correction.run_id}/")
            raise ValidationError("처리 방식을 확인해 주세요.")
        except (PermissionDenied, ValidationError, ValueError) as exc:
            messages.error(request, str(exc))
    return render(request, "app/hq/office_payroll_correction_detail.html", {"correction": correction, "correction_rows": correction_rows, "can_edit": can_edit, "can_approve": can_approve, "can_apply": can_apply})


def _office_payroll_export_run(request, run_id):
    require_role(request.user, [Role.HQ], request=request)
    run = get_object_or_404(OfficePayrollRun, id=run_id)
    if run.status not in {OfficePayrollStatus.APPROVED, OfficePayrollStatus.PAID}:
        raise PermissionDenied("확정 또는 지급 완료된 급여대장만 공식 파일로 다운로드할 수 있습니다.")
    return run


@login_required
def hq_office_payroll_download(request, run_id, file_format):
    run = _office_payroll_export_run(request, run_id)
    if file_format == "xlsx":
        stream, content_type, filename = payroll_workbook(run), "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet", f"office-payroll-{run.period_year}{run.period_month:02d}.xlsx"
    elif file_format == "pdf":
        stream, content_type, filename = payroll_pdf(run), "application/pdf", f"office-payroll-{run.period_year}{run.period_month:02d}.pdf"
    else:
        raise Http404
    log_action(actor=request.user, action="OFFICE_PAYROLL_EXPORT", object_type="OfficePayrollRun", object_id=run.id, after={"format": file_format, "scope": "payroll_register"})
    return FileResponse(stream, as_attachment=True, filename=filename, content_type=content_type)


@login_required
def hq_office_payslip_download(request, run_id, slip_id, file_format):
    run = _office_payroll_export_run(request, run_id)
    slip = get_object_or_404(OfficePayslip.objects.select_related("employee__user"), id=slip_id, run=run)
    if file_format == "xlsx":
        stream, content_type, filename = payslip_workbook(run, slip), "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet", f"office-payslip-{run.period_year}{run.period_month:02d}-{slip.id}.xlsx"
    elif file_format == "pdf":
        stream, content_type, filename = payslip_pdf(run, slip), "application/pdf", f"office-payslip-{run.period_year}{run.period_month:02d}-{slip.id}.pdf"
    else:
        raise Http404
    log_action(actor=request.user, action="OFFICE_PAYSLIP_EXPORT", object_type="OfficePayslip", object_id=slip.id, after={"format": file_format, "run_id": run.id})
    return FileResponse(stream, as_attachment=True, filename=filename, content_type=content_type)


@login_required
def hq_office_payroll_detail(request, run_id):
    require_role(request.user, [Role.HQ], request=request)
    run = get_object_or_404(OfficePayrollRun.objects.select_related("legal_entity"), id=run_id)
    require_legal_entity_access(request.user, run.legal_entity, request=request)
    policy, _ = OfficePayrollDeductionPolicy.objects.get_or_create(year=run.period_year)
    editable = run.status in {OfficePayrollStatus.DRAFT, OfficePayrollStatus.REJECTED}

    def _void_block_reason(payroll_run):
        if payroll_run.status == OfficePayrollStatus.PAID:
            return "지급 완료된 급여대장은 삭제할 수 없습니다. 급여 정정 절차를 이용해 주세요."
        if payroll_run.status == OfficePayrollStatus.VOID:
            return "이미 폐기된 급여대장입니다."
        if PayrollAllocationBatch.objects.filter(office_payroll_run=payroll_run).exists():
            return "프로젝트 급여 배부와 연결된 급여대장은 삭제할 수 없습니다. 배부 정정 절차를 이용해 주세요."
        if payroll_run.corrections.exclude(status=OfficePayrollCorrectionStatus.DRAFT).exists():
            return "승인 절차가 시작된 급여 정정 요청이 있어 급여대장을 삭제할 수 없습니다."
        return ""

    def _set_posted_payslip_values(slip, fields):
        for field in fields:
            value = str(request.POST.get(f"slip-{slip.id}-{field}", "0")).replace(",", "").strip()
            setattr(slip, field, int(value or 0))

    def _detail_context(slips=None, preview_calculated=False):
        void_block_reason = _void_block_reason(run)
        return {
            "run": run,
            "policy": policy,
            "slips": slips if slips is not None else run.slips.select_related("employee__user"),
            "employees": OfficeEmployeeProfile.objects.filter(
                active=True,
                employment_legal_entity=run.legal_entity,
            ).exclude(payslips__run=run),
            "editable": editable,
            "can_void": not void_block_reason,
            "void_block_reason": void_block_reason,
            "preview_calculated": preview_calculated,
            "corrections": OfficePayrollCorrection.objects.filter(run=run)
            .exclude(status=OfficePayrollCorrectionStatus.APPLIED)
            .select_related("requested_by", "approved_by")
            .order_by("-id"),
        }

    if request.method == "POST":
        action = request.POST.get("action")
        try:
            if not editable and action not in {"withdraw_submission", "approve", "paid", "void"}:
                raise PermissionDenied("확정 또는 지급 완료된 급여대장은 정정 절차 없이 수정할 수 없습니다.")
            if action == "void":
                reason = (request.POST.get("void_reason") or "").strip()
                if not reason:
                    raise ValidationError("급여대장 폐기 사유를 입력해 주세요.")
                with transaction.atomic():
                    locked_run = OfficePayrollRun.objects.select_for_update().get(id=run.id)
                    block_reason = _void_block_reason(locked_run)
                    if block_reason:
                        raise ValidationError(block_reason)
                    before = {"status": locked_run.status, "note": locked_run.note}
                    locked_run.status = OfficePayrollStatus.VOID
                    locked_run.voided_by = request.user
                    locked_run.voided_at = timezone.now()
                    locked_run.note = (locked_run.note + "\n" if locked_run.note else "") + f"[폐기 사유] {reason}"
                    locked_run.save(update_fields=["status", "voided_by", "voided_at", "note", "updated_at"])
                log_action(
                    actor=request.user,
                    action="OFFICE_PAYROLL_RUN_VOID",
                    object_type="OfficePayrollRun",
                    object_id=run.id,
                    before=before,
                    after={"status": OfficePayrollStatus.VOID, "reason": reason},
                )
                messages.success(request, "급여대장을 폐기했습니다. 목록에서는 제거되며, 같은 월 급여대장을 새로 만들 수 있습니다.")
                return redirect("/app/hq/labor/office-payroll/")
            if action == "add_employee":
                employee = get_object_or_404(
                    OfficeEmployeeProfile,
                    id=request.POST.get("employee_id"),
                    active=True,
                    employment_legal_entity=run.legal_entity,
                )
                _get_or_create_seeded_office_payslip(run, employee)
            elif action == "recalculate":
                # This is a preview: persist neither earnings nor deductions until HQ
                # reviews the calculated values and deliberately chooses "수정 저장".
                preview_slips = list(run.slips.select_related("employee__user"))
                for slip in preview_slips:
                    _set_posted_payslip_values(
                        slip,
                        ("base_pay", "meal_allowance_pay", "fuel_allowance_pay", "site_allowance_pay", "overtime_pay", "bonus_pay", "other_deduction"),
                    )
                    slip.apply_auto_deductions(policy)
                    slip.recalculate_totals()
                messages.info(request, "공제 자동계산 결과입니다. 금액을 검토·수정한 뒤 ‘수정 저장’을 눌러 확정해 주세요.")
                return render(
                    request,
                    "app/hq/office_payroll_detail_new.html",
                    _detail_context(slips=preview_slips, preview_calculated=True),
                )
            elif action == "save":
                for slip in run.slips.all():
                    _set_posted_payslip_values(
                        slip,
                        ("base_pay", "meal_allowance_pay", "fuel_allowance_pay", "site_allowance_pay", "overtime_pay", "bonus_pay", "income_tax", "local_income_tax", "national_pension", "health_insurance", "long_term_care", "employment_insurance", "other_deduction"),
                    )
                    # A saved calculation preview must retain the official tax-table
                    # inputs (including the employee's 80/100/120% choice), even
                    # when HQ subsequently fine-tunes a displayed deduction amount.
                    if request.POST.get("save_auto_calculation_snapshot") == "1":
                        entered_deductions = {
                            field: getattr(slip, field)
                            for field in (
                                "income_tax", "local_income_tax", "national_pension",
                                "health_insurance", "long_term_care",
                                "employment_insurance", "other_deduction",
                            )
                        }
                        slip.apply_auto_deductions(policy)
                        for field, value in entered_deductions.items():
                            setattr(slip, field, value)
                    slip.save()
            elif action == "submit":
                if not run.slips.exists():
                    raise ValidationError("급여명세서를 한 건 이상 등록해 주세요.")
                run.status, run.submitted_at = OfficePayrollStatus.SUBMITTED, timezone.now()
                run.save(update_fields=["status", "submitted_at", "updated_at"])
            elif action == "withdraw_submission":
                if run.status != OfficePayrollStatus.SUBMITTED:
                    raise ValidationError("검토 대기 상태의 급여대장만 검토 요청을 회수할 수 있습니다.")
                run.status, run.submitted_at = OfficePayrollStatus.DRAFT, None
                run.save(update_fields=["status", "submitted_at", "updated_at"])
            elif action == "approve":
                if run.status != OfficePayrollStatus.SUBMITTED:
                    raise ValidationError("검토 대기 상태의 급여대장만 확정할 수 있습니다.")
                run.status, run.approved_by, run.approved_at = OfficePayrollStatus.APPROVED, request.user, timezone.now()
                run.save(update_fields=["status", "approved_by", "approved_at", "updated_at"])
            elif action == "paid":
                if run.status != OfficePayrollStatus.APPROVED:
                    raise ValidationError("확정된 급여대장만 지급 완료할 수 있습니다.")
                run.status, run.paid_at = OfficePayrollStatus.PAID, timezone.now()
                run.save(update_fields=["status", "paid_at", "updated_at"])
            elif action == "create_project_allocation":
                if run.status not in {OfficePayrollStatus.APPROVED, OfficePayrollStatus.PAID}:
                    raise ValidationError("확정된 본사 급여대장만 프로젝트 배부를 시작할 수 있습니다.")
                existing = PayrollAllocationBatch.objects.filter(
                    legal_entity=run.legal_entity,
                    period_year=run.period_year,
                    period_month=run.period_month,
                ).first()
                if existing and existing.office_payroll_run_id != run.id:
                    raise ValidationError("해당 월의 다른 급여 배부가 이미 존재합니다. 급여대장을 통합하거나 기존 배부를 정정해 주세요.")
                batch = existing or create_payroll_batch(
                    year=run.period_year, month=run.period_month, total_amount=run.gross_total,
                    legal_entity=run.legal_entity,
                    actor=request.user, note=f"본사 급여대장 #{run.id} 연계 배부",
                )
                if batch.total_amount != run.gross_total:
                    raise ValidationError("급여 배부 총액이 확정 본사 급여 총지급액과 다릅니다.")
                batch.office_payroll_run = run
                batch.save(update_fields=["office_payroll_run", "updated_at"])
                log_action(actor=request.user, action="OFFICE_PAYROLL_PROJECT_ALLOCATION_STARTED", object_type="OfficePayrollRun", object_id=run.id, after={"allocation_batch_id": batch.id, "gross_total": run.gross_total})
                return redirect(f"/app/hq/labor/payroll-allocation/{batch.id}/")
            else:
                raise ValidationError("처리 방식을 확인해 주세요.")
            log_action(actor=request.user, action=f"OFFICE_PAYROLL_{str(action).upper()}", object_type="OfficePayrollRun", object_id=run.id, after={"status": run.status})
            messages.success(request, "본사 급여대장을 저장했습니다.")
            return redirect(f"/app/hq/labor/office-payroll/{run.id}/")
        except (PermissionDenied, ValidationError, ValueError) as exc:
            messages.error(request, str(exc))
    return render(request, "app/hq/office_payroll_detail_new.html", _detail_context())


@login_required
def my_office_payslips(request):
    """Employee self-service: only the authenticated employee's finalized slips."""
    profile = get_object_or_404(OfficeEmployeeProfile, user=request.user, active=True)
    slips = OfficePayslip.objects.filter(
        employee=profile,
        run__status__in=[OfficePayrollStatus.APPROVED, OfficePayrollStatus.PAID],
    ).select_related("run").order_by("-run__period_year", "-run__period_month")
    selected = slips.filter(id=request.GET.get("slip_id")).first() if request.GET.get("slip_id") else slips.first()
    if selected and selected.issued_at is None:
        selected.issued_at = timezone.now()
        selected.save(update_fields=["issued_at", "updated_at"])
        log_action(actor=request.user, action="OFFICE_PAYSLIP_SELF_VIEW", object_type="OfficePayslip", object_id=selected.id, after={"issued": True})
    return render(request, "app/my_payslips.html", {"slips": slips, "selected": selected})


@login_required
def my_office_payslip_download(request, slip_id, file_format):
    profile = get_object_or_404(OfficeEmployeeProfile, user=request.user, active=True)
    slip = get_object_or_404(
        OfficePayslip.objects.select_related("run", "employee__user"),
        id=slip_id,
        employee=profile,
        run__status__in=[OfficePayrollStatus.APPROVED, OfficePayrollStatus.PAID],
    )
    if file_format == "xlsx":
        stream, content_type, filename = payslip_workbook(slip.run, slip), "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet", f"my-payslip-{slip.run.period_year}{slip.run.period_month:02d}.xlsx"
    elif file_format == "pdf":
        stream, content_type, filename = payslip_pdf(slip.run, slip), "application/pdf", f"my-payslip-{slip.run.period_year}{slip.run.period_month:02d}.pdf"
    else:
        raise Http404
    log_action(actor=request.user, action="OFFICE_PAYSLIP_SELF_EXPORT", object_type="OfficePayslip", object_id=slip.id, after={"format": file_format})
    return FileResponse(stream, as_attachment=True, filename=filename, content_type=content_type)
