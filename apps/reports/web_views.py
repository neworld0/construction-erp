from datetime import date
from urllib.parse import urlencode

from django.contrib import messages
from django.contrib.auth.decorators import login_required
from django.core.exceptions import PermissionDenied
from django.http import QueryDict
from django.shortcuts import get_object_or_404, redirect, render
from django.utils import timezone

from apps.closing.guards import guard_write
from apps.core.models import ApprovalRequest, ApprovalStatus
from apps.core.rbac.models import Role
from apps.core.rbac.permissions import get_user_role, require_project_access
from apps.evidence.attachment_policy import can_edit_attachments
from apps.evidence.services.resolve import is_project_or_month_locked
from apps.projects.models import Project

from .models import FieldReport, FieldReportFile, FieldReportStatus


def _accessible_projects(user):
    role = get_user_role(user)
    if role in (Role.CEO, Role.HQ):
        return Project.objects.all().order_by("name")
    if role == Role.FIELD:
        return Project.objects.filter(
            projectassignment__user=user,
            projectassignment__is_active=True,
        ).order_by("name")
    return Project.objects.none()


def _filter_reports(user, project_id=None):
    qs = FieldReport.objects.select_related("project", "created_by").prefetch_related("files")
    role = get_user_role(user)
    if role == Role.FIELD:
        qs = qs.filter(created_by=user)
    if project_id:
        qs = qs.filter(project_id=project_id)
    return qs.order_by("-updated_at")


def _latest_reject_reason_map(report_ids):
    if not report_ids:
        return {}
    approvals = (
        ApprovalRequest.objects.filter(
            object_type="FIELD_REPORT",
            object_id__in=report_ids,
            status=ApprovalStatus.REJECTED,
        )
        .order_by("object_id", "-updated_at")
        .values("object_id", "reject_reason")
    )
    result = {}
    for row in approvals:
        object_id = row["object_id"]
        if object_id not in result:
            result[object_id] = (row.get("reject_reason") or "").strip()
    return result


def _ensure_can_edit(report, user):
    role = get_user_role(user)
    if role == Role.FIELD and report.created_by_id != user.id:
        raise PermissionDenied("Report edit not allowed.")
    if report.status not in (FieldReportStatus.DRAFT, FieldReportStatus.REJECTED):
        raise PermissionDenied("Report is locked after submission.")


def _sync_report_approval_for_submit(report, user):
    ApprovalRequest.objects.update_or_create(
        object_type="FIELD_REPORT",
        object_id=report.id,
        defaults={
            "status": ApprovalStatus.SUBMITTED,
            "submitted_by": user,
            "submitted_at": timezone.now(),
            "approved_by": None,
            "approved_at": None,
            "reject_reason": "",
        },
    )


@login_required
def report_list(request):
    project_id = request.GET.get("project_id")
    if project_id:
        require_project_access(request.user, project_id)
    projects = _accessible_projects(request.user)
    reports = list(_filter_reports(request.user, project_id))
    reject_reason_map = _latest_reject_reason_map([report.id for report in reports])
    for report in reports:
        report.reject_reason = reject_reason_map.get(report.id, "")

    return render(
        request,
        "app/report_list.html",
        {
            "projects": projects,
            "project_id": str(project_id) if project_id else "",
            "reports": reports,
            "role": get_user_role(request.user),
        },
    )


@login_required
def report_create(request):
    project_id = request.GET.get("project_id") or request.POST.get("project_id")
    if not project_id:
        messages.error(request, "프로젝트를 선택해 주세요.")
        return redirect("/app/reports/")

    require_project_access(request.user, project_id)
    project = get_object_or_404(Project, id=project_id)

    if request.method == "POST":
        action = request.POST.get("action", "draft")
        title = (request.POST.get("title") or "").strip()
        content = (request.POST.get("content") or "").strip()
        report_date = request.POST.get("report_date") or date.today().isoformat()
        files = request.FILES.getlist("files")

        try:
            report_date_obj = date.fromisoformat(report_date)
        except ValueError:
            messages.error(request, "작성일 형식이 올바르지 않습니다.")
            return redirect(f"/app/reports/new/?project_id={project.id}")

        if not title:
            messages.error(request, "제목을 입력해 주세요.")
            return redirect(f"/app/reports/new/?project_id={project.id}")

        try:
            guard_write(
                project=project,
                target_date=report_date_obj,
                message_context="보고서 작성",
                exc=PermissionDenied,
            )
        except PermissionDenied as exc:
            messages.error(request, str(exc))
            return redirect(f"/app/reports/new/?project_id={project.id}")

        status = FieldReportStatus.DRAFT
        submitted_at = None
        if action == "submit":
            status = FieldReportStatus.SUBMITTED
            submitted_at = timezone.now()

        report = FieldReport.objects.create(
            project=project,
            report_date=report_date_obj,
            title=title,
            content=content,
            status=status,
            created_by=request.user,
            submitted_at=submitted_at,
        )

        for file_obj in files:
            FieldReportFile.objects.create(
                report=report,
                file=file_obj,
                original_name=file_obj.name,
                uploaded_by=request.user,
            )

        if report.status == FieldReportStatus.SUBMITTED:
            _sync_report_approval_for_submit(report, request.user)
            messages.success(request, "보고서가 제출되었습니다.")
        else:
            messages.success(request, "보고서가 임시저장되었습니다.")

        return redirect("/app/reports/")

    return render(
        request,
        "app/report_form.html",
        {"project": project, "report": None, "now": timezone.localdate()},
    )


@login_required
def report_edit(request, report_id):
    report = get_object_or_404(FieldReport, id=report_id)
    require_project_access(request.user, report.project_id)
    _ensure_can_edit(report, request.user)

    is_closed_locked = is_project_or_month_locked(
        project=report.project,
        target_date=report.report_date,
    )
    can_edit = can_edit_attachments(status=report.status, is_closed_locked=is_closed_locked)

    try:
        guard_write(
            project=report.project,
            target_date=report.report_date,
            message_context="보고서 작성",
            exc=PermissionDenied,
        )
    except PermissionDenied as exc:
        messages.error(request, str(exc))
        return redirect("/app/reports/")

    if request.method == "POST":
        action = request.POST.get("action", "draft")

        if action == "attachment_upload":
            if not can_edit:
                messages.error(request, "제출/승인/마감 상태에서는 첨부를 수정할 수 없습니다.")
                return redirect(f"/app/reports/{report.id}/edit/")
            upload_files = request.FILES.getlist("files")
            if not upload_files:
                messages.error(request, "파일을 선택해 주세요.")
                return redirect(f"/app/reports/{report.id}/edit/")
            for upload_file in upload_files:
                FieldReportFile.objects.create(
                    report=report,
                    file=upload_file,
                    original_name=upload_file.name,
                    uploaded_by=request.user,
                )
            messages.success(request, "첨부 파일이 업로드되었습니다.")
            return redirect(f"/app/reports/{report.id}/edit/")

        if action == "attachment_delete":
            if not can_edit:
                messages.error(request, "제출/승인/마감 상태에서는 첨부를 수정할 수 없습니다.")
                return redirect(f"/app/reports/{report.id}/edit/")
            file_id = request.POST.get("file_id")
            report_file = report.files.filter(id=file_id).first()
            if report_file is None:
                messages.error(request, "삭제할 첨부 파일을 찾을 수 없습니다.")
                return redirect(f"/app/reports/{report.id}/edit/")
            report_file.delete()
            messages.success(request, "첨부 파일을 삭제했습니다.")
            return redirect(f"/app/reports/{report.id}/edit/")

        title = (request.POST.get("title") or "").strip()
        content = (request.POST.get("content") or "").strip()
        files = request.FILES.getlist("files")

        if not title:
            messages.error(request, "제목을 입력해 주세요.")
            return redirect(f"/app/reports/{report.id}/edit/")

        report.title = title
        report.content = content
        report.status = FieldReportStatus.DRAFT
        report.submitted_at = None
        if action == "submit":
            report.status = FieldReportStatus.SUBMITTED
            report.submitted_at = timezone.now()
        report.save(update_fields=["title", "content", "status", "submitted_at", "updated_at"])

        for file_obj in files:
            FieldReportFile.objects.create(
                report=report,
                file=file_obj,
                original_name=file_obj.name,
                uploaded_by=request.user,
            )

        if report.status == FieldReportStatus.SUBMITTED:
            _sync_report_approval_for_submit(report, request.user)
            messages.success(request, "보고서가 제출되었습니다.")
        else:
            messages.success(request, "보고서가 임시저장되었습니다.")
        return redirect("/app/reports/")

    report_files = list(report.files.all().order_by("-uploaded_at"))
    return render(
        request,
        "app/report_form.html",
        {
            "project": report.project,
            "report": report,
            "now": timezone.localdate(),
            "report_existing_files": report_files,
            "report_can_edit_attachments": can_edit,
            "report_attachment_upload_url": f"/app/reports/{report.id}/edit/" if can_edit else None,
            "report_attachment_delete_url": f"/app/reports/{report.id}/edit/" if can_edit else None,
            "report_attachment_help_text": (
                "임시저장/반려 상태에서는 제출 전까지 첨부를 수정할 수 있습니다."
                if can_edit
                else "제출/승인/마감 상태에서는 첨부를 수정할 수 없습니다."
            ),
        },
    )


@login_required
def report_submit(request, report_id):
    report = get_object_or_404(FieldReport, id=report_id)
    require_project_access(request.user, report.project_id)
    _ensure_can_edit(report, request.user)

    try:
        guard_write(
            project=report.project,
            target_date=report.report_date,
            message_context="보고서 제출",
            exc=PermissionDenied,
        )
    except PermissionDenied as exc:
        messages.error(request, str(exc))
        return redirect("/app/reports/")

    report.status = FieldReportStatus.SUBMITTED
    report.submitted_at = timezone.now()
    report.save(update_fields=["status", "submitted_at", "updated_at"])

    _sync_report_approval_for_submit(report, request.user)
    messages.success(request, "보고서가 제출되었습니다.")
    return redirect("/app/reports/")


@login_required
def report_detail(request, report_id):
    report = get_object_or_404(FieldReport, id=report_id)
    require_project_access(request.user, report.project_id)

    role = get_user_role(request.user)
    if role == Role.FIELD and report.created_by_id != request.user.id:
        raise PermissionDenied("Report access not allowed.")

    is_closed_locked = is_project_or_month_locked(
        project=report.project,
        target_date=report.report_date,
    )
    can_edit = (
        role == Role.FIELD
        and report.created_by_id == request.user.id
        and can_edit_attachments(status=report.status, is_closed_locked=is_closed_locked)
    )

    if request.method == "POST":
        action = request.POST.get("action", "")
        if action == "attachment_upload":
            if not can_edit:
                messages.error(request, "제출/승인/마감 상태에서는 첨부를 수정할 수 없습니다.")
                return redirect(f"/app/reports/{report.id}/")
            upload_files = request.FILES.getlist("files")
            if not upload_files:
                messages.error(request, "파일을 선택해 주세요.")
                return redirect(f"/app/reports/{report.id}/")
            for upload_file in upload_files:
                FieldReportFile.objects.create(
                    report=report,
                    file=upload_file,
                    original_name=upload_file.name,
                    uploaded_by=request.user,
                )
            messages.success(request, "첨부 파일이 업로드되었습니다.")
            return redirect(f"/app/reports/{report.id}/")

        if action == "attachment_delete":
            if not can_edit:
                messages.error(request, "제출/승인/마감 상태에서는 첨부를 수정할 수 없습니다.")
                return redirect(f"/app/reports/{report.id}/")
            file_id = request.POST.get("file_id")
            report_file = report.files.filter(id=file_id).first()
            if report_file is None:
                messages.error(request, "삭제할 첨부 파일을 찾을 수 없습니다.")
                return redirect(f"/app/reports/{report.id}/")
            report_file.delete()
            messages.success(request, "첨부 파일을 삭제했습니다.")
            return redirect(f"/app/reports/{report.id}/")

    report_files = list(report.files.all().order_by("-uploaded_at"))
    approved_back_url = None
    approved_type = request.GET.get("approved_type")
    approved_from = request.GET.get("approved_from")
    approved_to = request.GET.get("approved_to")
    approved_project_id = request.GET.get("approved_project_id")
    from_approved = (request.GET.get("from_approved") or "").strip()
    if from_approved:
        raw = from_approved[1:] if from_approved.startswith("?") else from_approved
        parsed = QueryDict(raw)
        approved_type = approved_type or parsed.get("type") or parsed.get("approved_type")
        approved_from = approved_from or parsed.get("from") or parsed.get("approved_from")
        approved_to = approved_to or parsed.get("to") or parsed.get("approved_to")
        approved_project_id = approved_project_id or parsed.get("project_id") or parsed.get("approved_project_id")
    if not approved_type and request.GET.get("type"):
        approved_type = request.GET.get("type")
    if not approved_from and request.GET.get("from"):
        approved_from = request.GET.get("from")
    if not approved_to and request.GET.get("to"):
        approved_to = request.GET.get("to")
    if not approved_project_id and request.GET.get("project_id"):
        approved_project_id = request.GET.get("project_id")

    if approved_type or approved_from or approved_to or approved_project_id:
        approved_back_url = "/app/field/approved/?" + urlencode(
            {
                "type": approved_type or "report",
                "from": approved_from or "",
                "to": approved_to or "",
                "project_id": approved_project_id or report.project_id,
            }
        )

    context = {
        "report": report,
        "report_existing_files": report_files,
        "report_can_edit_attachments": can_edit,
        "report_attachment_upload_url": f"/app/reports/{report.id}/" if can_edit else None,
        "report_attachment_delete_url": f"/app/reports/{report.id}/" if can_edit else None,
        "report_approved_back_url": approved_back_url,
        "report_attachment_help_text": (
            "임시저장/반려 상태에서는 제출 전까지 첨부를 수정할 수 있습니다."
            if can_edit
            else "제출/승인/마감 상태에서는 첨부를 수정할 수 없습니다."
        ),
    }
    return render(request, "app/report_detail.html", context)



