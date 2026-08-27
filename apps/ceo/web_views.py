from datetime import date

from django.contrib.auth.decorators import login_required
from django.shortcuts import redirect, render

from apps.core.rbac.models import Role
from apps.core.rbac.permissions import require_role
from apps.projects.models import Project
from .services.dashboard import get_ceo_project_summary, get_ceo_projects_list
from .services.progress_comparison import build_project_progress_timeline
from apps.projects.services.wbs_baseline import (
    get_wbs_baseline_badge,
    get_wbs_baseline_history,
)


def _parse_date(value):
    if not value:
        return None
    try:
        return date.fromisoformat(value)
    except ValueError:
        return None


@login_required
def dashboard_page(request):
    require_role(request.user, [Role.CEO, Role.HQ])
    return redirect("/app/ceo/")


@login_required
def project_detail_page(request, project_id):
    require_role(request.user, [Role.CEO, Role.HQ])
    as_of_date = _parse_date(request.GET.get("as_of_date"))
    summary = get_ceo_project_summary(project_id, as_of_date)
    project = Project.objects.filter(id=project_id).first()
    wbs_badge = get_wbs_baseline_badge(project) if project else {}
    wbs_history = get_wbs_baseline_history(project) if project else []
    progress_timeline = build_project_progress_timeline(project, as_of_date or date.today()) if project else {}

    context = {
        "summary": summary,
        "as_of_date": as_of_date,
        "project": project,
        "wbs_badge": wbs_badge,
        "wbs_history": wbs_history,
        "progress_timeline": progress_timeline,
    }
    return render(request, "ceo/project_detail.html", context)
