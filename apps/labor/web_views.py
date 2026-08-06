import logging
from datetime import date

from django.contrib import messages
from django.contrib.auth.decorators import login_required
from django.core.exceptions import PermissionDenied, ValidationError
from django.http import FileResponse, Http404
from django.db import models
from django.db.models import Q
from django.shortcuts import get_object_or_404, redirect, render

from apps.evidence.attachment_policy import can_edit_attachments
from apps.evidence.models import Evidence
from apps.evidence.services.resolve import is_project_or_month_locked
from apps.core.rbac.models import ProjectAssignment, Role
from apps.core.rbac.permissions import get_user_role, require_project_access, require_role
from apps.cost.models import CostItem
from apps.projects.models import Project

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
    create_payroll_batch,
    create_worker_master,
    reject_timesheet,
    submit_timesheet,
    parse_electronic_card_import_batch,
    reconcile_electronic_card_import_batch,
    register_labor_excel_export_download,
    resolve_labor_reconciliation_result,
    update_labor_role,
    update_labor_reporting_project,
    update_labor_work_ledger,
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
    qs = (
        LaborRateTable.objects.select_related("labor_role", "project")
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
    if active in ("0", "1"):
        qs = qs.filter(is_active=active == "1")
    roles = LaborRole.objects.order_by("code")
    projects = Project.objects.order_by("name")
    return render(
        request,
        "app/hq/master_labor_rate_list.html",
        {
            "rates": qs,
            "roles": roles,
            "projects": projects,
            "q": q,
            "active": active or "",
            "role_id": role_id or "",
            "project_id": project_id or "",
        },
    )


@login_required
def hq_labor_rate_new(request):
    require_role(request.user, [Role.HQ, Role.CEO], request=request)
    if request.method == "POST":
        form = LaborRateForm(request.POST)
        if form.is_valid():
            try:
                create_rate(form.cleaned_data, actor=request.user)
                messages.success(request, "\ub2e8\uac00\uac00 \ub4f1\ub85d\ub418\uc5c8\uc2b5\ub2c8\ub2e4.")
                return redirect("/app/hq/master/labor/rates/")
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
                return redirect("/app/hq/master/labor/rates/")
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
    return redirect("/app/hq/master/labor/rates/")


def _get_assigned_projects(user):
    return Project.objects.filter(
        projectassignment__user=user, projectassignment__is_active=True
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
        role_id = post_data.get(f"lines-{idx}-role_id")
        headcount = post_data.get(f"lines-{idx}-headcount")
        hours = post_data.get(f"lines-{idx}-hours")
        rate_type = post_data.get(f"lines-{idx}-rate_type") or "DAY"
        memo = post_data.get(f"lines-{idx}-memo") or ""
        if not role_id and not headcount and not hours and not memo:
            continue
        lines.append(
            {
                "labor_role_id": role_id,
                "headcount": headcount,
                "hours": hours,
                "rate_type": rate_type,
                "memo": memo,
            }
        )
    return lines


@login_required
def field_timesheet_list(request):
    require_role(request.user, [Role.FIELD], request=request)
    projects = _get_assigned_projects(request.user)
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
    projects = _get_assigned_projects(request.user)
    if not projects.exists():
        messages.error(request, "\ubc30\uc815\ub41c \ud504\ub85c\uc81d\ud2b8\uac00 \uc5c6\uc2b5\ub2c8\ub2e4.")
        return render(request, "app/field/timesheet_form.html", {"projects": []})
    timesheet = None
    if timesheet_id:
        timesheet = get_object_or_404(
            Timesheet.objects.select_related("project").prefetch_related("lines", "lines__labor_role"),
            id=timesheet_id,
            created_by=request.user,
        )
    roles = LaborRole.objects.filter(is_active=True).order_by("sort_order", "code")
    line_rows = []
    if timesheet:
        for line in timesheet.lines.all():
            line_rows.append(
                {
                    "role_id": line.labor_role_id,
                    "headcount": line.headcount,
                    "hours": line.hours,
                    "rate_type": line.rate_type,
                    "memo": line.memo,
                }
            )
    while len(line_rows) < 8:
        line_rows.append(
            {"role_id": "", "headcount": "", "hours": "", "rate_type": "DAY", "memo": ""}
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
                else:
                    timesheet.note = note
                    timesheet.save(update_fields=["note", "updated_at"])
                lines_payload = _build_lines_payload_from_post(request.POST)
                upsert_timesheet_lines(
                    timesheet=timesheet, lines_payload=lines_payload, actor=request.user
                )
                if action == "submit":
                    submit_timesheet(timesheet=timesheet, actor=request.user)
                    messages.success(
                        request,
                        "\ucd9c\uc5ed\ubd80\uac00 \uc81c\ucd9c\ub418\uc5c8\uc2b5\ub2c8\ub2e4. \uc2b9\uc778 \ub300\uae30 \uc0c1\ud0dc\uc785\ub2c8\ub2e4.",
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
                messages.error(request, message)
    form_disabled = timesheet and timesheet.status in (
        TimesheetStatus.SUBMITTED,
        TimesheetStatus.APPROVED,
    )
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
            "line_rows": line_rows,
            "form_disabled": form_disabled,
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
    qs = PayrollAllocationBatch.objects.order_by("-period_year", "-period_month", "-id")
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
        form = PayrollBatchForm(request.POST)
        if form.is_valid():
            try:
                batch = create_payroll_batch(
                    year=form.cleaned_data["period_year"],
                    month=form.cleaned_data["period_month"],
                    total_amount=form.cleaned_data["total_amount"],
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
        form = PayrollBatchForm()
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
            "projects": Project.objects.order_by("name"),
            "cost_items": CostItem.objects.filter(is_active=True).order_by("code"),
        },
    )


@login_required
def hq_payroll_detail(request, batch_id):
    require_role(request.user, [Role.HQ, Role.CEO], request=request)
    batch = get_object_or_404(PayrollAllocationBatch, id=batch_id)
    lines = list(
        PayrollAllocationLine.objects.select_related("project", "cbs")
        .filter(batch=batch)
        .order_by("id")
    )
    if request.method == "POST":
        form = PayrollBatchForm(request.POST, instance=batch)
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
        form = PayrollBatchForm(instance=batch)
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
            "projects": Project.objects.order_by("name"),
            "cost_items": CostItem.objects.filter(is_active=True).order_by("code"),
            "form_disabled": batch.status
            in (PayrollAllocationStatus.SUBMITTED, PayrollAllocationStatus.APPROVED),
        },
    )
