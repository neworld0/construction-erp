from __future__ import annotations

from datetime import timedelta

from django.contrib import messages
from django.contrib.auth.decorators import login_required
from django.core.exceptions import PermissionDenied
from django.shortcuts import redirect, render
from django.utils import timezone

from apps.core.rbac.models import Role
from apps.core.rbac.permissions import get_user_role
from apps.cost.models import CostActual
from apps.schedule.models import DailyProgress

from .web_views import (
    _get_accessible_projects,
    _handle_progress_submit,
    _load_progress_context,
    _resolve_project,
)

_MOBILE_KEYWORDS = (
    "android",
    "iphone",
    "ipad",
    "ipod",
    "mobile",
    "windows phone",
    "webos",
)


def _ensure_mobile_field(request):
    role = get_user_role(request.user)
    if role != Role.FIELD:
        raise PermissionDenied("FIELD 전용 화면입니다.")

    user_agent = (request.META.get("HTTP_USER_AGENT") or "").lower()
    if request.GET.get("force_mobile") != "1" and not any(
        keyword in user_agent for keyword in _MOBILE_KEYWORDS
    ):
        raise PermissionDenied("모바일 전용 화면입니다.")


def _resolve_mobile_project(request):
    projects = _get_accessible_projects(request.user)
    project = None

    project_id = request.GET.get("project_id") or request.POST.get("project_id")
    if project_id:
        try:
            project = _resolve_project(request.user, project_id)
        except PermissionDenied:
            project = None

    if project is None:
        last_project_id = request.session.get("field_mobile_last_project_id")
        if last_project_id:
            try:
                project = _resolve_project(request.user, last_project_id)
            except PermissionDenied:
                project = None

    if project is None:
        project = projects.first()

    if project is not None:
        request.session["field_mobile_last_project_id"] = project.id

    return projects, project


def _status_today_progress(project, user, today):
    qs = DailyProgress.objects.filter(project=project, reporter=user, report_date=today)
    if qs.filter(status__in=["submitted", "approved"]).exists():
        return "제출"
    if qs.filter(status="draft").exists():
        return "임시저장"
    return "미제출"


def _status_today_cost(project, user, today):
    qs = CostActual.objects.filter(
        project=project,
        source_daily_report__reporter=user,
        report_date=today,
    )
    if qs.filter(status__in=["submitted", "approved"]).exists():
        return "제출"
    if qs.filter(status="draft").exists():
        return "임시저장"
    return "미입력"


def _project_qs(project):
    return f"?project_id={project.id}" if project else ""


@login_required
def field_mobile_home(request):
    _ensure_mobile_field(request)
    projects, project = _resolve_mobile_project(request)

    today = timezone.localdate()
    if project is None:
        return render(
            request,
            "app/field/mobile/home.html",
            {
                "projects": projects,
                "project": None,
                "today": today,
                "progress_status": "미제출",
                "daily_report_status": "자동 취합",
                "cost_status": "미입력",
            },
        )

    context = {
        "projects": projects,
        "project": project,
        "today": today,
        "progress_status": _status_today_progress(project, request.user, today),
        "daily_report_status": "자동 취합",
        "cost_status": _status_today_cost(project, request.user, today),
    }
    return render(request, "app/field/mobile/home.html", context)


@login_required
def field_mobile_progress(request):
    _ensure_mobile_field(request)
    projects, project = _resolve_mobile_project(request)
    if project is None:
        messages.warning(request, "프로젝트를 먼저 선택해 주세요.")
        return redirect("/app/field/mobile/")

    context = {
        "tab": "progress",
        "projects": projects,
        "project": project,
        "errors": [],
        "success": "",
        "now": timezone.localdate().isoformat(),
        "progress_min_date": (timezone.localdate() - timedelta(days=1)).isoformat(),
        "progress_max_date": timezone.localdate().isoformat(),
    }

    if request.method == "POST":
        _handle_progress_submit(request, project, context)
        if context.get("success"):
            messages.success(request, context["success"])
            return redirect(f"/app/field/mobile/progress/?project_id={project.id}")

    _load_progress_context(project, request.user, request, context)
    return render(request, "app/field/mobile/progress.html", context)


@login_required
def field_mobile_reports(request):
    _ensure_mobile_field(request)
    _projects, project = _resolve_mobile_project(request)
    project_qs = _project_qs(project)
    return redirect(f"/app/field/site-daily-logs/{project_qs}")


@login_required
def field_mobile_costs(request):
    _ensure_mobile_field(request)
    _projects, project = _resolve_mobile_project(request)
    project_qs = f"&project_id={project.id}" if project else ""
    return render(
        request,
        "app/field/mobile/link_hub.html",
        {
            "title": "모바일 원가 입력",
            "subtitle": "기존 검증 로직을 그대로 사용해 원가를 입력합니다.",
            "primary_label": "원가 입력 열기",
            "primary_url": f"/app/field/?tab=cost{project_qs}",
            "secondary_label": "원가 목록 보기",
            "secondary_url": f"/app/field/?tab=cost{project_qs}",
        },
    )


@login_required
def field_mobile_inventory_issue(request):
    _ensure_mobile_field(request)
    _projects, project = _resolve_mobile_project(request)
    project_qs = _project_qs(project)
    return redirect(f"/app/field/inventory/issues/{project_qs}")


@login_required
def field_mobile_timesheet(request):
    _ensure_mobile_field(request)
    _projects, project = _resolve_mobile_project(request)
    project_qs = _project_qs(project)
    return redirect(f"/app/field/labor/timesheets/new/{project_qs}")
