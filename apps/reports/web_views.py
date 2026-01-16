from datetime import date

from django.contrib import messages
from django.contrib.auth.decorators import login_required
from django.core.exceptions import PermissionDenied
from django.shortcuts import get_object_or_404, redirect, render
from django.utils import timezone

from apps.core.rbac.models import Role
from apps.core.rbac.permissions import get_user_role, require_project_access
from apps.projects.models import Project

from .models import FieldReport, FieldReportFile, FieldReportStatus


def _accessible_projects(user):
    role = get_user_role(user)
    if role in (Role.CEO, Role.HQ):
        return Project.objects.all().order_by("name")
    if role == Role.FIELD:
        return Project.objects.filter(
            projectassignment__user=user, projectassignment__is_active=True
        ).order_by("name")
    return Project.objects.none()


def _filter_reports(user, project_id=None):
    qs = FieldReport.objects.select_related("project", "created_by").prefetch_related(
        "files"
    )
    role = get_user_role(user)
    if role == Role.FIELD:
        qs = qs.filter(created_by=user)
    if project_id:
        qs = qs.filter(project_id=project_id)
    return qs.order_by("-updated_at")


def _ensure_can_edit(report, user):
    role = get_user_role(user)
    if role == Role.FIELD and report.created_by_id != user.id:
        raise PermissionDenied("Report edit not allowed.")
    if report.status != FieldReportStatus.DRAFT:
        raise PermissionDenied("Report is locked after submission.")


@login_required
def report_list(request):
    project_id = request.GET.get("project_id")
    if project_id:
        require_project_access(request.user, project_id)
    projects = _accessible_projects(request.user)
    reports = _filter_reports(request.user, project_id)
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
        messages.error(request, "프로젝트를 선택하세요.")
        return redirect("/app/reports/")
    require_project_access(request.user, project_id)
    project = get_object_or_404(Project, id=project_id)

    if request.method == "POST":
        action = request.POST.get("action", "draft")
        title = (request.POST.get("title") or "").strip()
        content = (request.POST.get("content") or "").strip()
        report_date = request.POST.get("report_date") or date.today().isoformat()
        files = request.FILES.getlist("files")

        if not title:
            messages.error(request, "제목을 입력하세요.")
            return redirect(f"/app/reports/new/?project_id={project.id}")

        status = FieldReportStatus.DRAFT
        submitted_at = None
        if action == "submit":
            status = FieldReportStatus.SUBMITTED
            submitted_at = timezone.now()

        report = FieldReport.objects.create(
            project=project,
            report_date=report_date,
            title=title,
            content=content,
            status=status,
            created_by=request.user,
            submitted_at=submitted_at,
        )
        for file_obj in files:
            FieldReportFile.objects.create(
                report=report, file=file_obj, uploaded_by=request.user
            )
        messages.success(request, "보고서가 저장되었습니다.")
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

    if request.method == "POST":
        action = request.POST.get("action", "draft")
        title = (request.POST.get("title") or "").strip()
        content = (request.POST.get("content") or "").strip()
        files = request.FILES.getlist("files")

        if not title:
            messages.error(request, "제목을 입력하세요.")
            return redirect(f"/app/reports/{report.id}/edit/")

        report.title = title
        report.content = content
        report.status = FieldReportStatus.DRAFT
        report.submitted_at = None
        if action == "submit":
            report.status = FieldReportStatus.SUBMITTED
            report.submitted_at = timezone.now()
        report.save(
            update_fields=["title", "content", "status", "submitted_at", "updated_at"]
        )

        for file_obj in files:
            FieldReportFile.objects.create(
                report=report, file=file_obj, uploaded_by=request.user
            )
        if report.status == FieldReportStatus.SUBMITTED:
            messages.success(request, "보고서가 제출되었습니다.")
        else:
            messages.success(request, "보고서가 수정되었습니다.")
        return redirect("/app/reports/")

    return render(
        request,
        "app/report_form.html",
        {"project": report.project, "report": report, "now": timezone.localdate()},
    )


@login_required
def report_submit(request, report_id):
    report = get_object_or_404(FieldReport, id=report_id)
    require_project_access(request.user, report.project_id)
    _ensure_can_edit(report, request.user)

    report.status = FieldReportStatus.SUBMITTED
    report.submitted_at = timezone.now()
    report.save(update_fields=["status", "submitted_at", "updated_at"])
    messages.success(request, "보고서가 제출되었습니다.")
    return redirect("/app/reports/")


@login_required
def report_detail(request, report_id):
    report = get_object_or_404(FieldReport, id=report_id)
    require_project_access(request.user, report.project_id)
    role = get_user_role(request.user)
    if role == Role.FIELD and report.created_by_id != request.user.id:
        raise PermissionDenied("Report access not allowed.")
    return render(request, "app/report_detail.html", {"report": report})
