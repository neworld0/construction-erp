from datetime import date

from django.contrib.auth.decorators import login_required
from django.core.exceptions import PermissionDenied
from django.http import FileResponse
from django.shortcuts import get_object_or_404, render
from django.utils import timezone

from apps.core.rbac.models import Role
from apps.core.rbac.permissions import (
    get_current_legal_entity,
    get_user_legal_entities,
    get_user_role,
    require_project_access,
    require_role,
)
from apps.projects.models import Project

from .daily_report_service import build_organization_daily_report, build_project_daily_report
from .daily_report_exports import organization_daily_report_pdf, project_daily_report_pdf


def _as_of_date(request):
    raw = request.GET.get("as_of_date")
    try:
        return date.fromisoformat(raw) if raw else timezone.localdate()
    except ValueError:
        return timezone.localdate()


def _pdf_response(stream, filename):
    return FileResponse(stream, as_attachment=True, filename=filename, content_type="application/pdf")


def _field_projects(user, entity=None):
    projects = Project.objects.filter(
        projectassignment__user=user,
        projectassignment__is_active=True,
        is_active=True,
        legal_entity__in=get_user_legal_entities(user),
    ).distinct()
    return projects.filter(legal_entity=entity) if entity else projects


@login_required
def field_project_daily_report_list(request):
    require_role(request.user, [Role.FIELD], request=request)
    entity = get_current_legal_entity(request)
    projects = _field_projects(request.user, entity).order_by("name")
    as_of_date = _as_of_date(request)
    return render(request, "app/field/project_daily_report_list.html", {
        "projects": projects,
        "as_of_date": as_of_date,
        "active_tab": "site_daily_log",
        "role": get_user_role(request.user),
    })


@login_required
def field_project_daily_report_detail(request, project_id):
    require_role(request.user, [Role.FIELD], request=request)
    project = get_object_or_404(Project, id=project_id, is_active=True)
    require_project_access(request.user, project.id)
    if not _field_projects(request.user).filter(id=project.id).exists():
        raise PermissionDenied("배정된 프로젝트의 공사일보만 볼 수 있습니다.")
    as_of_date = _as_of_date(request)
    return render(request, "app/field/project_daily_report_detail.html", {
        "report": build_project_daily_report(project=project, as_of_date=as_of_date),
        "as_of_date": as_of_date,
        "active_tab": "site_daily_log",
        "project_id": project.id,
        "role": get_user_role(request.user),
    })


@login_required
def field_project_daily_report_pdf(request, project_id):
    require_role(request.user, [Role.FIELD], request=request)
    project = get_object_or_404(Project.objects.select_related("legal_entity"), id=project_id, is_active=True)
    require_project_access(request.user, project.id)
    if not _field_projects(request.user).filter(id=project.id).exists():
        raise PermissionDenied("배정된 프로젝트의 공사일보만 내려받을 수 있습니다.")
    as_of_date = _as_of_date(request)
    return _pdf_response(
        project_daily_report_pdf(build_project_daily_report(project=project, as_of_date=as_of_date)),
        f"공사일보_{project.code}_{as_of_date:%Y%m%d}.pdf",
    )


def _organization_scope(request, *, allow_group):
    accessible = get_user_legal_entities(request.user)
    entity_id = request.GET.get("legal_entity_id")
    requested_scope = (request.GET.get("scope") or "").upper()
    requested_group = allow_group and requested_scope == "GROUP"
    if requested_group:
        codes = set(accessible.values_list("code", flat=True))
        if {"ASAN", "MISAN"}.issubset(codes):
            return accessible.filter(code__in=["ASAN", "MISAN"]), "아미산(그룹합산)", "GROUP"
        raise PermissionDenied("아미산 그룹합산을 조회할 권한이 없습니다.")
    entity = None
    if str(entity_id).isdigit():
        entity = accessible.filter(id=entity_id).first()
    elif requested_scope:
        entity = accessible.filter(code=requested_scope).first()
    if entity is None:
        entity = get_current_legal_entity(request)
    if entity is None or not accessible.filter(id=entity.id).exists():
        raise PermissionDenied("조회 가능한 운영 법인이 없습니다.")
    return accessible.filter(id=entity.id), entity.legal_name, entity.code


@login_required
def hq_organization_daily_report(request):
    require_role(request.user, [Role.HQ, Role.CEO], request=request)
    entities, scope_label, scope_code = _organization_scope(request, allow_group=True)
    project_id = request.GET.get("project_id")
    projects = Project.objects.filter(legal_entity__in=entities, is_active=True).select_related("legal_entity").order_by("legal_entity__code", "name")
    if str(project_id).isdigit():
        projects = projects.filter(id=project_id)
    as_of_date = _as_of_date(request)
    return render(request, "app/hq/organization_daily_report.html", {
        "organization_report": build_organization_daily_report(projects=projects, as_of_date=as_of_date),
        "as_of_date": as_of_date,
        "legal_entities": get_user_legal_entities(request.user),
        "selected_scope": scope_code,
        "scope_label": scope_label,
        "selected_project_id": project_id,
        "role": get_user_role(request.user),
    })


@login_required
def hq_organization_daily_report_pdf(request):
    require_role(request.user, [Role.HQ, Role.CEO], request=request)
    entities, scope_label, _ = _organization_scope(request, allow_group=True)
    project_id = request.GET.get("project_id")
    projects = Project.objects.filter(legal_entity__in=entities, is_active=True).select_related("legal_entity").order_by("legal_entity__code", "name")
    if str(project_id).isdigit():
        projects = projects.filter(id=project_id)
    as_of_date = _as_of_date(request)
    return _pdf_response(
        organization_daily_report_pdf(build_organization_daily_report(projects=projects, as_of_date=as_of_date), scope_label),
        f"공사일보_{scope_label}_{as_of_date:%Y%m%d}.pdf",
    )


@login_required
def hq_project_daily_report_detail(request, project_id):
    """HQ read-only detail for one project's source-backed daily report."""
    require_role(request.user, [Role.HQ, Role.CEO], request=request)
    project = get_object_or_404(Project.objects.select_related("legal_entity"), id=project_id, is_active=True)
    require_project_access(request.user, project.id)
    as_of_date = _as_of_date(request)
    return render(request, "app/hq/project_daily_report_detail.html", {
        "report": build_project_daily_report(project=project, as_of_date=as_of_date),
        "as_of_date": as_of_date,
        "role": get_user_role(request.user),
    })


@login_required
def hq_project_daily_report_pdf(request, project_id):
    require_role(request.user, [Role.HQ, Role.CEO], request=request)
    project = get_object_or_404(Project.objects.select_related("legal_entity"), id=project_id, is_active=True)
    require_project_access(request.user, project.id)
    as_of_date = _as_of_date(request)
    return _pdf_response(
        project_daily_report_pdf(build_project_daily_report(project=project, as_of_date=as_of_date)),
        f"공사일보_{project.code}_{as_of_date:%Y%m%d}.pdf",
    )


@login_required
def ceo_organization_daily_report(request):
    require_role(request.user, [Role.CEO, Role.HQ], request=request)
    entities, scope_label, scope_code = _organization_scope(request, allow_group=True)
    projects = Project.objects.filter(legal_entity__in=entities, is_active=True).select_related("legal_entity").order_by("legal_entity__code", "name")
    as_of_date = _as_of_date(request)
    return render(request, "ceo/organization_daily_report.html", {
        "organization_report": build_organization_daily_report(projects=projects, as_of_date=as_of_date),
        "as_of_date": as_of_date,
        "legal_entities": get_user_legal_entities(request.user),
        "selected_scope": scope_code,
        "scope_label": scope_label,
        "ceo_read_only": get_user_role(request.user) != Role.CEO,
    })


@login_required
def ceo_organization_daily_report_pdf(request):
    require_role(request.user, [Role.CEO, Role.HQ], request=request)
    entities, scope_label, _ = _organization_scope(request, allow_group=True)
    projects = Project.objects.filter(legal_entity__in=entities, is_active=True).select_related("legal_entity").order_by("legal_entity__code", "name")
    as_of_date = _as_of_date(request)
    return _pdf_response(
        organization_daily_report_pdf(build_organization_daily_report(projects=projects, as_of_date=as_of_date), scope_label),
        f"공사일보_{scope_label}_{as_of_date:%Y%m%d}.pdf",
    )
