from rest_framework.response import Response
from rest_framework.views import APIView

from django.shortcuts import get_object_or_404

from apps.core.rbac.models import Role
from apps.core.rbac.permissions import require_role
from apps.projects.models import Project
from apps.projects.services.wbs_baseline import (
    get_wbs_baseline_badge,
    get_wbs_baseline_history,
)


class ProjectWBSBaselineBadgeView(APIView):
    def get(self, request, project_id):
        require_role(request.user, [Role.CEO, Role.HQ], request=request)
        project = get_object_or_404(Project, id=project_id)
        return Response(get_wbs_baseline_badge(project))


class ProjectWBSBaselineHistoryView(APIView):
    def get(self, request, project_id):
        require_role(request.user, [Role.CEO, Role.HQ], request=request)
        project = get_object_or_404(Project, id=project_id)
        try:
            limit = int(request.GET.get("limit", "20"))
        except (TypeError, ValueError):
            limit = 20
        limit = max(1, min(50, limit))
        return Response(get_wbs_baseline_history(project, limit=limit))
