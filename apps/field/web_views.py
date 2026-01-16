from __future__ import annotations

from datetime import date
from decimal import Decimal, InvalidOperation

from django.contrib import messages
from django.contrib.auth.decorators import login_required
from django.core.exceptions import PermissionDenied
from django.core.paginator import Paginator
from django.db import IntegrityError, transaction
from django.db.models import Q
from django.shortcuts import get_object_or_404, redirect, render
from django.utils import timezone

from apps.audit.constants import DRAFT_SAVE, EVIDENCE_CREATE, EVIDENCE_FILE_ADD, SUBMIT
from apps.audit.services.logger import log_action
from apps.core.models import ApprovalRequest, ApprovalStatus
from apps.core.rbac.models import Role
from apps.core.rbac.permissions import get_user_role, require_project_access
from apps.cost.models import CostActual, CostActualLine, CostActualStatus, CostItem
from apps.evidence.models import Evidence, EvidenceFile, EvidenceStatus
from apps.reports.models import FieldReport, FieldReportStatus
from apps.field.models import DailyReport, DailyReportLine, DailyReportStatus
from apps.projects.models import Project
from apps.schedule.models import DailyProgress, SchedulePlan, ScheduleTask


_LOCKED_STATUSES = {"SUBMITTED", "APPROVED", "FINAL", "LOCKED", "CLOSED"}


def _get_accessible_projects(user):
    role = get_user_role(user)
    if role in (Role.CEO, Role.HQ):
        return Project.objects.all().order_by("name")
    if role == Role.FIELD:
        return Project.objects.filter(
            projectassignment__user=user, projectassignment__is_active=True
        ).order_by("name")
    return Project.objects.none()


def _resolve_project(user, project_id):
    if not project_id:
        return None
    require_project_access(user, project_id)
    return Project.objects.filter(id=project_id).first()


def _parse_decimal(value, default=Decimal("0")):
    try:
        return Decimal(value)
    except (InvalidOperation, TypeError):
        return default


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
    if tab == "evidence":
        tab = "report"
    projects = _get_accessible_projects(request.user)
    project_id = request.GET.get("project_id") or request.POST.get("project_id")
    project = _resolve_project(request.user, project_id) if project_id else None

    context = {
        "tab": tab,
        "projects": projects,
        "project": project,
        "errors": [],
        "success": "",
        "now": date.today().isoformat(),
        "role": get_user_role(request.user),
    }

    if project_id and project is None:
        raise PermissionDenied("Project access denied.")

    if request.method == "POST" and project:
        if tab == "progress":
            _handle_progress_submit(request, project, context)
        elif tab == "report":
            context["errors"].append("보고서는 /app/reports/에서 작성하세요.")
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
def field_cost_edit(request, cost_actual_id):
    cost_actual = get_object_or_404(CostActual, id=cost_actual_id)
    project = cost_actual.project
    require_project_access(request.user, project.id)

    role = get_user_role(request.user)
    report = cost_actual.source_daily_report
    if role == Role.FIELD:
        if report is None or report.reporter_id != request.user.id:
            raise PermissionDenied("Cost edit not allowed.")
        if _is_cost_locked(cost_actual):
            raise PermissionDenied("Cost is locked after approval.")

    line = cost_actual.lines.order_by("id").first()
    evidence = Evidence.objects.filter(
        object_type="COST_ACTUAL", object_id=cost_actual.id
    ).first()

    if request.method == "POST":
        action = request.POST.get("action", "draft")
        if action == "submit":
            if str(cost_actual.status).lower() != "draft":
                messages.error(request, "임시저장 상태에서만 제출할 수 있습니다.")
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
        memo = (request.POST.get("memo") or "").strip()
        file_obj = request.FILES.get("evidence_file")
        cost_item = None
        if cost_item_id:
            cost_item = CostItem.objects.filter(id=cost_item_id, is_active=True).first()
        if cost_item is None:
            return render(
                request,
                "app/cost_edit.html",
                {
                    "cost_actual": cost_actual,
                    "line": line,
                    "cost_items": list(CostItem.objects.filter(is_active=True)),
                    "error": "?? ??? ?????.",
                },
            )
        if quantity is None or unit_price is None:
            return render(
                request,
                "app/cost_edit.html",
                {
                    "cost_actual": cost_actual,
                    "line": line,
                    "cost_items": list(CostItem.objects.filter(is_active=True)),
                    "error": "??/??? ?????.",
                },
            )
        if line:
            line.cost_item = cost_item
            line.quantity = quantity
            line.unit_price = unit_price
            line.description = memo
            line.save()
        else:
            line = CostActualLine.objects.create(
                cost_actual=cost_actual,
                cost_item=cost_item,
                description=memo,
                quantity=quantity,
                unit_price=unit_price,
            )

        if report and memo:
            report.note = memo
            report.save(update_fields=["note", "updated_at"])

        if file_obj:
            if evidence is None:
                evidence = Evidence.objects.create(
                    object_type="COST_ACTUAL",
                    object_id=cost_actual.id,
                    title=f"원가 증빙 - {line.cost_item.name}",
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

    return render(
        request,
        "app/cost_edit.html",
        {
            "cost_actual": cost_actual,
            "line": line,
            "evidence": evidence,
            "cost_items": list(CostItem.objects.filter(is_active=True)),
        },
    )


@login_required
def field_progress_edit(request, progress_id):
    progress = get_object_or_404(DailyProgress, id=progress_id)
    project = progress.project
    require_project_access(request.user, project.id)

    role = get_user_role(request.user)
    if role == Role.FIELD:
        if progress.reporter_id != request.user.id:
            raise PermissionDenied("Progress edit not allowed.")
        if _is_progress_locked(progress):
            raise PermissionDenied("Progress is locked after submission.")

    plan = SchedulePlan.objects.filter(project=project, is_active=True).first()
    tasks = list(
        ScheduleTask.objects.filter(plan=plan, is_active=True).order_by("sort_order")
        if plan
        else []
    )

    if request.method == "POST":
        action = request.POST.get("action", "draft")
        task_id = request.POST.get("task_id")
        progress_percent = _parse_decimal(request.POST.get("progress_percent"), None)
        note = (request.POST.get("note") or "").strip()
        report_date = progress.report_date

        if action == "submit":
            if str(progress.status).lower() != "draft":
                messages.error(request, "Only draft items can be submitted.")
                return redirect(f"/app/field/?tab=progress&project_id={project.id}")
            progress.status = "submitted"
            progress.save(update_fields=["status", "updated_at"])
            log_action(
                actor=request.user,
                action=SUBMIT,
                object_type="DAILY_PROGRESS",
                object_id=progress.id,
                project=project,
                request=request,
                after={
                    "status": progress.status,
                    "report_date": str(progress.report_date),
                },
            )
            messages.success(request, "진행률이 제출되었습니다.")
            return redirect(f"/app/field/?tab=progress&project_id={project.id}")

        if not task_id or progress_percent is None:
            messages.error(request, "태스크와 진행률을 입력하세요.")
            return redirect(f"/app/field/progress/{progress.id}/edit/")
        if progress_percent < 0 or progress_percent > 100:
            messages.error(request, "진행률은 0~100 범위여야 합니다.")
            return redirect(f"/app/field/progress/{progress.id}/edit/")

        task = ScheduleTask.objects.filter(id=task_id, plan__project=project).first()
        if task is None:
            messages.error(request, "태스크를 찾을 수 없습니다.")
            return redirect(f"/app/field/progress/{progress.id}/edit/")

        progress.task = task
        progress.progress_percent = progress_percent
        progress.note = note
        progress.report_date = report_date
        progress.status = "draft"
        progress.save(
            update_fields=[
                "task",
                "progress_percent",
                "note",
                "report_date",
                "status",
                "updated_at",
            ]
        )
        log_action(
            actor=request.user,
            action=DRAFT_SAVE,
            object_type="DAILY_PROGRESS",
            object_id=progress.id,
            project=project,
            request=request,
            after={"status": progress.status, "report_date": str(progress.report_date)},
        )
        messages.success(request, "진행률이 임시저장되었습니다.")
        return redirect(f"/app/field/?tab=progress&project_id={project.id}")

    return render(
        request,
        "app/progress_edit.html",
        {"progress": progress, "project": project, "tasks": tasks},
    )


def _handle_progress_submit(request, project, context):
    action = request.POST.get("action", "draft")
    progress_id = request.POST.get("progress_id")
    task_id = request.POST.get("task_id")
    progress_percent = _parse_decimal(request.POST.get("progress_percent"), None)
    note = (request.POST.get("note") or "").strip()
    report_date = request.POST.get("report_date") or date.today().isoformat()

    if action == "submit":
        progress = None
        if progress_id:
            progress = DailyProgress.objects.filter(
                id=progress_id, project=project, reporter=request.user
            ).first()
        if progress is None:
            progress = (
                DailyProgress.objects.filter(
                    project=project, reporter=request.user, status="draft"
                )
                .order_by("-updated_at")
                .first()
            )
        if progress is None:
            context["errors"].append("임시저장 내역이 없어 제출할 수 없습니다.")
            return
        if _is_progress_locked(progress):
            context["errors"].append("승인 완료 후에는 수정/제출할 수 없습니다.")
            return
        if str(progress.status).lower() != "draft":
            context["errors"].append("Only draft items can be submitted.")
            return
        progress.status = "submitted"
        progress.save(update_fields=["status", "updated_at"])
        log_action(
            actor=request.user,
            action=SUBMIT,
            object_type="DAILY_PROGRESS",
            object_id=progress.id,
            project=project,
            request=request,
            after={"status": progress.status, "report_date": str(progress.report_date)},
        )
        context["success"] = "진행률이 제출되었습니다."
        return

    if not task_id or progress_percent is None:
        context["errors"].append("태스크와 진행률을 입력하세요.")
        return
    if progress_percent < 0 or progress_percent > 100:
        context["errors"].append("진행률은 0~100 범위여야 합니다.")
        return

    task = ScheduleTask.objects.filter(id=task_id, plan__project=project).first()
    if task is None:
        context["errors"].append("태스크를 찾을 수 없습니다.")
        return

    plan = SchedulePlan.objects.filter(project=project, is_active=True).first()
    if plan is None:
        context["errors"].append("활성 계획이 없습니다.")
        return

    existing_progress = DailyProgress.objects.filter(
        task=task, report_date=report_date, reporter=request.user
    ).first()
    if existing_progress and _is_progress_locked(existing_progress):
        context["errors"].append("Submitted items cannot be edited.")
        return

    progress, _created = DailyProgress.objects.update_or_create(
        task=task,
        report_date=report_date,
        reporter=request.user,
        defaults={
            "project": project,
            "plan": plan,
            "progress_percent": progress_percent,
            "note": note,
            "status": "draft",
        },
    )
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
            context["errors"].append("승인 완료 후에는 제출할 수 없습니다.")
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
        context["errors"].append("제목을 입력하세요.")
        return

    evidence = None
    if evidence_id:
        evidence = Evidence.objects.filter(
            id=evidence_id, created_by=request.user
        ).first()
        if evidence is not None and evidence.status != EvidenceStatus.DRAFT:
            context["errors"].append("승인 완료 후에는 수정할 수 없습니다.")
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
    cost_item_id = request.POST.get("cost_item_id")
    quantity = _parse_decimal_amount(request.POST.get("quantity"))
    unit_price = _parse_decimal_amount(request.POST.get("unit_price"))
    memo = (request.POST.get("memo") or "").strip()
    evidence_file = request.FILES.get("evidence_file")

    cost_item = None
    if action != "submit":
        cost_actual_id = None
        if not cost_item_id or quantity is None or unit_price is None:
            context["errors"].append("원가 항목과 금액을 입력하세요.")
            return
        if quantity < 0 or unit_price < 0:
            context["errors"].append("금액은 0 이상이어야 합니다.")
            return
        cost_item = CostItem.objects.filter(id=cost_item_id, is_active=True).first()
        if cost_item is None:
            context["errors"].append("원가 항목을 찾을 수 없습니다.")
            return

    report_date = date.today()
    try:
        with transaction.atomic():
            if action == "submit":
                cost_actual = None
                cost_actual = (
                    CostActual.objects.filter(id=cost_actual_id, project=project).first()
                    if cost_actual_id
                    else None
                )
                if cost_actual is None:
                    draft_qs = CostActual.objects.filter(
                        project=project,
                        source_daily_report__reporter=request.user,
                        status=CostActualStatus.DRAFT,
                    ).order_by("-updated_at")
                    draft_count = draft_qs.count()
                    if draft_count > 1:
                        context["errors"].append("임시저장 건이 여러 건입니다. 목록에서 날짜를 선택해 제출해 주세요.")
                        return
                    if draft_count == 1:
                        cost_actual = draft_qs.first()
                    if cost_actual is None:
                        report_qs = DailyReport.objects.filter(
                            project=project,
                            reporter=request.user,
                            status=DailyReportStatus.DRAFT,
                        ).order_by("-updated_at")
                        if report_qs.count() > 1:
                            context["errors"].append("임시저장 건이 여러 건입니다. 목록에서 날짜를 선택해 제출해 주세요.")
                            return
                        report = report_qs.first()
                        cost_actual = getattr(report, "costactual", None) if report else None
                if cost_actual is None or _is_cost_locked(cost_actual):
                    context["errors"].append("임시저장 내역이 없어 제출할 수 없습니다.")
                    return
                if str(cost_actual.status).lower() != "draft":
                    context["errors"].append("Only draft costs can be submitted.")
                    return
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
                    after={"status": cost_actual.status, "report_date": str(report_date)},
                )
                context["success"] = "원가가 제출되었습니다."
                return

            cost_actual = None
            report = DailyReport.objects.create(
                project=project,
                report_date=report_date,
                reporter=request.user,
                note=memo,
                status=DailyReportStatus.DRAFT,
            )
            if report.status == DailyReportStatus.APPROVED:
                context["errors"].append("?? ??? ??????.")
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

            if cost_actual is None:
                cost_actual = getattr(report, "costactual", None)
            if cost_actual is None:
                cost_actual = CostActual.objects.create(
                    project=project,
                    report_date=report.report_date,
                    source_daily_report=report,
                    status=CostActualStatus.DRAFT,
                )
            if str(cost_actual.status).upper() in _LOCKED_STATUSES:
                context["errors"].append("승인 완료 후에는 수정할 수 없습니다.")
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
                )
            else:
                cost_line.cost_item = cost_item
                cost_line.description = report_line.description
                cost_line.quantity = report_line.quantity
                cost_line.unit_price = report_line.unit_price
                cost_line.save()

            if evidence_file:
                evidence, created = Evidence.objects.get_or_create(
                    object_type="COST_ACTUAL",
                    object_id=cost_actual.id,
                    defaults={
                        "title": f"원가 증빙 - {cost_item.name}",
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
        context["errors"].append("원가 저장에 실패했습니다.")
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
    context["success"] = "원가가 임시저장되었습니다."


def _load_progress_context(project, user, request, context):
    context["tasks"] = []
    context["progress_entries"] = []
    context["progress_page_obj"] = None
    context["progress_draft"] = None
    if project is None:
        return
    plan = SchedulePlan.objects.filter(project=project, is_active=True).first()
    if plan:
        context["tasks"] = list(
            ScheduleTask.objects.filter(plan=plan, is_active=True).order_by("sort_order")
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
    context["progress_page_obj"] = progress_page_obj
    context["progress_page_range"] = _window_page_range(progress_page_obj)
    context["progress_draft"] = (
        DailyProgress.objects.filter(project=project, reporter=user, status__in=["draft"])
        .order_by("-updated_at")
        .first()
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
    context["report_page_obj"] = report_page_obj
    context["report_page_range"] = _window_page_range(report_page_obj)


def _load_cost_context(project, user, request, context):
    context["cost_items"] = list(
        CostItem.objects.filter(is_active=True).order_by("sort_order", "name")
    )
    context["cost_reports"] = []
    context["cost_page_obj"] = None
    context["cost_draft"] = None
    if project is None:
        return
    cost_qs = (
        CostActual.objects.filter(project=project, source_daily_report__reporter=user)
        .select_related("source_daily_report")
        .prefetch_related("lines__cost_item")
        .order_by("-report_date", "-updated_at")
    )
    cost_paginator = Paginator(cost_qs, 10)
    cost_page = request.GET.get("cost_page") or 1
    cost_page_obj = cost_paginator.get_page(cost_page)
    context["cost_reports"] = list(cost_page_obj)
    context["cost_page_obj"] = cost_page_obj
    context["cost_page_range"] = _window_page_range(cost_page_obj)
    cost_drafts = list(
        CostActual.objects.filter(
            project=project,
            source_daily_report__reporter=user,
            status__in=[CostActualStatus.DRAFT],
        ).order_by("-updated_at")
    )
    context["cost_drafts"] = cost_drafts
    context["cost_drafts_count"] = len(cost_drafts)
    context["cost_draft"] = cost_drafts[0] if len(cost_drafts) == 1 else None
    context["cost_draft_line"] = None
    if context["cost_draft"]:
        context["cost_draft_line"] = (
            context["cost_draft"].lines.order_by("id").first()
        )
