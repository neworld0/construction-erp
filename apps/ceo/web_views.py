from datetime import date

from django.contrib.auth.decorators import login_required
from django.shortcuts import redirect, render

from apps.core.rbac.models import Role
from apps.core.rbac.permissions import require_role
from .services.dashboard import get_ceo_project_summary, get_ceo_projects_list


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

    context = {
        "summary": summary,
        "as_of_date": as_of_date,
    }
    return render(request, "ceo/project_detail.html", context)
