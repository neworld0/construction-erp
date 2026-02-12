import logging
from datetime import date

from django.contrib import messages
from django.contrib.auth.decorators import login_required
from django.core.exceptions import PermissionDenied, ValidationError
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

from .forms import LaborRateForm, LaborRoleForm, PayrollBatchForm
from .models import (
    LaborRateTable,
    LaborRole,
    PayrollAllocationBatch,
    PayrollAllocationLine,
    PayrollAllocationStatus,
    Timesheet,
    TimesheetStatus,
)
from .services import (
    approve_timesheet,
    create_labor_role,
    create_rate,
    create_timesheet,
    create_payroll_batch,
    reject_timesheet,
    submit_timesheet,
    update_labor_role,
    update_rate,
    upsert_timesheet_lines,
    submit_payroll_batch,
    update_payroll_batch,
    upsert_payroll_lines,
    validate_payroll_batch,
)

logger = logging.getLogger(__name__)


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
        "app/hq/payroll_list.html",
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
                return redirect(f"/app/hq/labor/payroll/{batch.id}/")
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
                return redirect(f"/app/hq/labor/payroll/{batch.id}/")
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
