from datetime import date

from django.contrib import messages
from django.core.exceptions import PermissionDenied, ValidationError
from django.db import transaction
from django.shortcuts import get_object_or_404, redirect, render
from django.utils import timezone
from django.views.decorators.http import require_POST

from apps.closing.guards import guard_write
from apps.core.rbac.models import Role
from apps.core.rbac.permissions import (
    get_current_legal_entity,
    get_user_legal_entities,
    get_user_role,
    require_legal_entity_access,
    require_project_access,
    require_role,
)
from apps.projects.models import Project

from .models import SiteDailyLog, SiteDailyLogStatus
from .site_daily_log_forms import SiteDailyLogForm, SiteDailyLogWorkLineFormSet
from .site_daily_log_services import decide_site_daily_log, submit_site_daily_log


def _field_projects(user):
    return Project.objects.filter(
        legal_entity__in=get_user_legal_entities(user),
        projectassignment__user=user,
        projectassignment__is_active=True,
        is_active=True,
    ).distinct().order_by("name")


def _current_entity_projects(request):
    entity = get_current_legal_entity(request)
    projects = _field_projects(request.user)
    return projects.filter(legal_entity=entity) if entity else projects.none()


def field_site_daily_log_list(request):
    require_role(request.user, [Role.FIELD], request=request)
    projects = _current_entity_projects(request)
    logs = SiteDailyLog.objects.filter(project__in=projects, reporter=request.user).select_related("project")
    return render(
        request,
        "app/field/site_daily_log_list.html",
        {"logs": logs, "projects": projects, "role": get_user_role(request.user), "active_tab": "site_daily_log"},
    )


def field_site_daily_log_new(request):
    require_role(request.user, [Role.FIELD], request=request)
    projects = _current_entity_projects(request)
    initial = {"report_date": timezone.localdate()}
    requested_project = request.GET.get("project_id")
    if str(requested_project).isdigit() and projects.filter(id=requested_project).exists():
        initial["project"] = requested_project
    form = SiteDailyLogForm(initial=initial, projects=projects)
    return render(
        request,
        "app/field/site_daily_log_form.html",
        {"form": form, "work_formset": None, "is_new": True, "role": get_user_role(request.user), "active_tab": "site_daily_log"},
    )


@require_POST
def field_site_daily_log_create(request):
    require_role(request.user, [Role.FIELD], request=request)
    projects = _current_entity_projects(request)
    form = SiteDailyLogForm(request.POST, projects=projects)
    if not form.is_valid():
        return _render_log_form(request, form=form)
    project = form.cleaned_data["project"]
    try:
        require_project_access(request.user, project.id)
        guard_write(
            project=project,
            target_date=form.cleaned_data["report_date"],
            message_context="공사일보 저장은 불가능합니다.",
        )
        log = form.save(commit=False)
        log.reporter = request.user
        log.save()
        messages.success(request, "공사일보를 생성했습니다. WBS 물량실적을 입력해 주세요.")
        return redirect(f"/app/field/site-daily-logs/{log.id}/")
    except (PermissionDenied, ValidationError) as exc:
        messages.error(request, str(exc))
        return _render_log_form(request, form=form)


def _render_log_form(request, *, log=None, form=None, work_formset=None):
    projects = _current_entity_projects(request)
    if form is None:
        form = SiteDailyLogForm(instance=log, projects=projects)
    if work_formset is None and log is not None:
        work_formset = SiteDailyLogWorkLineFormSet(instance=log, form_kwargs={"project": log.project})
    return render(
        request,
        "app/field/site_daily_log_form.html",
        {
            "form": form,
            "work_formset": work_formset,
            "log": log,
            "is_new": log is None,
            "can_edit": log is None or log.status in (SiteDailyLogStatus.DRAFT, SiteDailyLogStatus.REJECTED),
            "role": get_user_role(request.user),
            "active_tab": "site_daily_log",
        },
    )


def field_site_daily_log_detail(request, log_id):
    require_role(request.user, [Role.FIELD], request=request)
    log = get_object_or_404(SiteDailyLog.objects.select_related("project"), id=log_id, reporter=request.user)
    require_project_access(request.user, log.project_id)
    if request.method != "POST":
        return _render_log_form(request, log=log)
    if log.status not in (SiteDailyLogStatus.DRAFT, SiteDailyLogStatus.REJECTED):
        messages.error(request, "제출 또는 승인된 공사일보는 수정할 수 없습니다.")
        return redirect(f"/app/field/site-daily-logs/{log.id}/")
    form = SiteDailyLogForm(request.POST, instance=log, projects=_current_entity_projects(request))
    project = log.project
    if form.is_valid():
        project = form.cleaned_data["project"]
    formset = SiteDailyLogWorkLineFormSet(request.POST, instance=log, form_kwargs={"project": project})
    if not (form.is_valid() and formset.is_valid()):
        return _render_log_form(request, log=log, form=form, work_formset=formset)
    try:
        require_project_access(request.user, project.id)
        current_entity = get_current_legal_entity(request)
        if current_entity is None or project.legal_entity_id != current_entity.id:
            raise PermissionDenied("선택한 운영 법인의 프로젝트만 처리할 수 있습니다.")
        guard_write(project=project, target_date=form.cleaned_data["report_date"], message_context="공사일보 저장은 불가능합니다.")
        with transaction.atomic():
            saved = form.save(commit=False)
            saved.project = project
            saved.save()
            formset.instance = saved
            formset.save()
        messages.success(request, "공사일보를 임시저장했습니다.")
        return redirect(f"/app/field/site-daily-logs/{log.id}/")
    except (PermissionDenied, ValidationError) as exc:
        messages.error(request, str(exc))
        return _render_log_form(request, log=log, form=form, work_formset=formset)


@require_POST
def field_site_daily_log_submit(request, log_id):
    require_role(request.user, [Role.FIELD], request=request)
    try:
        log = submit_site_daily_log(log_id=log_id, actor=request.user, request=request)
        messages.success(request, "공사일보를 제출했습니다.")
        return redirect(f"/app/field/site-daily-logs/{log.id}/")
    except (SiteDailyLog.DoesNotExist, PermissionDenied, ValidationError) as exc:
        messages.error(request, str(exc))
        return redirect(f"/app/field/site-daily-logs/{log_id}/")


def hq_site_daily_log_list(request):
    require_role(request.user, [Role.HQ, Role.CEO], request=request)
    entities = get_user_legal_entities(request.user)
    requested_entity = request.GET.get("legal_entity_id")
    entity = entities.filter(id=requested_entity).first() if str(requested_entity).isdigit() else get_current_legal_entity(request)
    logs = SiteDailyLog.objects.select_related("project", "reporter", "approved_by", "rejected_by")
    if entity:
        logs = logs.filter(project__legal_entity=entity)
    return render(
        request,
        "app/hq/site_daily_log_list.html",
        {"logs": logs, "legal_entities": entities, "selected_entity": entity, "role": get_user_role(request.user)},
    )


@require_POST
def hq_site_daily_log_decide(request, log_id):
    require_role(request.user, [Role.HQ, Role.CEO], request=request)
    approve = request.POST.get("decision") == "approve"
    try:
        log = decide_site_daily_log(
            log_id=log_id,
            actor=request.user,
            approve=approve,
            reason=request.POST.get("reason", ""),
            request=request,
        )
        messages.success(request, "공사일보를 승인했습니다." if approve else "공사일보를 반려했습니다.")
    except (SiteDailyLog.DoesNotExist, PermissionDenied, ValidationError) as exc:
        messages.error(request, str(exc))
    return redirect("/app/hq/site-daily-logs/")
