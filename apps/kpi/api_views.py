from django.http import JsonResponse
from django.utils.dateparse import parse_date
from rest_framework.views import APIView
from rest_framework.permissions import IsAuthenticated

from apps.core.rbac.permissions import can_view_project, require_role

from apps.projects.models import Project

from .services import compute_portfolio_kpi, compute_project_kpi
from .timeline import build_timeline


class ProjectKPIView(APIView):
    permission_classes = [IsAuthenticated]

    def get(self, request, project_id):
        require_role(request.user, ["hq", "ceo"], request=request)
        if not can_view_project(request.user, project_id):
            return JsonResponse({"detail": "Project access denied."}, status=403)
        include_submitted = request.GET.get("include_submitted") in ("1", "true", "True")
        as_of_date = parse_date(request.GET.get("as_of_date") or "")
        data = compute_project_kpi(project_id, as_of_date, include_submitted)
        return JsonResponse(data, status=200)


class PortfolioKPIView(APIView):
    permission_classes = [IsAuthenticated]

    def get(self, request):
        require_role(request.user, ["hq", "ceo"], request=request)
        include_submitted = request.GET.get("include_submitted") in ("1", "true", "True")
        as_of_date = parse_date(request.GET.get("as_of_date") or "")
        ids_param = request.GET.get("project_ids")
        project_ids = []
        if ids_param:
            for raw in ids_param.split(","):
                raw = raw.strip()
                if raw.isdigit():
                    project_ids.append(int(raw))
        if not project_ids:
            project_ids = list(Project.objects.values_list("id", flat=True))
        data = compute_portfolio_kpi(project_ids, as_of_date, include_submitted)
        return JsonResponse(data, safe=False, status=200)


class ProjectKPITimelineView(APIView):
    permission_classes = [IsAuthenticated]

    def get(self, request, project_id):
        require_role(request.user, ["hq", "ceo", "field"], request=request)
        if not can_view_project(request.user, project_id):
            return JsonResponse({"detail": "Project access denied."}, status=403)
        project = Project.objects.get(id=project_id)
        granularity = request.GET.get("granularity", "month")
        start_date = parse_date(request.GET.get("start") or "")
        end_date = parse_date(request.GET.get("end") or "")
        metrics = request.GET.get("metrics")
        payload = build_timeline(
            project,
            granularity=granularity,
            start=start_date,
            end=end_date,
            metrics=metrics,
        )
        return JsonResponse(payload, status=200)
