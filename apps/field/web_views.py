from __future__ import annotations

from datetime import date, datetime, timedelta
from decimal import Decimal, InvalidOperation, ROUND_HALF_UP

from django.contrib import messages
from django.contrib.auth.decorators import login_required
from django.core.exceptions import PermissionDenied, ValidationError
from django.core.paginator import Paginator
from django.db import DataError, IntegrityError, transaction
from django.db.models import Count, Q
from django.http import JsonResponse
from django.shortcuts import get_object_or_404, redirect, render
from django.utils import timezone

from apps.closing.guards import guard_write

from apps.audit.constants import DRAFT_SAVE, EVIDENCE_CREATE, EVIDENCE_FILE_ADD, SUBMIT
from apps.audit.services.logger import log_action
from apps.core.models import ApprovalRequest, ApprovalStatus
from apps.core.rbac.models import Role
from apps.core.rbac.permissions import get_current_legal_entity, get_user_legal_entities, get_user_role, require_project_access, require_role
from apps.cost.models import CostActual, CostActualLine, CostActualStatus, CostItem, CostVATTreatment
from apps.evidence.attachment_policy import can_edit_attachments
from apps.evidence.models import Evidence, EvidenceFile, EvidenceStatus
from apps.evidence.services.resolve import is_project_or_month_locked
from apps.reports.models import FieldReport, FieldReportStatus
from apps.field.models import (
    DailyReport,
    DailyReportLine,
    DailyReportStatus,
    RetroactiveEntryRequest,
    RetroactiveEntryRequestStatus,
)
from apps.field.retro_progress import (
    approve_retroactive_progress_request,
    consume_retroactive_progress_request,
    create_retroactive_progress_request,
    get_retroactive_progress_request,
    reject_retroactive_progress_request,
    require_approved_retroactive_progress_request,
    requires_retroactive_progress_authorization,
)
from apps.projects.models import Project, WBSItem
from apps.projects.test_date_window import (
    allows_future_operational_test_date,
    allows_operational_test_date,
    get_active_test_date_window,
)
from apps.projects.wbs_change import render_wbs_change_form
from apps.schedule.models import DailyProgress, SchedulePlan, ScheduleTask, ProgressCorrectionType
from apps.schedule.progress_corrections import create_progress_correction


_LOCKED_STATUSES = {"SUBMITTED", "APPROVED", "FINAL", "LOCKED", "CLOSED"}


def _get_accessible_projects(user):
    role = get_user_role(user)
    if role in (Role.CEO, Role.HQ):
        return Project.objects.filter(legal_entity__in=get_user_legal_entities(user)).order_by("name")
    if role == Role.FIELD:
        return Project.objects.filter(
            projectassignment__user=user,
            projectassignment__is_active=True,
            legal_entity__in=get_user_legal_entities(user),
        ).order_by("name")
    return Project.objects.none()


def _resolve_project(user, project_id):
    if not project_id:
        return None
    require_project_access(user, project_id)
    return Project.objects.filter(id=project_id).first()


def _require_current_entity_project(request, project):
    require_project_access(request.user, project.id)
    current_legal_entity = get_current_legal_entity(request)
    if current_legal_entity is None or project.legal_entity_id != current_legal_entity.id:
        raise PermissionDenied("선택한 운영 법인의 프로젝트만 처리할 수 있습니다.")


def _forbidden(_request):
    raise PermissionDenied("Access denied.")


def _can_edit_progress(user, project):
    role = get_user_role(user)
    if role in (Role.CEO, Role.HQ):
        return True
    if role != Role.FIELD or project is None:
        return False
    return Project.objects.filter(
        id=project.id,
        projectassignment__user=user,
        projectassignment__is_active=True,
    ).exists()


def _get_progress_wbs_queryset(project):
    if project is None:
        return WBSItem.objects.none()
    qs = WBSItem.objects.filter(project=project, is_baseline=True).order_by(
        "sort_order", "id"
    )
    if qs.exists():
        return qs
    return WBSItem.objects.filter(project=project).order_by("sort_order", "id")


def _format_progress_task_label(task):
    prefix = f"{task.sort_order}. " if getattr(task, "sort_order", 0) else ""
    weight = getattr(task, "weight_percent", None)
    if weight not in (None, ""):
        return f"{prefix}{task.name} / {weight}%"
    return f"{prefix}{task.name}"


def _decorate_progress_tasks(tasks):
    for task in tasks:
        task.display_name = _format_progress_task_label(task)
    return tasks


def _ensure_progress_tasks_for_project(project):
    if project is None:
        return None, []

    plan = SchedulePlan.objects.filter(project=project, is_active=True).first()
    if plan is not None:
        active_tasks = list(
            ScheduleTask.objects.filter(plan=plan, is_active=True).order_by(
                "sort_order", "id"
            )
        )
        if active_tasks:
            return plan, _decorate_progress_tasks(active_tasks)

    wbs_items = list(_get_progress_wbs_queryset(project))
    if not wbs_items:
        if plan is not None:
            existing_tasks = list(
                ScheduleTask.objects.filter(plan=plan).order_by("sort_order", "id")
            )
            if existing_tasks:
                return plan, _decorate_progress_tasks(existing_tasks)
        return plan, []

    with transaction.atomic():
        plan = SchedulePlan.objects.filter(project=project, is_active=True).first()
        if plan is None:
            latest_version = (
                SchedulePlan.objects.filter(project=project)
                .order_by("-version_no")
                .values_list("version_no", flat=True)
                .first()
                or 0
            )
            plan = SchedulePlan.objects.create(
                project=project,
                version_no=latest_version + 1,
                name="WBS Baseline",
                is_active=True,
            )

        if not ScheduleTask.objects.filter(plan=plan).exists():
            ScheduleTask.objects.bulk_create(
                [
                    ScheduleTask(
                        plan=plan,
                        name=wbs.name,
                        start_date=wbs.plan_start_date or project.start_date,
                        end_date=wbs.plan_end_date or project.end_date,
                        weight_percent=wbs.weight or Decimal("0"),
                        sort_order=wbs.sort_order or index,
                        is_active=True,
                    )
                    for index, wbs in enumerate(wbs_items, start=1)
                ]
            )

    tasks = list(
        ScheduleTask.objects.filter(plan=plan, is_active=True).order_by(
            "sort_order", "id"
        )
    )
    if not tasks:
        tasks = list(ScheduleTask.objects.filter(plan=plan).order_by("sort_order", "id"))
    return plan, _decorate_progress_tasks(tasks)


def _parse_decimal(value, default=Decimal("0")):
    try:
        return Decimal(value)
    except (InvalidOperation, TypeError):
        return default


def _normalize_progress_percent(value):
    if value is None:
        return None
    try:
        return value.quantize(Decimal("0.1"), rounding=ROUND_HALF_UP)
    except (InvalidOperation, AttributeError):
        return None


def _validate_progress_monotonic(project, task, target_date, value, reporter):
    if project is None or task is None or target_date is None or value is None:
        return None
    today = date.today()
    yesterday = today - timedelta(days=1)
    if target_date == today:
        yesterday_max = (
            DailyProgress.objects.filter(
                project=project,
                task=task,
                report_date=yesterday,
                reporter=reporter,
            )
            .exclude(progress_percent=None)
            .order_by("-progress_percent")
            .values_list("progress_percent", flat=True)
            .first()
        )
        if yesterday_max is not None and float(value) < float(yesterday_max):
            return "어제 진행률보다 낮게 입력할 수 없습니다."
    if target_date == yesterday:
        today_max = (
            DailyProgress.objects.filter(
                project=project,
                task=task,
                report_date=today,
                reporter=reporter,
            )
            .exclude(progress_percent=None)
            .order_by("-progress_percent")
            .values_list("progress_percent", flat=True)
            .first()
        )
        if today_max is not None and float(value) > float(today_max):
            return "오늘 진행률보다 높게 입력할 수 없습니다."
    return None


def _parse_int_amount(value):
    if value is None:
        return None
    digits = "".join(ch for ch in str(value) if ch.isdigit())
    if not digits:
        return None
    return Decimal(digits)


def _parse_decimal_amount(value):
    if value is None:
        return None
    cleaned = str(value).replace(",", "").strip()
    if not cleaned:
        return None
    try:
        return Decimal(cleaned)
    except (InvalidOperation, TypeError):
        return None


def _is_approval_approved(object_type, object_id) -> bool:
    return ApprovalRequest.objects.filter(
        object_type=object_type,
        object_id=object_id,
        status=ApprovalStatus.APPROVED,
    ).exists()


def _window_page_range(page_obj, window=2):
    if page_obj is None:
        return []
    start = max(page_obj.number - window, 1)
    end = min(page_obj.number + window, page_obj.paginator.num_pages)
    return list(range(start, end + 1))


def _dedupe_project_evidence(evidence):
    if evidence is None or evidence.object_type != "PROJECT":
        return
    Evidence.objects.filter(
        object_type="PROJECT",
        object_id=evidence.object_id,
        created_by=evidence.created_by,
        status__in=[EvidenceStatus.DRAFT, EvidenceStatus.SUBMITTED],
    ).exclude(id=evidence.id).delete()


def _upsert_progress_evidence(progress, request, file_obj):
    if progress is None or file_obj is None:
        return None

    is_closed_locked = is_project_or_month_locked(
        project=progress.project,
        target_date=progress.report_date,
    )
    if not can_edit_attachments(status=progress.status, is_closed_locked=is_closed_locked):
        return "제출/승인/마감 상태에서는 첨부를 수정할 수 없습니다."

    evidence = Evidence.objects.filter(
        object_type="DAILY_PROGRESS",
        object_id=progress.id,
        created_by=request.user,
    ).order_by("-created_at").first()

    if evidence is not None and evidence.status != EvidenceStatus.DRAFT:
        evidence = None

    if evidence is None:
        evidence = Evidence.objects.create(
            title=f"진행률 증빙 - {progress.report_date}",
            description=(progress.note or "").strip(),
            object_type="DAILY_PROGRESS",
            object_id=progress.id,
            status=EvidenceStatus.DRAFT,
            created_by=request.user,
        )
        log_action(
            actor=request.user,
            action=EVIDENCE_CREATE,
            object_type="EVIDENCE",
            object_id=evidence.id,
            project=progress.project,
            request=request,
            after={"status": evidence.status, "object_type": evidence.object_type},
        )

    evidence_file = EvidenceFile.objects.create(
        evidence=evidence,
        file=file_obj,
        original_name=file_obj.name,
        content_type=getattr(file_obj, "content_type", "") or "application/octet-stream",
        size_bytes=file_obj.size,
        sha256="",
        created_by=request.user,
    )

    log_action(
        actor=request.user,
        action=EVIDENCE_FILE_ADD,
        object_type="EVIDENCE_FILE",
        object_id=evidence_file.id,
        project=progress.project,
        request=request,
        after={"file_id": evidence_file.id},
        meta={
            "original_name": evidence_file.original_name,
            "size_bytes": evidence_file.size_bytes,
            "content_type": evidence_file.content_type,
            "sha256": evidence_file.sha256,
        },
    )
    return None


def _upsert_progress_evidence_files(progress, request, file_objs):
    if progress is None:
        return None
    for file_obj in file_objs or []:
        if file_obj is None:
            continue
        error = _upsert_progress_evidence(progress, request, file_obj)
        if error:
            return error
    return None


def _delete_progress_evidence_file(progress, request, file_id):
    if progress is None or not file_id:
        return "삭제할 첨부 파일을 찾을 수 없습니다."

    is_closed_locked = is_project_or_month_locked(
        project=progress.project,
        target_date=progress.report_date,
    )
    if not can_edit_attachments(status=progress.status, is_closed_locked=is_closed_locked):
        return "제출/승인/마감 상태에서는 첨부를 수정할 수 없습니다."

    evidence_file = (
        EvidenceFile.objects.select_related("evidence")
        .filter(
            id=file_id,
            evidence__object_type="DAILY_PROGRESS",
            evidence__object_id=progress.id,
            evidence__created_by=request.user,
        )
        .first()
    )
    if evidence_file is None:
        return "삭제할 첨부 파일을 찾을 수 없습니다."

    evidence_file.delete()
    return None


def _submit_progress_evidence(progress):
    if progress is None:
        return
    evidence = (
        Evidence.objects.filter(
            object_type="DAILY_PROGRESS",
            object_id=progress.id,
            status=EvidenceStatus.DRAFT,
        )
        .order_by("-created_at")
        .first()
    )
    if evidence is not None:
        evidence.status = EvidenceStatus.SUBMITTED
        evidence.save(update_fields=["status", "updated_at"])


def _is_cost_locked(cost_actual) -> bool:
    if cost_actual is None:
        return True
    if str(cost_actual.status).upper() in _LOCKED_STATUSES:
        return True
    return _is_approval_approved("COST_ACTUAL", cost_actual.id)


def _is_progress_locked(progress) -> bool:
    if progress is None:
        return True
    if str(progress.status).upper() in _LOCKED_STATUSES:
        return True
    return _is_approval_approved("DAILY_PROGRESS", progress.id)


@login_required
def field_dashboard(request):
    tab = request.GET.get("tab", request.POST.get("tab", "progress"))
    if tab in {"evidence", "report"}:
        tab = "progress"
        messages.info(request, "기존 보고서 메뉴는 공사일보로 통합되었습니다. 공사일보 탭에서 자동 취합 결과를 확인해 주세요.")
    projects = _get_accessible_projects(request.user)
    current_legal_entity = get_current_legal_entity(request)
    if current_legal_entity is not None:
        projects = projects.filter(legal_entity=current_legal_entity)
    project_id = request.GET.get("project_id") or request.POST.get("project_id")
    project = None
    requested_project_denied = False
    if project_id:
        try:
            project = _resolve_project(request.user, project_id)
        except PermissionDenied:
            requested_project_denied = True
            project = None
    if project is not None and not projects.filter(id=project.id).exists():
        requested_project_denied = True
        project = None

    if project is None:
        last_project_id = request.session.get("last_project_id")
        if last_project_id:
            try:
                project = _resolve_project(request.user, last_project_id)
            except PermissionDenied:
                project = None
            if project:
                project_id = project.id
    if project is None:
        project = projects.first()
        if project:
            project_id = project.id

    test_date_window = get_active_test_date_window(project) if project else None
    progress_max_date = (test_date_window.end_date if test_date_window else date.today()).isoformat()
    context = {
        "tab": tab,
        "projects": projects,
        "project": project,
        "errors": [],
        "success": "",
        "now": date.today().isoformat(),
        "progress_min_date": (
            test_date_window.start_date if test_date_window else date.today() - timedelta(days=1)
        ).isoformat(),
        "progress_max_date": progress_max_date,
        "test_date_window": test_date_window,
        "retro_request_context": None,
        "role": get_user_role(request.user),
    }

    if requested_project_denied:
        context["errors"].append("선택한 프로젝트 접근 권한이 없어 접근 가능한 프로젝트로 전환했습니다.")
    if project:
        request.session["last_project_id"] = project.id

    if request.method == "POST" and project:
        if tab == "progress":
            _handle_progress_submit(request, project, context)
        elif tab == "cost":
            _handle_cost_submit(request, project, context)
        if context["success"]:
            messages.success(request, context["success"])
            return redirect(f"/app/field/?tab={tab}&project_id={project.id}")

    _load_progress_context(project, request.user, request, context)
    _load_report_context(project, request.user, request, context)
    _load_cost_context(project, request.user, request, context)

    return render(request, "field/dashboard.html", context)


@login_required
def hq_retroactive_progress_request_list(request):
    require_role(request.user, [Role.HQ, Role.CEO], request=request)
    if request.method == "POST":
        retro_request = get_object_or_404(
            RetroactiveEntryRequest,
            pk=request.POST.get("request_id"),
            project__legal_entity=get_current_legal_entity(request),
        )
        action = request.POST.get("action")
        try:
            if action == "approve":
                approve_retroactive_progress_request(
                    retro_request=retro_request,
                    actor=request.user,
                    review_comment=request.POST.get("review_comment", ""),
                    request=request,
                )
                messages.success(request, "진행률 소급 입력 요청을 승인했습니다.")
            elif action == "reject":
                reject_retroactive_progress_request(
                    retro_request=retro_request,
                    actor=request.user,
                    review_comment=request.POST.get("review_comment", ""),
                    request=request,
                )
                messages.success(request, "진행률 소급 입력 요청을 반려했습니다.")
            else:
                messages.error(request, "요청 처리 방식을 확인해 주세요.")
        except (PermissionDenied, ValidationError) as exc:
            messages.error(request, str(exc))
        return redirect("/app/hq/progress/retro-requests/")

    status = (request.GET.get("status") or "PENDING").upper()
    requests = RetroactiveEntryRequest.objects.select_related(
        "project", "requested_by", "reviewed_by"
    ).filter(project__legal_entity=get_current_legal_entity(request)).order_by("-requested_at", "-id")
    valid_statuses = {choice for choice, _label in RetroactiveEntryRequestStatus.choices}
    if status in valid_statuses:
        requests = requests.filter(status=status)
    else:
        status = ""
    return render(
        request,
        "app/hq/retro_progress_request_list.html",
        {
            "retro_requests": requests,
            "selected_status": status,
            "retro_statuses": RetroactiveEntryRequestStatus.choices,
        },
    )


@login_required
def field_cost_detail(request, cost_actual_id):
    """
    Legacy detail endpoint kept for URL compatibility.
    Field cost flow uses the edit/detail hybrid page.
    """
    return redirect(f"/app/field/cost/{cost_actual_id}/edit/")


@login_required
def field_cost_edit(request, cost_actual_id):
    cost_actual = get_object_or_404(CostActual, id=cost_actual_id)
    project = cost_actual.project
    _require_current_entity_project(request, project)

    role = get_user_role(request.user)
    try:
        guard_write(
            project=cost_actual.project,
            target_date=cost_actual.report_date,
            message_context="원가 수정입니다.",
            exc=PermissionDenied,
        )
    except PermissionDenied as exc:
        messages.error(request, str(exc))
        return redirect(f"/app/field/?tab=cost&project_id={project.id}")

    report = cost_actual.source_daily_report
    if role == Role.FIELD:
        if report is None or report.reporter_id != request.user.id:
            raise PermissionDenied("Cost edit not allowed.")
        editable_statuses = {
            str(CostActualStatus.DRAFT).lower(),
            str(CostActualStatus.REJECTED).lower(),
        }
        if str(cost_actual.status).lower() not in editable_statuses:
            raise PermissionDenied("Only draft or rejected costs are editable.")
        if _is_cost_locked(cost_actual):
            raise PermissionDenied("Cost is locked after approval.")

    line = cost_actual.lines.order_by("id").first()
    evidences = list(
        Evidence.objects.filter(
            object_type="COST_ACTUAL",
            object_id=cost_actual.id,
        )
        .prefetch_related("files")
        .order_by("-created_at")
    )
    evidence = evidences[0] if evidences else None
    attachment_files = []
    seen_file_ids = set()
    for evidence_obj in evidences:
        for evidence_file in evidence_obj.files.all().order_by("-created_at"):
            if evidence_file.id in seen_file_ids:
                continue
            seen_file_ids.add(evidence_file.id)
            attachment_files.append(evidence_file)

    is_closed_locked = is_project_or_month_locked(
        project=cost_actual.project,
        target_date=cost_actual.report_date,
    )
    can_edit_cost_attachments = can_edit_attachments(
        status=cost_actual.status,
        is_closed_locked=is_closed_locked,
    )

    def _render_cost_edit(error_message=None):
        return render(
            request,
            "app/cost_edit.html",
            {
                "cost_actual": cost_actual,
                "line": line,
                "evidence": evidence,
                "cost_items": list(
                    CostItem.objects.filter(is_active=True).prefetch_related("aliases")
                ),
                "error": error_message,
                "cost_existing_files": attachment_files,
                "cost_can_edit_attachments": can_edit_cost_attachments,
                "cost_attachment_upload_url": f"/app/field/cost/{cost_actual.id}/edit/",
                "cost_attachment_delete_url": f"/app/field/cost/{cost_actual.id}/edit/",
                "cost_attachment_help_text": (
                    "임시저장/반려 상태에서는 제출 전까지 첨부를 수정할 수 있습니다."
                    if can_edit_cost_attachments
                    else "제출/승인/마감 상태에서는 첨부를 수정할 수 없습니다."
                ),
            },
        )

    if request.method == "POST":
        action = request.POST.get("action", "draft")
        if action == "attachment_upload":
            if not can_edit_cost_attachments:
                messages.error(request, "제출/승인/마감 상태에서는 첨부를 수정할 수 없습니다.")
                return redirect(f"/app/field/cost/{cost_actual.id}/edit/")
            upload_files = request.FILES.getlist("files")
            if not upload_files:
                return _render_cost_edit("업로드할 파일을 선택해 주세요.")
            editable_evidence = (
                Evidence.objects.filter(
                    object_type="COST_ACTUAL",
                    object_id=cost_actual.id,
                    created_by=request.user,
                    status=EvidenceStatus.DRAFT,
                )
                .order_by("-created_at")
                .first()
            )
            if editable_evidence is None:
                editable_evidence = Evidence.objects.create(
                    object_type="COST_ACTUAL",
                    object_id=cost_actual.id,
                    title=f"원가 증빙 - {line.cost_item.get_display_name() if line else '원가'}",
                    description=(line.description if line else "") or "",
                    created_by=request.user,
                    status=EvidenceStatus.DRAFT,
                )
            for upload_file in upload_files:
                EvidenceFile.objects.create(
                    evidence=editable_evidence,
                    file=upload_file,
                    original_name=upload_file.name,
                    content_type=getattr(upload_file, "content_type", "")
                    or "application/octet-stream",
                    size_bytes=upload_file.size,
                    sha256="",
                    created_by=request.user,
                )
            messages.success(request, "첨부 파일이 업로드되었습니다.")
            return redirect(f"/app/field/cost/{cost_actual.id}/edit/")

        if action == "attachment_delete":
            if not can_edit_cost_attachments:
                messages.error(request, "제출/승인/마감 상태에서는 첨부를 수정할 수 없습니다.")
                return redirect(f"/app/field/cost/{cost_actual.id}/edit/")
            file_id = request.POST.get("file_id")
            evidence_file = (
                EvidenceFile.objects.select_related("evidence")
                .filter(
                    id=file_id,
                    evidence__object_type="COST_ACTUAL",
                    evidence__object_id=cost_actual.id,
                )
                .first()
            )
            if evidence_file is None:
                return _render_cost_edit("삭제할 첨부 파일을 찾을 수 없습니다.")
            evidence_file.delete()
            messages.success(request, "첨부 파일을 삭제했습니다.")
            return redirect(f"/app/field/cost/{cost_actual.id}/edit/")

        if action == "submit":
            if str(cost_actual.status).lower() not in {
                str(CostActualStatus.DRAFT).lower(),
                str(CostActualStatus.REJECTED).lower(),
            }:
                messages.error(request, "임시저장/반려 상태에서만 제출할 수 있습니다.")
                return redirect(f"/app/field/cost/{cost_actual.id}/edit/")
            report = cost_actual.source_daily_report
            if report and report.status != DailyReportStatus.SUBMITTED:
                report.status = DailyReportStatus.SUBMITTED
                report.save(update_fields=["status"])
            cost_actual.status = CostActualStatus.SUBMITTED
            cost_actual.save(update_fields=["status", "updated_at"])
            ApprovalRequest.objects.update_or_create(
                object_type="COST_ACTUAL",
                object_id=cost_actual.id,
                defaults={
                    "status": ApprovalStatus.SUBMITTED,
                    "submitted_by": request.user,
                    "submitted_at": timezone.now(),
                },
            )
            log_action(
                actor=request.user,
                action=SUBMIT,
                object_type="COST_ACTUAL",
                object_id=cost_actual.id,
                project=project,
                request=request,
                after={"status": cost_actual.status},
            )
            messages.success(request, "원가가 제출되었습니다.")
            return redirect(f"/app/field/?tab=cost&project_id={project.id}")
        cost_item_id = request.POST.get("cost_item_id")
        quantity = _parse_decimal_amount(request.POST.get("quantity"))
        unit_price = _parse_decimal_amount(request.POST.get("unit_price"))
        vat_treatment = request.POST.get("vat_treatment") or CostVATTreatment.DEDUCTIBLE
        memo = (request.POST.get("memo") or "").strip()
        file_obj = request.FILES.get("evidence_file")
        cost_item = None
        if cost_item_id:
            cost_item = CostItem.objects.filter(id=cost_item_id, is_active=True).first()
        if cost_item is None:
            return _render_cost_edit("원가 항목을 선택해 주세요.")
        if quantity is None or unit_price is None:
            return _render_cost_edit("수량/단가를 입력해 주세요.")
        if vat_treatment not in CostVATTreatment.values:
            return _render_cost_edit("부가세 처리 구분을 선택해 주세요.")
        if line:
            line.cost_item = cost_item
            line.quantity = quantity
            line.unit_price = unit_price
            line.vat_treatment = vat_treatment
            line.description = memo
            line.save()
        else:
            line = CostActualLine.objects.create(
                cost_actual=cost_actual,
                cost_item=cost_item,
                description=memo,
                quantity=quantity,
                unit_price=unit_price,
                vat_treatment=vat_treatment,
            )

        if report and memo:
            report.note = memo
            report.save(update_fields=["note", "updated_at"])

        if file_obj:
            if evidence is None:
                evidence = Evidence.objects.create(
                    object_type="COST_ACTUAL",
                    object_id=cost_actual.id,
                    title=f"원가 증빙 - {line.cost_item.get_display_name()}",
                    description=memo,
                    created_by=request.user,
                    status=EvidenceStatus.DRAFT,
                )
                log_action(
                    actor=request.user,
                    action=EVIDENCE_CREATE,
                    object_type="EVIDENCE",
                    object_id=evidence.id,
                    project=project,
                    request=request,
                    after={"title": evidence.title},
                    meta={
                        "object_type": evidence.object_type,
                        "object_id": evidence.object_id,
                    },
                )
            evidence_file = EvidenceFile.objects.create(
                evidence=evidence,
                file=file_obj,
                original_name=file_obj.name,
                content_type=getattr(file_obj, "content_type", "")
                or "application/octet-stream",
                size_bytes=file_obj.size,
                sha256="",
                created_by=request.user,
            )
            log_action(
                actor=request.user,
                action=EVIDENCE_FILE_ADD,
                object_type="EVIDENCE",
                object_id=evidence.id,
                project=project,
                request=request,
                after={"file_id": evidence_file.id},
                meta={
                    "original_name": evidence_file.original_name,
                    "size_bytes": evidence_file.size_bytes,
                    "content_type": evidence_file.content_type,
                    "sha256": evidence_file.sha256,
                },
            )

        log_action(
            actor=request.user,
            action=DRAFT_SAVE,
            object_type="COST_ACTUAL",
            object_id=cost_actual.id,
            project=project,
            request=request,
            after={"status": cost_actual.status},
        )
        return redirect(f"/app/field/?tab=cost&project_id={project.id}")

    return _render_cost_edit()


@login_required
def field_progress_detail(request, progress_id):
    """
    Legacy detail endpoint kept for URL compatibility.
    Field progress flow uses dashboard detail/edit hybrid.
    """
    progress = get_object_or_404(DailyProgress, pk=progress_id)
    _require_current_entity_project(request, progress.project)
    return redirect(
        f"/app/field/?tab=progress&project_id={progress.project_id}&progress_id={progress.id}"
    )


@login_required
def field_progress_correction_new(request, progress_id):
    progress = get_object_or_404(DailyProgress.objects.select_related("project", "task", "reporter"), pk=progress_id)
    _require_current_entity_project(request, progress.project)
    if get_user_role(request.user) != Role.FIELD or progress.reporter_id != request.user.id:
        raise PermissionDenied("본인이 작성한 진행률만 정정·취소 요청할 수 있습니다.")
    if request.method == "POST":
        try:
            value = request.POST.get("proposed_progress_percent")
            create_progress_correction(
                progress=progress, actor=request.user,
                correction_type=(request.POST.get("correction_type") or "").upper(),
                proposed_progress_percent=Decimal(value) if value not in (None, "") else None,
                proposed_note=request.POST.get("proposed_note", ""), reason=request.POST.get("reason", ""), request=request,
            )
        except (ValidationError, PermissionDenied, InvalidOperation) as exc:
            messages.error(request, str(exc))
        else:
            messages.success(request, "진행률 정정·취소 요청을 HQ에 전달했습니다.")
            return redirect(f"/app/field/?tab=progress&project_id={progress.project_id}")
    return render(request, "field/progress_correction_new.html", {"progress": progress, "role": get_user_role(request.user)})


@login_required
def field_progress_edit(request, progress_id):
    message_context = "\uc9c4\ud589\ub960 \uc785\ub825\uc785\ub2c8\ub2e4."
    progress = get_object_or_404(DailyProgress, pk=progress_id)
    project = progress.project

    _require_current_entity_project(request, project)

    if not _can_edit_progress(request.user, project):
        return _forbidden(request)

    if request.method != "POST":
        return redirect(
            f"/app/field/?tab=progress&project_id={project.id}&progress_id={progress.id}"
        )

    try:
        guard_write(
            project=project,
            target_date=progress.report_date,
            message_context=message_context,
            exc=PermissionDenied,
        )
    except PermissionDenied as exc:
        messages.error(request, str(exc))
        return redirect("/app/field/?tab=progress&project_id=%s" % project.id)

    if progress.status not in {"draft", "rejected"}:
        messages.error(request, "\uc81c\ucd9c \uc644\ub8cc \ud6c4\uc5d0\ub294 \uc218\uc815\ud560 \uc218 \uc5c6\uc2b5\ub2c8\ub2e4.")
        return redirect("/app/field/?tab=progress&project_id=%s" % project.id)

    task_id = request.POST.get("task_id")
    report_date = request.POST.get("report_date") or progress.report_date
    progress_percent = request.POST.get("progress_percent")
    note = request.POST.get("note", "")
    progress_photo = request.FILES.getlist("progress_photo")

    if not task_id or progress_percent in (None, ""):
        messages.error(request, "\uc791\uc5c5\uacfc \uc9c4\ud589\ub960\uc744 \uc785\ub825\ud574 \uc8fc\uc138\uc694.")
        return redirect("/app/field/?tab=progress&project_id=%s" % project.id)

    try:
        value = float(progress_percent)
    except (TypeError, ValueError):
        messages.error(request, "\uc9c4\ud589\ub960\uc740 0~100 \uc0ac\uc774 \uc22b\uc790\uc5ec\uc57c \ud569\ub2c8\ub2e4. (\uc608: 9.0)")
        return redirect("/app/field/?tab=progress&project_id=%s" % project.id)

    if value < 0 or value > 100:
        messages.error(request, "\uc9c4\ud589\ub960\uc740 0~100 \uc0ac\uc774 \uc22b\uc790\uc5ec\uc57c \ud569\ub2c8\ub2e4. (\uc608: 9.0)")
        return redirect("/app/field/?tab=progress&project_id=%s" % project.id)

    task = ScheduleTask.objects.filter(pk=task_id, plan__project_id=project.id).first()
    if task is None:
        messages.error(request, "\uc791\uc5c5\uc744 \ucc3e\uc744 \uc218 \uc5c6\uc2b5\ub2c8\ub2e4.")
        return redirect("/app/field/?tab=progress&project_id=%s" % project.id)

    try:
        if report_date:
            report_date = datetime.strptime(str(report_date), "%Y-%m-%d").date()
    except ValueError:
        messages.error(request, "\ub0a0\uc9dc \ud615\uc2dd\uc774 \uc62c\ubc14\ub974\uc9c0 \uc54a\uc2b5\ub2c8\ub2e4.")
        return redirect("/app/field/?tab=progress&project_id=%s" % project.id)
    if report_date:
        today = date.today()
        if report_date > today and not allows_future_operational_test_date(project, report_date, today=today):
            messages.error(request, "미래 날짜의 진행률은 입력할 수 없습니다.")
            return redirect("/app/field/?tab=progress&project_id=%s" % project.id)
        try:
            guard_write(
                project=project,
                target_date=report_date,
                message_context=message_context,
                exc=PermissionDenied,
            )
        except PermissionDenied as exc:
            messages.error(request, str(exc))
            return redirect("/app/field/?tab=progress&project_id=%s" % project.id)
        if (
            requires_retroactive_progress_authorization(report_date, today=today)
            and not allows_operational_test_date(project, report_date, today=today)
        ):
            try:
                require_approved_retroactive_progress_request(
                    project=project,
                    target_date=report_date,
                    actor=request.user,
                )
            except ValidationError as exc:
                messages.error(request, str(exc))
                return redirect("/app/field/?tab=progress&project_id=%s" % project.id)
        monotonic_error = _validate_progress_monotonic(
            project=project,
            task=task,
            target_date=report_date,
            value=value,
            reporter=request.user,
        )
        if monotonic_error:
            messages.error(request, monotonic_error)
            return redirect("/app/field/?tab=progress&project_id=%s" % project.id)

    progress.task = task
    progress.report_date = report_date
    progress.progress_percent = round(value, 1)
    progress.note = note
    progress.save()

    if progress_photo:
        evidence_error = _upsert_progress_evidence_files(progress, request, progress_photo)
        if evidence_error:
            messages.error(request, evidence_error)
            return redirect("/app/field/?tab=progress&project_id=%s" % project.id)

    messages.success(request, f"{progress.report_date} \uc9c4\ud589\ub960\uc774 \uc784\uc2dc\uc800\uc7a5\ub418\uc5c8\uc2b5\ub2c8\ub2e4.")
    return redirect("/app/field/?tab=progress&project_id=%s" % project.id)

@login_required
def field_progress_yesterday(request):
    project_id = request.GET.get("project_id")
    task_id = request.GET.get("task_id")
    base_date = request.GET.get("date") or date.today().isoformat()

    if not project_id or not task_id:
        return JsonResponse({"ok": False, "message": "\uc870\ud68c \uc870\uac74\uc774 \ubd80\uc871\ud569\ub2c8\ub2e4."})

    project = _resolve_project(request.user, project_id)
    if project is None or not _can_edit_progress(request.user, project):
        return JsonResponse({"ok": False, "message": "\ud504\ub85c\uc81d\ud2b8 \uad8c\ud55c\uc774 \uc5c6\uc2b5\ub2c8\ub2e4."}, status=403)

    try:
        base_date_parsed = datetime.strptime(str(base_date), "%Y-%m-%d").date()
    except ValueError:
        return JsonResponse({"ok": False, "message": "\ub0a0\uc9dc \ud615\uc2dd\uc774 \uc62c\ubc14\ub974\uc9c0 \uc54a\uc2b5\ub2c8\ub2e4."})

    target_date = base_date_parsed - timedelta(days=1)
    task = ScheduleTask.objects.filter(pk=task_id, plan__project_id=project.id).first()
    if task is None:
        return JsonResponse({"ok": False, "message": "\uc791\uc5c5\uc744 \ucc3e\uc744 \uc218 \uc5c6\uc2b5\ub2c8\ub2e4."})

    qs = (
        DailyProgress.objects.filter(
            project=project,
            task=task,
            report_date=target_date,
        )
        .order_by("-updated_at")
    )
    progress = None
    for item in qs:
        if str(item.status).lower() != "draft":
            progress = item
            break
    if progress is None:
        progress = qs.first()

    if progress is None:
        return JsonResponse({"ok": False, "message": "\uc5b4\uc81c \uc785\ub825\uac12\uc774 \uc5c6\uc2b5\ub2c8\ub2e4."})

    return JsonResponse(
        {
            "ok": True,
            "progress": f"{float(progress.progress_percent):.1f}",
            "memo": progress.note or "",
            "source_date": str(progress.report_date),
        }
    )

def _handle_progress_submit(request, project, context):
    action = request.POST.get("action", "draft")
    message_context = "진행률 입력입니다."
    today = date.today()
    min_date = today - timedelta(days=1)
    _plan, available_tasks = _ensure_progress_tasks_for_project(project)

    def _set_retro_request_context(target_date):
        context["retro_request_context"] = {
            "target_date": target_date,
            "retro_request": get_retroactive_progress_request(
                project=project,
                target_date=target_date,
                actor=request.user,
            ),
        }

    def _validate_recent_date(target_date):
        if target_date > today and not allows_future_operational_test_date(project, target_date, today=today):
            context["errors"].append("미래 날짜의 진행률은 입력할 수 없습니다.")
            return False
        if (
            requires_retroactive_progress_authorization(target_date, today=today)
            and not allows_operational_test_date(project, target_date, today=today)
        ):
            _set_retro_request_context(target_date)
            try:
                require_approved_retroactive_progress_request(
                    project=project,
                    target_date=target_date,
                    actor=request.user,
                )
            except ValidationError as exc:
                context["errors"].append(
                    "해당 일자는 일반 입력 가능기간(오늘/어제)을 초과했습니다. 소급 입력이 필요한 경우 HQ 승인을 요청해 주세요."
                )
                context["errors"].append(str(exc))
                return False
        return True

    if action == "retro_request":
        target_value = request.POST.get("retro_target_date") or request.POST.get("report_date")
        try:
            target_date = datetime.strptime(str(target_value), "%Y-%m-%d").date()
        except (TypeError, ValueError):
            context["errors"].append("소급 입력 대상일을 확인해 주세요.")
            return
        _set_retro_request_context(target_date)
        try:
            retro_request, created = create_retroactive_progress_request(
                project=project,
                target_date=target_date,
                reason=request.POST.get("retro_reason", ""),
                actor=request.user,
                request=request,
            )
        except (PermissionDenied, ValidationError) as exc:
            context["errors"].append(str(exc))
            return
        context["retro_request_context"]["retro_request"] = retro_request
        context["success"] = (
            "진행률 소급 입력 요청을 제출했습니다. HQ 승인 후 해당 일자에 입력할 수 있습니다."
            if created
            else "동일한 소급 입력 요청이 이미 접수되어 있습니다. 처리 상태를 확인해 주세요."
        )
        return

    if action in {"attachment_upload", "attachment_delete"}:
        progress_id = request.POST.get("progress_id")
        if not progress_id:
            context["errors"].append("첨부 대상을 찾을 수 없습니다.")
            return
        progress = DailyProgress.objects.filter(
            id=progress_id,
            project=project,
            reporter=request.user,
        ).first()
        if progress is None:
            context["errors"].append("첨부 대상을 찾을 수 없습니다.")
            return
        if not _validate_recent_date(progress.report_date):
            return
        try:
            guard_write(
                project=project,
                target_date=progress.report_date,
                message_context=message_context,
                exc=PermissionDenied,
            )
        except PermissionDenied as exc:
            context["errors"].append(str(exc))
            return

        if action == "attachment_upload":
            progress_photo_files = request.FILES.getlist("progress_photo")
            if not progress_photo_files:
                context["errors"].append("업로드할 파일을 선택해 주세요.")
                return
            evidence_error = _upsert_progress_evidence_files(progress, request, progress_photo_files)
            if evidence_error:
                context["errors"].append(evidence_error)
                return
            context["success"] = "첨부 파일이 업로드되었습니다."
            return

        file_id = request.POST.get("file_id")
        evidence_error = _delete_progress_evidence_file(progress, request, file_id)
        if evidence_error:
            context["errors"].append(evidence_error)
            return
        context["success"] = "첨부 파일이 삭제되었습니다."
        return

    if action == "submit":
        progress_id = request.POST.get("progress_id")
        progress_photo_submit = request.FILES.getlist("progress_photo")
        if not progress_id:
            # Allow submit without reselecting file/id by falling back to latest editable draft.
            latest = (
                DailyProgress.objects.filter(
                    project=project,
                    reporter=request.user,
                    status__in=["draft", "rejected"],
                )
                .order_by("-updated_at")
                .first()
            )
            if latest is not None:
                progress_id = str(latest.id)
            else:
                context["errors"].append("임시저장 내역이 없어 제출할 수 없습니다.")
                return
        progress = DailyProgress.objects.filter(
            id=progress_id,
            project=project,
            reporter=request.user,
        ).first()
        if progress is None:
            context["errors"].append(
                "임시저장 내역을 찾을 수 없습니다."
            )
            return
        if not _validate_recent_date(progress.report_date):
            return
        try:
            guard_write(
                project=project,
                target_date=progress.report_date,
                message_context=message_context,
                exc=PermissionDenied,
            )
        except PermissionDenied as exc:
            context["errors"].append(str(exc))
            return
        if progress.status not in {"draft", "rejected"}:
            context["errors"].append(
                "임시저장 상태에서만 제출할 수 있습니다."
            )
            return
        if progress.task_id is None or progress.progress_percent is None:
            context["errors"].append("작업과 진행률을 입력해 주세요.")
            return
        if progress_photo_submit:
            evidence_error = _upsert_progress_evidence_files(progress, request, progress_photo_submit)
            if evidence_error:
                context["errors"].append(evidence_error)
                return
        with transaction.atomic():
            progress = DailyProgress.objects.select_for_update().get(pk=progress.pk)
            guard_write(
                project=project,
                target_date=progress.report_date,
                message_context=message_context,
                exc=PermissionDenied,
            )
            retro_request = None
            if requires_retroactive_progress_authorization(progress.report_date, today=today):
                retro_request = require_approved_retroactive_progress_request(
                    project=project,
                    target_date=progress.report_date,
                    actor=request.user,
                    lock=True,
                )
            progress.status = "submitted"
            progress.rejected_by = None
            progress.rejected_at = None
            progress.reject_reason = ""
            progress.save(
                update_fields=[
                    "status",
                    "rejected_by",
                    "rejected_at",
                    "reject_reason",
                    "updated_at",
                ]
            )
            _submit_progress_evidence(progress)
            ApprovalRequest.objects.update_or_create(
                object_type="DAILY_PROGRESS",
                object_id=progress.id,
                defaults={
                    "status": ApprovalStatus.SUBMITTED,
                    "submitted_by": request.user,
                    "submitted_at": timezone.now(),
                    "approved_by": None,
                    "approved_at": None,
                    "reject_reason": "",
                },
            )
            log_action(
                actor=request.user,
                action=SUBMIT,
                object_type="DAILY_PROGRESS",
                object_id=progress.id,
                project=project,
                request=request,
                after={"status": progress.status, "report_date": str(progress.report_date)},
            )
            if retro_request is not None:
                consume_retroactive_progress_request(
                    retro_request=retro_request,
                    actor=request.user,
                    progress=progress,
                    request=request,
                )
                log_action(
                    actor=request.user,
                    action="RETRO_PROGRESS_SUBMITTED",
                    object_type="DAILY_PROGRESS",
                    object_id=progress.id,
                    project=project,
                    request=request,
                    after={"status": progress.status, "report_date": str(progress.report_date)},
                    meta={"retro_request_id": retro_request.id},
                )
        context["success"] = "진행률이 제출되었습니다."
        return
        monotonic_error = _validate_progress_monotonic(
            project=project,
            task=progress.task,
            target_date=progress.report_date,
            value=progress.progress_percent,
            reporter=request.user,
        )
        if monotonic_error:
            context["errors"].append(monotonic_error)
            return



    task_id = request.POST.get("task_id")
    report_date = request.POST.get("report_date") or today.isoformat()
    progress_percent = request.POST.get("progress_percent")
    note = (request.POST.get("note") or "").strip()
    progress_photo = request.FILES.getlist("progress_photo")

    if not available_tasks:
        context["errors"].append(
            "이 프로젝트에는 WBS 기준선 작업이 없습니다. HQ에서 WBS 기준선을 등록한 뒤 진행률을 입력할 수 있습니다."
        )
        return

    if not task_id:
        context["errors"].append("작업을 선택해 주세요.")
        return

    if progress_percent in (None, ""):
        context["errors"].append("진행률을 입력해 주세요.")
        return

    if len(note) > 5000:
        context["errors"].append("메모는 5,000자 이내로 입력해 주세요.")
        return

    try:
        value = float(progress_percent)
    except (TypeError, ValueError):
        context["errors"].append(
            "진행률은 0~100 사이 숫자여야 합니다. (예: 9.0)"
        )
        return

    if value < 0 or value > 100:
        context["errors"].append(
            "진행률은 0~100 사이 숫자여야 합니다. (예: 9.0)"
        )
        return

    try:
        report_date_parsed = datetime.strptime(str(report_date), "%Y-%m-%d").date()
    except ValueError:
        context["errors"].append("날짜 형식이 올바르지 않습니다.")
        return

    if not _validate_recent_date(report_date_parsed):
        return

    try:
        guard_write(
            project=project,
            target_date=report_date_parsed,
            message_context=message_context,
            exc=PermissionDenied,
        )
    except PermissionDenied as exc:
        context["errors"].append(str(exc))
        return

    task = ScheduleTask.objects.filter(pk=task_id, plan__project_id=project.id).first()
    if task is None:
        context["errors"].append("작업을 찾을 수 없습니다.")
        return
    monotonic_error = _validate_progress_monotonic(
        project=project,
        task=task,
        target_date=report_date_parsed,
        value=value,
        reporter=request.user,
    )
    if monotonic_error:
        context["errors"].append(monotonic_error)
        return



    existing = DailyProgress.objects.filter(
        project=project,
        task=task,
        report_date=report_date_parsed,
        reporter=request.user,
    ).first()
    if existing and existing.status not in {"draft", "rejected"}:
        context["errors"].append("제출 완료 후에는 수정할 수 없습니다.")
        return

    try:
        if existing:
            existing.progress_percent = round(value, 1)
            existing.note = note
            if existing.status == "rejected":
                existing.status = "draft"
                existing.save(update_fields=["progress_percent", "note", "status", "updated_at"])
            else:
                existing.save(update_fields=["progress_percent", "note", "updated_at"])
            progress = existing
        else:
            progress = DailyProgress.objects.create(
                project=project,
                task=task,
                report_date=report_date_parsed,
                progress_percent=round(value, 1),
                status="draft",
                reporter=request.user,
                note=note,
            )

        if progress_photo:
            evidence_error = _upsert_progress_evidence_files(progress, request, progress_photo)
            if evidence_error:
                context["errors"].append(evidence_error)
                return
    except IntegrityError:
        context["errors"].append("이미 동일한 작업/날짜의 진행률이 존재합니다.")
        return
    except DataError:
        logger.exception("Failed to save DailyProgress due to invalid field length.")
        context["errors"].append(
            "입력값 중 너무 긴 항목이 있습니다. 메모 길이를 줄이거나 관리자에게 문의해 주세요."
        )
        return

    log_action(
        actor=request.user,
        action=DRAFT_SAVE,
        object_type="DAILY_PROGRESS",
        object_id=progress.id,
        project=project,
        request=request,
        after={"status": progress.status, "report_date": str(progress.report_date)},
    )
    context["success"] = f"{progress.report_date} 진행률이 임시저장되었습니다."

def _handle_evidence_submit(request, project, context):
    action = request.POST.get("action", "draft")
    evidence_id = request.POST.get("evidence_id")
    title = (request.POST.get("title") or "").strip()
    description = (request.POST.get("description") or "").strip()
    file_obj = request.FILES.get("file")

    if action == "submit":
        evidence = (
            Evidence.objects.filter(id=evidence_id, created_by=request.user).first()
            if evidence_id
            else None
        )
        if evidence is None:
            context["errors"].append("임시저장 내역이 없어 제출할 수 없습니다.")
            return
        if evidence.status != EvidenceStatus.DRAFT:
            context["errors"].append("확인 완료 전에는 제출할 수 없습니다.")
            return
        if not evidence.files.exists() and file_obj is None:
            context["errors"].append("제출하려면 파일이 필요합니다.")
            return
        if file_obj:
            EvidenceFile.objects.create(
                evidence=evidence,
                file=file_obj,
                original_name=file_obj.name,
                content_type=getattr(file_obj, "content_type", "")
                or "application/octet-stream",
                size_bytes=file_obj.size,
                sha256="",
                created_by=request.user,
            )
        evidence.status = EvidenceStatus.SUBMITTED
        evidence.save(update_fields=["status", "updated_at"])
        log_action(
            actor=request.user,
            action=SUBMIT,
            object_type="EVIDENCE",
            object_id=evidence.id,
            project=project,
            request=request,
            after={"status": evidence.status},
            meta={"object_type": evidence.object_type, "object_id": evidence.object_id},
        )
        context["success"] = "보고서가 제출되었습니다."
        return

    if not title:
        context["errors"].append("제목을 입력해 주세요.")
        return

    evidence = None
    if evidence_id:
        evidence = Evidence.objects.filter(
            id=evidence_id, created_by=request.user
        ).first()
        if evidence is not None and evidence.status != EvidenceStatus.DRAFT:
            context["errors"].append("확인 완료 전에는 수정할 수 없습니다.")
            return
    if evidence is None:
        evidence = (
            Evidence.objects.filter(
                object_type="PROJECT",
                object_id=project.id,
                created_by=request.user,
                status__in=[EvidenceStatus.DRAFT, EvidenceStatus.SUBMITTED],
            )
            .order_by("-updated_at")
            .first()
        )
    if evidence is None:
        evidence = Evidence.objects.create(
            object_type="PROJECT",
            object_id=project.id,
            title=title,
            description=description,
            created_by=request.user,
            status=EvidenceStatus.DRAFT,
        )
        log_action(
            actor=request.user,
            action=EVIDENCE_CREATE,
            object_type="EVIDENCE",
            object_id=evidence.id,
            project=project,
            request=request,
            after={"title": evidence.title},
            meta={"object_type": evidence.object_type, "object_id": evidence.object_id},
        )
    else:
        evidence.title = title
        evidence.description = description
        evidence.status = EvidenceStatus.DRAFT
        evidence.save(update_fields=["title", "description", "status", "updated_at"])
    _dedupe_project_evidence(evidence)

    if file_obj:
        evidence_file = EvidenceFile.objects.create(
            evidence=evidence,
            file=file_obj,
            original_name=file_obj.name,
            content_type=getattr(file_obj, "content_type", "")
            or "application/octet-stream",
            size_bytes=file_obj.size,
            sha256="",
            created_by=request.user,
        )
        log_action(
            actor=request.user,
            action=EVIDENCE_FILE_ADD,
            object_type="EVIDENCE",
            object_id=evidence.id,
            project=project,
            request=request,
            after={"file_id": evidence_file.id},
            meta={
                "original_name": evidence_file.original_name,
                "size_bytes": evidence_file.size_bytes,
                "content_type": evidence_file.content_type,
                "sha256": evidence_file.sha256,
            },
        )

    log_action(
        actor=request.user,
        action=DRAFT_SAVE,
        object_type="EVIDENCE",
        object_id=evidence.id,
        project=project,
        request=request,
        after={"status": evidence.status},
        meta={"object_type": evidence.object_type, "object_id": evidence.object_id},
    )
    context["success"] = "보고서가 임시저장되었습니다."


def _handle_cost_submit(request, project, context):
    action = request.POST.get("action", "draft")
    cost_actual_id = request.POST.get("cost_actual_id")
    report_date = None
    cost_item_id = request.POST.get("cost_item_id")
    quantity = _parse_decimal_amount(request.POST.get("quantity"))
    unit_price = _parse_decimal_amount(request.POST.get("unit_price"))
    vat_treatment = request.POST.get("vat_treatment") or CostVATTreatment.DEDUCTIBLE
    memo = (request.POST.get("memo") or "").strip()
    evidence_file = request.FILES.get("evidence_file")

    cost_item = None
    if action != "submit":
        report_date = _parse_iso_date(request.POST.get("report_date"))
        if report_date is None:
            context["errors"].append("원가 발생일을 선택해 주세요.")
            return
        if report_date > timezone.localdate() and not allows_future_operational_test_date(project, report_date):
            context["errors"].append("미래 날짜의 원가는 입력할 수 없습니다.")
            return
        cost_actual_id = None
        if not cost_item_id or quantity is None or unit_price is None:
            context["errors"].append("\uc6d0\uac00 \ud56d\ubaa9/\uc218\ub7c9/\ub2e8\uac00\ub97c \uc785\ub825\ud558\uc138\uc694.")
            return
        if quantity < 0 or unit_price < 0:
            context["errors"].append("\uae08\uc561\uc740 0 \uc774\uc0c1\uc774\uc5b4\uc57c \ud569\ub2c8\ub2e4.")
            return
        if vat_treatment not in CostVATTreatment.values:
            context["errors"].append("부가세 처리 구분을 선택해 주세요.")
            return
        cost_item = CostItem.objects.filter(id=cost_item_id, is_active=True).first()
        if cost_item is None:
            context["errors"].append("\uc6d0\uac00 \ud56d\ubaa9\uc744 \ucc3e\uc744 \uc218 \uc5c6\uc2b5\ub2c8\ub2e4.")
            return

    try:
        with transaction.atomic():
            if action == "submit":
                if not cost_actual_id:
                    latest_cost = (
                        CostActual.objects.filter(
                            project=project,
                            source_daily_report__reporter=request.user,
                            status=CostActualStatus.DRAFT,
                        )
                        .order_by("-updated_at")
                        .first()
                    )
                    if latest_cost is None:
                        context["errors"].append("임시저장 내역이 없어 제출할 수 없습니다.")
                        return
                    cost_actual_id = str(latest_cost.id)
                cost_actual = CostActual.objects.filter(
                    id=cost_actual_id,
                    project=project,
                    source_daily_report__reporter=request.user,
                ).first()
                if cost_actual is None:
                    context["errors"].append("\uc784\uc2dc\uc800\uc7a5 \ub0b4\uc5ed\uc744 \ucc3e\uc744 \uc218 \uc5c6\uc2b5\ub2c8\ub2e4.")
                    return
                try:
                        guard_write(
                            project=cost_actual.project,
                            target_date=cost_actual.report_date,
                            message_context="원가 입력입니다.",
                            exc=PermissionDenied,
                        )
                except PermissionDenied as exc:
                    context["errors"].append(str(exc))
                    return
                if _is_cost_locked(cost_actual):
                    context["errors"].append("\uc81c\ucd9c \uc774\ud6c4\uc5d0\ub294 \uc218\uc815\ud560 \uc218 \uc5c6\uc2b5\ub2c8\ub2e4.")
                    return
                if str(cost_actual.status).lower() not in {
                    str(CostActualStatus.DRAFT).lower(),
                    str(CostActualStatus.REJECTED).lower(),
                }:
                    context["errors"].append("\uc784\uc2dc\uc800\uc7a5/\ubc18\ub824 \uc0c1\ud0dc\uc5d0\uc11c\ub9cc \uc81c\ucd9c\ud560 \uc218 \uc788\uc2b5\ub2c8\ub2e4.")
                    return

                report = cost_actual.source_daily_report
                report_date = cost_actual.report_date
                if report and report.status != DailyReportStatus.SUBMITTED:
                    report.status = DailyReportStatus.SUBMITTED
                    report.save(update_fields=["status"])
                cost_actual.status = CostActualStatus.SUBMITTED
                cost_actual.save(update_fields=["status", "updated_at"])
                ApprovalRequest.objects.update_or_create(
                    object_type="COST_ACTUAL",
                    object_id=cost_actual.id,
                    defaults={
                        "status": ApprovalStatus.SUBMITTED,
                        "submitted_by": request.user,
                        "submitted_at": timezone.now(),
                    },
                )
                log_action(
                    actor=request.user,
                    action=SUBMIT,
                    object_type="COST_ACTUAL",
                    object_id=cost_actual.id,
                    project=project,
                    request=request,
                    after={"status": cost_actual.status, "report_date": str(report_date)},
                )
                context["success"] = "\uc6d0\uac00\uac00 \uc81c\ucd9c\ub418\uc5c8\uc2b5\ub2c8\ub2e4."
                return

            try:
                guard_write(
                    project=project,
                    target_date=report_date,
                    message_context="원가 입력입니다.",
                    exc=PermissionDenied,
                )
            except PermissionDenied as exc:
                context["errors"].append(str(exc))
                return
            report = DailyReport.objects.create(
                project=project,
                report_date=report_date,
                reporter=request.user,
                note=memo,
                status=DailyReportStatus.DRAFT,
            )
            if report.status == DailyReportStatus.APPROVED:
                context["errors"].append("\uc2b9\uc778 \uc644\ub8cc\ub41c \uc77c\uc77c\ubcf4\uace0\uc11c\ub294 \uc218\uc815\ud560 \uc218 \uc5c6\uc2b5\ub2c8\ub2e4.")
                return

            report_line = report.lines.order_by("id").first()
            if report_line is None:
                report_line = DailyReportLine.objects.create(
                    report=report,
                    cost_item=cost_item,
                    description=memo,
                    quantity=quantity,
                    unit_price=unit_price,
                )
            else:
                report_line.cost_item = cost_item
                report_line.description = memo
                report_line.quantity = quantity
                report_line.unit_price = unit_price
                report_line.save()

            cost_actual = getattr(report, "costactual", None)
            if cost_actual is None:
                cost_actual = CostActual.objects.create(
                    project=project,
                    report_date=report.report_date,
                    source_daily_report=report,
                    status=CostActualStatus.DRAFT,
                )
            if str(cost_actual.status).upper() in _LOCKED_STATUSES:
                context["errors"].append("\uc2b9\uc778 \uc644\ub8cc \ud6c4\uc5d0\ub294 \uc218\uc815\ud560 \uc218 \uc5c6\uc2b5\ub2c8\ub2e4.")
                return
            if cost_actual.status != CostActualStatus.DRAFT:
                cost_actual.status = CostActualStatus.DRAFT
                cost_actual.save(update_fields=["status", "updated_at"])

            cost_line = cost_actual.lines.order_by("id").first()
            if cost_line is None:
                CostActualLine.objects.create(
                    cost_actual=cost_actual,
                    cost_item=cost_item,
                    description=report_line.description,
                    quantity=report_line.quantity,
                    unit_price=report_line.unit_price,
                    vat_treatment=vat_treatment,
                )
            else:
                cost_line.cost_item = cost_item
                cost_line.description = report_line.description
                cost_line.quantity = report_line.quantity
                cost_line.unit_price = report_line.unit_price
                cost_line.vat_treatment = vat_treatment
                cost_line.save()

            if evidence_file:
                evidence, created = Evidence.objects.get_or_create(
                    object_type="COST_ACTUAL",
                    object_id=cost_actual.id,
                    defaults={
                        "title": f"\uc6d0\uac00 \uc99d\ube59 - {cost_item.get_display_name()}",
                        "description": memo,
                        "created_by": request.user,
                        "status": EvidenceStatus.DRAFT,
                    },
                )
                if not created:
                    evidence.description = memo
                    evidence.status = EvidenceStatus.DRAFT
                    evidence.save(update_fields=["description", "status", "updated_at"])
                file_obj = EvidenceFile.objects.create(
                    evidence=evidence,
                    file=evidence_file,
                    original_name=evidence_file.name,
                    content_type=getattr(evidence_file, "content_type", "")
                    or "application/octet-stream",
                    size_bytes=evidence_file.size,
                    sha256="",
                    created_by=request.user,
                )
                if created:
                    log_action(
                        actor=request.user,
                        action=EVIDENCE_CREATE,
                        object_type="EVIDENCE",
                        object_id=evidence.id,
                        project=project,
                        request=request,
                        after={"title": evidence.title},
                        meta={
                            "object_type": evidence.object_type,
                            "object_id": evidence.object_id,
                        },
                    )
                log_action(
                    actor=request.user,
                    action=EVIDENCE_FILE_ADD,
                    object_type="EVIDENCE",
                    object_id=evidence.id,
                    project=project,
                    request=request,
                    after={"file_id": file_obj.id},
                    meta={
                        "original_name": file_obj.original_name,
                        "size_bytes": file_obj.size_bytes,
                        "content_type": file_obj.content_type,
                        "sha256": file_obj.sha256,
                    },
                )
    except IntegrityError:
        context["errors"].append("\uc6d0\uac00 \uc800\uc7a5\uc5d0 \uc2e4\ud328\ud588\uc2b5\ub2c8\ub2e4.")
        return

    log_action(
        actor=request.user,
        action=DRAFT_SAVE,
        object_type="COST_ACTUAL",
        object_id=cost_actual.id,
        project=project,
        request=request,
        after={"status": cost_actual.status, "report_date": str(report_date)},
    )
    context["success"] = "\uc6d0\uac00\uac00 \uc784\uc2dc\uc800\uc7a5\ub418\uc5c8\uc2b5\ub2c8\ub2e4."

def _load_progress_context(project, user, request, context):
    context["tasks"] = []
    context["progress_task_input_disabled"] = True
    context["progress_tasks_unavailable_message"] = ""
    context["progress_entries"] = []
    context["progress_page_obj"] = None
    context["progress_draft"] = None
    context["progress_reject_reasons"] = {}
    context["retroactive_progress_requests"] = []
    if project is None:
        return
    context["retroactive_progress_requests"] = list(
        RetroactiveEntryRequest.objects.filter(
            project=project,
            requested_by=user,
            request_type="PROGRESS",
        )
        .select_related("reviewed_by")
        .order_by("-requested_at", "-id")[:5]
    )
    plan, tasks = _ensure_progress_tasks_for_project(project)
    context["tasks"] = tasks
    context["progress_task_input_disabled"] = not bool(tasks)
    if not tasks:
        if _get_progress_wbs_queryset(project).exists():
            context["progress_tasks_unavailable_message"] = (
                "이 프로젝트의 진행률 작업을 준비하지 못했습니다. HQ에서 일정 기준선을 확인해 주세요."
            )
        else:
            context["progress_tasks_unavailable_message"] = (
                "이 프로젝트에는 WBS 기준선 작업이 없습니다. HQ에서 WBS 기준선을 등록한 뒤 진행률을 입력할 수 있습니다."
            )
    progress_qs = (
        DailyProgress.objects.filter(project=project, reporter=user)
        .select_related("task")
        .order_by("-report_date", "-updated_at")
    )
    progress_paginator = Paginator(progress_qs, 10)
    progress_page = request.GET.get("progress_page") or 1
    progress_page_obj = progress_paginator.get_page(progress_page)
    context["progress_entries"] = list(progress_page_obj)
    progress_ids = [entry.id for entry in context["progress_entries"]]
    attachments_map = {}
    if progress_ids:
        evidences = list(
            Evidence.objects.filter(
                object_type="DAILY_PROGRESS",
                object_id__in=progress_ids,
            )
            .only("id", "object_id", "created_at")
            .order_by("object_id", "-created_at")
        )
        latest_evidence_ids = {}
        for evidence in evidences:
            latest_evidence_ids.setdefault(evidence.object_id, evidence.id)
        if latest_evidence_ids:
            files_by_evidence = {}
            for evidence_file in EvidenceFile.objects.filter(
                evidence_id__in=latest_evidence_ids.values()
            ).order_by("-created_at"):
                files_by_evidence.setdefault(evidence_file.evidence_id, []).append(evidence_file)
            for object_id, evidence_id in latest_evidence_ids.items():
                attachments_map[object_id] = files_by_evidence.get(evidence_id, [])

        rejected_approvals = (
            ApprovalRequest.objects.filter(
                object_type="DAILY_PROGRESS",
                object_id__in=progress_ids,
                status=ApprovalStatus.REJECTED,
            )
            .order_by("-updated_at")
            .values("object_id", "reject_reason")
        )
        reason_map = {}
        for row in rejected_approvals:
            object_id = row["object_id"]
            if object_id in reason_map:
                continue
            reason_map[object_id] = (row.get("reject_reason") or "").strip()
        context["progress_reject_reasons"] = reason_map
        for entry in context["progress_entries"]:
            entry.reject_reason = reason_map.get(entry.id, "")
            entry.attachments = attachments_map.get(entry.id, [])
    else:
        for entry in context["progress_entries"]:
            entry.reject_reason = ""
            entry.attachments = []
    context["progress_page_obj"] = progress_page_obj
    context["progress_page_range"] = _window_page_range(progress_page_obj)
    context["progress_draft"] = (
        DailyProgress.objects.filter(project=project, reporter=user, status__in=["draft", "rejected"])
        .order_by("-updated_at")
        .first()
    )
    context["progress_existing_files"] = []
    context["progress_can_edit_attachments"] = False
    context["progress_attachment_upload_url"] = None
    context["progress_attachment_hidden_fields"] = {}
    context["progress_attachment_delete_url"] = None
    context["progress_attachment_help_text"] = "제출/승인/마감 상태에서는 첨부를 수정할 수 없습니다."
    context["progress_selected"] = None
    context["progress_focus_mode"] = False
    context["progress_approved_back_url"] = None
    if context["progress_draft"] is not None:
        draft_attachments = attachments_map.get(context["progress_draft"].id)
        if draft_attachments is None:
            progress_evidence = (
                Evidence.objects.filter(
                    object_type="DAILY_PROGRESS",
                    object_id=context["progress_draft"].id,
                )
                .order_by("-created_at")
                .first()
            )
            draft_attachments = (
                list(progress_evidence.files.order_by("-created_at"))
                if progress_evidence is not None
                else []
            )
        context["progress_existing_files"] = draft_attachments
        is_closed_locked = is_project_or_month_locked(
            project=project,
            target_date=context["progress_draft"].report_date,
        )
        can_edit = can_edit_attachments(
            status=context["progress_draft"].status,
            is_closed_locked=is_closed_locked,
        )
        context["progress_can_edit_attachments"] = can_edit
        context["progress_attachment_upload_url"] = (
            f"/app/field/?tab=progress&project_id={project.id}&progress_id={context['progress_draft'].id}"
            if can_edit and project is not None
            else None
        )
        context["progress_attachment_hidden_fields"] = {
            "tab": "progress",
            "project_id": str(project.id) if project is not None else "",
            "progress_id": str(context["progress_draft"].id),
        }
        context["progress_attachment_delete_url"] = context["progress_attachment_upload_url"]
        context["progress_attachment_help_text"] = (
            "임시저장/반려 상태에서는 제출 전까지 첨부를 수정할 수 있습니다."
            if can_edit
            else "제출/승인/마감 상태에서는 첨부를 수정할 수 없습니다."
        )
    today = timezone.localdate()
    has_today_draft = DailyProgress.objects.filter(
        project=project,
        reporter=user,
        report_date=today,
        status="draft",
    ).exists()
    has_today_submitted = DailyProgress.objects.filter(
        project=project,
        reporter=user,
        report_date=today,
        status="submitted",
    ).exists()
    context["show_today_progress_banner"] = has_today_draft and not has_today_submitted
    context["progress_editing"] = False
    edit_id = request.GET.get("progress_id")
    if edit_id:
        edit_progress = DailyProgress.objects.filter(
            id=edit_id, project=project, reporter=user, status__in=["draft", "rejected"]
        ).first()
        if edit_progress:
            context["progress_draft"] = edit_progress
            context["progress_editing"] = True
            progress_evidence = (
                Evidence.objects.filter(
                    object_type="DAILY_PROGRESS",
                    object_id=edit_progress.id,
                )
                .order_by("-created_at")
                .first()
            )
            context["progress_existing_files"] = (
                list(progress_evidence.files.order_by("-created_at"))
                if progress_evidence is not None
                else []
            )
            is_closed_locked = is_project_or_month_locked(
                project=project,
                target_date=edit_progress.report_date,
            )
            can_edit = can_edit_attachments(
                status=edit_progress.status,
                is_closed_locked=is_closed_locked,
            )
            context["progress_can_edit_attachments"] = can_edit
            context["progress_attachment_upload_url"] = (
                f"/app/field/?tab=progress&project_id={project.id}&progress_id={edit_progress.id}"
                if can_edit and project is not None
                else None
            )
            context["progress_attachment_delete_url"] = context["progress_attachment_upload_url"]
            context["progress_attachment_hidden_fields"] = {
                "tab": "progress",
                "project_id": str(project.id) if project is not None else "",
                "progress_id": str(edit_progress.id),
            }
            context["progress_attachment_help_text"] = (
                "임시저장/반려 상태에서는 제출 전까지 첨부를 수정할 수 있습니다."
                if can_edit
                else "제출/승인/마감 상태에서는 첨부를 수정할 수 없습니다."
            )
        else:
            # Read-only selection path for submitted/approved entries opened from approved list.
            selected_progress = DailyProgress.objects.filter(
                id=edit_id,
                project=project,
                reporter=user,
            ).select_related("task", "reporter").first()
            if selected_progress:
                selected_attachments = attachments_map.get(selected_progress.id)
                if selected_attachments is None:
                    selected_evidence = (
                        Evidence.objects.filter(
                            object_type="DAILY_PROGRESS",
                            object_id=selected_progress.id,
                        )
                        .order_by("-created_at")
                        .first()
                    )
                    selected_attachments = (
                        list(selected_evidence.files.order_by("-created_at"))
                        if selected_evidence is not None
                        else []
                    )
                selected_progress.attachments = selected_attachments
                selected_progress.reject_reason = context["progress_reject_reasons"].get(
                    selected_progress.id, ""
                )
                context["progress_selected"] = selected_progress
                context["progress_focus_mode"] = True
                approved_type = (request.GET.get("approved_type") or "progress").strip() or "progress"
                approved_from = (request.GET.get("approved_from") or "").strip()
                approved_to = (request.GET.get("approved_to") or "").strip()
                approved_project = (
                    (request.GET.get("approved_project_id") or "").strip()
                    or (str(project.id) if project is not None else "")
                )
                approved_parts = [f"type={approved_type}"]
                if approved_from:
                    approved_parts.append(f"from={approved_from}")
                if approved_to:
                    approved_parts.append(f"to={approved_to}")
                if approved_project:
                    approved_parts.append(f"project_id={approved_project}")
                context["progress_approved_back_url"] = "/app/field/approved/?" + "&".join(
                    approved_parts
                )


def _load_evidence_context(project, user, context):
    context["evidence_list"] = []
    context["evidence_draft"] = None
    if project is None:
        return
    cost_actual_ids = list(
        CostActual.objects.filter(project=project).values_list("id", flat=True)
    )
    evidence_qs = Evidence.objects.filter(
        Q(object_type="PROJECT", object_id=project.id)
        | Q(object_type="COST_ACTUAL", object_id__in=cost_actual_ids)
    )
    if get_user_role(user) == Role.FIELD:
        evidence_qs = evidence_qs.filter(created_by=user)
    context["evidence_list"] = list(
        evidence_qs.prefetch_related("files").order_by("-created_at")
    )
    context["evidence_draft"] = (
        Evidence.objects.filter(
            object_type="PROJECT",
            object_id=project.id,
            created_by=user,
            status__in=[EvidenceStatus.DRAFT],
        )
        .order_by("-updated_at")
        .first()
    )


def _load_report_context(project, user, request, context):
    context["field_reports"] = []
    context["report_page_obj"] = None
    if project is None:
        return
    reports = FieldReport.objects.filter(project=project)
    if get_user_role(user) == Role.FIELD:
        reports = reports.filter(created_by=user)
    reports_qs = reports.prefetch_related("files").order_by("-updated_at")
    report_paginator = Paginator(reports_qs, 10)
    report_page = request.GET.get("report_page") or 1
    report_page_obj = report_paginator.get_page(report_page)
    context["field_reports"] = list(report_page_obj)
    reject_reason_map = {}
    approval_status_map = {}
    if context["field_reports"]:
        report_ids = [report.id for report in context["field_reports"]]
        rejected_reports = (
            ApprovalRequest.objects.filter(
                object_type="FIELD_REPORT",
                object_id__in=report_ids,
                status=ApprovalStatus.REJECTED,
            )
            .order_by("-created_at")
            .values("object_id", "status", "reject_reason")
        )
        for row in rejected_reports:
            object_id = row.get("object_id")
            if object_id in approval_status_map:
                continue
            approval_status_map[object_id] = (row.get("status") or "").upper()
            reject_reason_map[object_id] = (row.get("reject_reason") or "").strip()
    for report in context["field_reports"]:
        report.display_status = approval_status_map.get(report.id, report.status)
        report.reject_reason = reject_reason_map.get(report.id, "")
    context["report_page_obj"] = report_page_obj
    context["report_page_range"] = _window_page_range(report_page_obj)


def _load_cost_context(project, user, request, context):
    context["cost_selected"] = None
    context["cost_focus_mode"] = False
    context["cost_approved_back_url"] = None
    context["cost_items"] = list(
        CostItem.objects.filter(is_active=True)
        .prefetch_related("aliases")
        .order_by("sort_order", "name")
    )
    context["cost_reports"] = []
    context["cost_page_obj"] = None
    context["cost_draft"] = None
    if project is None:
        return
    cost_qs = (
        CostActual.objects.filter(project=project, source_daily_report__reporter=user)
        .select_related("source_daily_report")
        .prefetch_related("lines__cost_item__aliases")
        .order_by("-report_date", "-updated_at")
    )
    cost_paginator = Paginator(cost_qs, 10)
    cost_page = request.GET.get("cost_page") or 1
    cost_page_obj = cost_paginator.get_page(cost_page)
    context["cost_reports"] = list(cost_page_obj)
    context["cost_page_obj"] = cost_page_obj
    context["cost_page_range"] = _window_page_range(cost_page_obj)
    cost_attachments_map = {}
    if context["cost_reports"]:
        cost_actual_ids = [report.id for report in context["cost_reports"]]
        evidence_qs = (
            Evidence.objects.filter(
                object_type="COST_ACTUAL",
                object_id__in=cost_actual_ids,
            )
            .prefetch_related("files")
            .order_by("-created_at")
        )
        for evidence in evidence_qs:
            cost_attachments_map.setdefault(evidence.object_id, []).extend(
                list(evidence.files.all().order_by("-created_at"))
            )
    for report in context["cost_reports"]:
        report.attachments = cost_attachments_map.get(report.id, [])
    cost_reject_reason_map = {}
    if context["cost_reports"]:
        cost_actual_ids = [report.id for report in context["cost_reports"]]
        rejected_cost_approvals = (
            ApprovalRequest.objects.filter(
                object_type="COST_ACTUAL",
                object_id__in=cost_actual_ids,
                status=ApprovalStatus.REJECTED,
            )
            .order_by("-created_at")
            .values("object_id", "reject_reason")
        )
        for row in rejected_cost_approvals:
            object_id = row.get("object_id")
            if object_id in cost_reject_reason_map:
                continue
            cost_reject_reason_map[object_id] = (row.get("reject_reason") or "").strip()
    for report in context["cost_reports"]:
        report.reject_reason = cost_reject_reason_map.get(report.id, "")

    selected_cost_id = (request.GET.get("cost_id") or "").strip()
    if selected_cost_id:
        try:
            selected_cost_id_int = int(selected_cost_id)
        except (TypeError, ValueError):
            selected_cost_id_int = None
        if selected_cost_id_int:
            selected = (
                CostActual.objects.filter(
                    id=selected_cost_id_int,
                    project=project,
                    source_daily_report__reporter=user,
                )
                .select_related("source_daily_report")
                .prefetch_related("lines__cost_item__aliases")
                .first()
            )
            if selected is not None:
                selected_evidences = (
                    Evidence.objects.filter(
                        object_type="COST_ACTUAL",
                        object_id=selected.id,
                    )
                    .prefetch_related("files")
                    .order_by("-created_at")
                )
                selected_attachments = []
                selected_seen_file_ids = set()
                for evidence in selected_evidences:
                    for evidence_file in evidence.files.all().order_by("-created_at"):
                        if evidence_file.id in selected_seen_file_ids:
                            continue
                        selected_seen_file_ids.add(evidence_file.id)
                        selected_attachments.append(evidence_file)
                selected.attachments = selected_attachments
                selected.reject_reason = (
                    ApprovalRequest.objects.filter(
                        object_type="COST_ACTUAL",
                        object_id=selected.id,
                        status=ApprovalStatus.REJECTED,
                    )
                    .order_by("-created_at")
                    .values_list("reject_reason", flat=True)
                    .first()
                    or ""
                )
                context["cost_selected"] = selected
                context["cost_focus_mode"] = True

                approved_type = (request.GET.get("approved_type") or "cost").strip() or "cost"
                approved_from = (request.GET.get("approved_from") or "").strip()
                approved_to = (request.GET.get("approved_to") or "").strip()
                approved_project = (
                    (request.GET.get("approved_project_id") or "").strip()
                    or (request.GET.get("project_id") or "").strip()
                )
                approved_parts = [f"type={approved_type}"]
                if approved_from:
                    approved_parts.append(f"from={approved_from}")
                if approved_to:
                    approved_parts.append(f"to={approved_to}")
                if approved_project:
                    approved_parts.append(f"project_id={approved_project}")
                context["cost_approved_back_url"] = "/app/field/approved/?" + "&".join(
                    approved_parts
                )

    cost_drafts = list(
        CostActual.objects.filter(
            project=project,
            source_daily_report__reporter=user,
            status__in=[CostActualStatus.DRAFT, CostActualStatus.REJECTED],
        ).order_by("-updated_at")
    )
    context["cost_drafts"] = cost_drafts
    context["cost_drafts_count"] = len(cost_drafts)
    context["cost_draft"] = cost_drafts[0] if cost_drafts else None
    context["cost_draft_line"] = None
    context["cost_existing_files"] = []
    if context["cost_draft"]:
        context["cost_draft_line"] = (
            context["cost_draft"].lines.order_by("id").first()
        )
        cost_evidence = (
            Evidence.objects.filter(
                object_type="COST_ACTUAL",
                object_id=context["cost_draft"].id,
            )
            .order_by("-created_at")
            .first()
        )
        if cost_evidence is not None:
            context["cost_existing_files"] = list(
                cost_evidence.files.order_by("-created_at")
            )


@login_required
def field_wbs_change_new(request, project_id):
    project = get_object_or_404(Project, id=project_id)
    _require_current_entity_project(request, project)
    role = get_user_role(request.user)
    return render_wbs_change_form(
        request,
        project,
        role,
        template_name="app/common/wbs_change_form.html",
        back_url=f"/app/field/?tab=progress&project_id={project.id}",
    )


def _parse_iso_date(value):
    if not value:
        return None
    try:
        return date.fromisoformat(value)
    except (TypeError, ValueError):
        return None


def _safe_local_iso(dt):
    if dt is None:
        return None
    if isinstance(dt, datetime):
        return timezone.localtime(dt).isoformat()
    return None


@login_required
def field_approved_list(request):
    role = get_user_role(request.user)
    if role != Role.FIELD:
        raise PermissionDenied("Access denied.")

    # Discovery note:
    # - Approval source: apps.core.models.ApprovalRequest (status=approved, approved_at)
    # - Type mapping: DAILY_PROGRESS / FIELD_REPORT / COST_ACTUAL
    # - Field scope: apps.core.rbac.permissions + ProjectAssignment via _get_accessible_projects
    type_param = (request.GET.get("type") or "").strip().lower()
    project_param = (request.GET.get("project_id") or "").strip()
    response_format = (request.GET.get("format") or "").strip().lower()
    wants_json = response_format == "json"
    from_param = _parse_iso_date(request.GET.get("from"))
    to_param = _parse_iso_date(request.GET.get("to"))
    if to_param is None:
        to_param = timezone.localdate()
    if from_param is None:
        from_param = to_param - timedelta(days=29)
    if from_param > to_param:
        from_param, to_param = to_param, from_param

    type_map = {
        "progress": {"DAILY_PROGRESS"},
        "report": {"FIELD_REPORT"},
        "cost": {"COST_ACTUAL"},
    }
    allowed_types = (
        type_map.get(type_param)
        if type_param in type_map
        else {"DAILY_PROGRESS", "FIELD_REPORT", "COST_ACTUAL"}
    )

    accessible_projects = _get_accessible_projects(request.user).filter(
        legal_entity=get_current_legal_entity(request)
    )
    project_ids = list(accessible_projects.values_list("id", flat=True))
    selected_project_id = None
    if project_param and project_param.isdigit():
        candidate_project_id = int(project_param)
        if candidate_project_id in project_ids:
            selected_project_id = candidate_project_id
            project_ids = [candidate_project_id]
    if not project_ids:
        payload = {
            "items": [],
            "filters": {
                "type": type_param or "all",
                "from": from_param.isoformat(),
                "to": to_param.isoformat(),
                "project_id": selected_project_id,
            },
            "count": 0,
        }
        if wants_json:
            return JsonResponse(payload)
        return render(
            request,
            "field/approved_list.html",
            {
                "items": [],
                "filters": payload["filters"],
                "projects": accessible_projects,
                "count": 0,
            },
        )

    approvals = list(
        ApprovalRequest.objects.filter(
            status=ApprovalStatus.APPROVED,
            object_type__in=sorted(allowed_types),
            approved_at__date__gte=from_param,
            approved_at__date__lte=to_param,
        )
        .select_related("submitted_by", "approved_by")
        .order_by("-approved_at", "-updated_at")
    )

    progress_ids = [
        a.object_id for a in approvals if (a.object_type or "").upper() == "DAILY_PROGRESS"
    ]
    report_ids = [
        a.object_id for a in approvals if (a.object_type or "").upper() == "FIELD_REPORT"
    ]
    cost_ids = [
        a.object_id for a in approvals if (a.object_type or "").upper() == "COST_ACTUAL"
    ]

    progress_map = {
        row.id: row
        for row in DailyProgress.objects.filter(
            id__in=progress_ids, project_id__in=project_ids
        )
        .select_related("project", "task")
        .only("id", "project_id", "project__name", "task__name", "report_date", "progress_percent", "note")
    }
    report_map = {
        row.id: row
        for row in FieldReport.objects.filter(id__in=report_ids, project_id__in=project_ids)
        .select_related("project", "created_by")
        .prefetch_related("files")
        .only("id", "project_id", "project__name", "title", "report_date", "content", "created_by__username")
    }
    cost_map = {
        row.id: row
        for row in CostActual.objects.filter(id__in=cost_ids, project_id__in=project_ids)
        .select_related("project")
        .only("id", "project_id", "project__name", "report_date", "total_amount")
    }

    evidence_q = Q()
    if progress_map:
        evidence_q |= Q(object_type="DAILY_PROGRESS", object_id__in=list(progress_map.keys()))
    if report_map:
        evidence_q |= Q(object_type="FIELD_REPORT", object_id__in=list(report_map.keys()))
    if cost_map:
        evidence_q |= Q(object_type="COST_ACTUAL", object_id__in=list(cost_map.keys()))
    attachments_count_map = {}
    attachments_map = {}
    if evidence_q:
        evidences = Evidence.objects.filter(evidence_q).prefetch_related("files")
        for evidence in evidences:
            key = ((evidence.object_type or "").upper(), evidence.object_id)
            files = list(evidence.files.all())
            if not files:
                continue
            attachments_count_map[key] = attachments_count_map.get(key, 0) + len(files)
            attachments_map.setdefault(key, []).extend(files)

    items = []
    for approval in approvals:
        object_type = (approval.object_type or "").upper()
        object_id = approval.object_id
        obj = None
        summary = ""
        event_date = None
        project_name = ""
        type_label = "기타"
        detail_url = ""
        approved_qs = (
            f"type={type_param or 'all'}&from={from_param.isoformat()}&to={to_param.isoformat()}"
            + (f"&project_id={selected_project_id}" if selected_project_id else "")
        )
        if object_type == "DAILY_PROGRESS":
            obj = progress_map.get(object_id)
            if obj is None:
                continue
            type_label = "진행률"
            event_date = obj.report_date
            project_name = obj.project.name
            progress_value = _normalize_progress_percent(obj.progress_percent)
            if progress_value is not None:
                summary = f"{obj.task.name} / {progress_value}%"
            else:
                summary = obj.task.name
            detail_url = (
                f"/app/field/?tab=progress&project_id={obj.project_id}&progress_id={obj.id}"
                f"&approved_type={type_param or 'all'}"
                f"&approved_from={from_param.isoformat()}"
                f"&approved_to={to_param.isoformat()}"
                + (f"&approved_project_id={selected_project_id}" if selected_project_id else "")
            )
        elif object_type == "FIELD_REPORT":
            obj = report_map.get(object_id)
            if obj is None:
                continue
            type_label = "보고서"
            event_date = obj.report_date
            project_name = obj.project.name
            summary = (obj.title or "").strip() or "현장 보고서"
            detail_url = f"/app/reports/{obj.id}/?from_approved={approved_qs}"
        elif object_type == "COST_ACTUAL":
            obj = cost_map.get(object_id)
            if obj is None:
                continue
            type_label = "원가"
            event_date = obj.report_date
            project_name = obj.project.name
            summary = f"합계 {obj.total_amount:,.2f}"
            # Route approved cost rows through Field cost tab detail context.
            # Direct /app/field/cost/<id>/ may redirect to edit flow and hit role/state guards.
            detail_url = (
                f"/app/field/?tab=cost&project_id={obj.project_id}&cost_id={obj.id}"
                f"&approved_type={type_param or 'all'}"
                f"&approved_from={from_param.isoformat()}"
                f"&approved_to={to_param.isoformat()}"
                + (f"&approved_project_id={selected_project_id}" if selected_project_id else "")
            )
        else:
            continue

        report_attachments = []
        if object_type == "FIELD_REPORT":
            # Field report attachments are stored directly on FieldReportFile,
            # not only via Evidence, so map them explicitly.
            report_attachments = list(obj.files.all())
        attachments = report_attachments or attachments_map.get((object_type, object_id), [])

        items.append(
            {
                "id": approval.id,
                "approved_at": _safe_local_iso(
                    approval.approved_at or approval.updated_at
                ),
                "approved_at_display": timezone.localtime(
                    approval.approved_at or approval.updated_at
                ).strftime("%Y-%m-%d %H:%M")
                if (approval.approved_at or approval.updated_at)
                else "-",
                "project_name": project_name,
                "project_id": getattr(obj, "project_id", None),
                "object_id": object_id,
                "object_type": object_type,
                "type": type_label,
                "summary": summary,
                "date": event_date.isoformat() if event_date else None,
                "attachments_count": len(attachments),
                "attachments": attachments,
                "detail_url": detail_url,
            }
        )

    payload = {
        "items": items,
        "filters": {
            "type": type_param or "all",
            "from": from_param.isoformat(),
            "to": to_param.isoformat(),
            "project_id": selected_project_id,
        },
        "count": len(items),
    }
    if wants_json:
        return JsonResponse(payload)
    return render(
        request,
        "field/approved_list.html",
        {
            "items": items,
            "filters": payload["filters"],
            "projects": accessible_projects,
            "count": len(items),
        },
    )



