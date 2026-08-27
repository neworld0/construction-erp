from datetime import date
import csv

from django.http import HttpResponse
from rest_framework import status
from rest_framework.permissions import IsAuthenticated
from rest_framework.response import Response
from rest_framework.views import APIView

from apps.audit.constants import REPORT_EXPORT
from apps.audit.services.logger import log_action
from apps.contracts.models import ContractSnapshot
from apps.core.rbac.models import Role
from apps.core.rbac.permissions import require_role
from .permissions import CEOAccessPermission
from .services.dashboard import (
    get_ceo_dashboard,
    get_ceo_project_summary,
    get_ceo_projects_list,
)


class CEODashboardView(APIView):
    permission_classes = [IsAuthenticated, CEOAccessPermission]
    # TODO: RBAC CEO만 허용(T8-SEC-1 연계)

    def get(self, request, *args, **kwargs):
        as_of_date = _parse_date(request.query_params.get("as_of_date"))
        data = get_ceo_dashboard(as_of_date)
        return Response(data, status=status.HTTP_200_OK)


class CEOProjectsView(APIView):
    permission_classes = [IsAuthenticated, CEOAccessPermission]
    # TODO: RBAC CEO만 허용(T8-SEC-1 연계)

    def get(self, request, *args, **kwargs):
        filters = {
            "q": request.query_params.get("q"),
            "sort": request.query_params.get("sort"),
            "status": request.query_params.get("status"),
            "as_of_date": _parse_date(request.query_params.get("as_of_date")),
        }
        data = get_ceo_projects_list(filters)
        return Response(data, status=status.HTTP_200_OK)


class CEOProjectSummaryView(APIView):
    permission_classes = [IsAuthenticated, CEOAccessPermission]
    # TODO: RBAC CEO만 허용(T8-SEC-1 연계)

    def get(self, request, id, *args, **kwargs):
        as_of_date = _parse_date(request.query_params.get("as_of_date"))
        data = get_ceo_project_summary(id, as_of_date)
        return Response(data, status=status.HTTP_200_OK)


class CEOProjectSummaryReportView(APIView):
    permission_classes = [IsAuthenticated, CEOAccessPermission]
    # TODO: RBAC CEO만 허용(T8-SEC-1 연계)

    def get(self, request, *args, **kwargs):
        require_role(request.user, [Role.CEO, Role.HQ])
        as_of_date = _parse_date(request.query_params.get("as_of_date"))
        data = get_ceo_dashboard(as_of_date)
        projects = data.get("projects", [])
        project_ids = [item.get("project_id") for item in projects if item.get("project_id")]
        snapshots = ContractSnapshot.objects.filter(
            project_id__in=project_ids, is_active=True
        ).values("project_id", "version_no")
        snapshot_map = {row["project_id"]: row["version_no"] for row in snapshots}

        response = HttpResponse(content_type="text/csv; charset=utf-8")
        response["Content-Disposition"] = "attachment; filename*=UTF-8''project-summary.csv"
        # Excel on Windows reliably detects Korean UTF-8 CSV only with a BOM.
        response.write("\ufeff")
        writer = csv.writer(response)
        writer.writerow(
            [
                "project_id",
                "project_name",
                "snapshot_version_no",
                "overall_progress_percent",
                "recognized_revenue",
                "accrual_cost",
                "profit",
                "margin_percent",
                "risk_open_count",
                "risk_critical_count",
            ]
        )
        for item in projects:
            project_id = item.get("project_id")
            writer.writerow(
                [
                    project_id,
                    item.get("project_name", ""),
                    snapshot_map.get(project_id, ""),
                    item.get("overall_progress_percent", 0),
                    item.get("recognized_revenue", 0),
                    item.get("accrual_cost", 0),
                    item.get("profit", 0),
                    item.get("margin_percent", 0),
                    item.get("risk_open_count", 0),
                    item.get("risk_critical_count", 0),
                ]
            )

        log_action(
            actor=request.user,
            action=REPORT_EXPORT,
            object_type="REPORT",
            object_id=0,
            request=request,
            meta={
                "report_name": "project_summary",
                "as_of_date": as_of_date.isoformat() if as_of_date else None,
                "row_count": len(projects),
            },
        )
        return response

def _parse_date(value):
    if not value:
        return None
    try:
        return date.fromisoformat(value)
    except ValueError:
        return None
