from django.utils import timezone
from django.core.exceptions import PermissionDenied
from rest_framework import status
from rest_framework.generics import ListAPIView, RetrieveAPIView
from rest_framework.permissions import IsAuthenticated
from rest_framework.response import Response
from rest_framework.views import APIView

from apps.audit.constants import RISK_ACK
from apps.audit.services.logger import log_action
from apps.core.rbac.models import Role
from apps.core.rbac.permissions import get_user_role, require_project_access
from .models import RiskFinding, RiskFindingStatus


class RiskFindingListView(ListAPIView):
    permission_classes = [IsAuthenticated]

    def get_queryset(self):
        queryset = RiskFinding.objects.all().order_by("-created_at")
        project_id = self.request.query_params.get("project_id")
        status_value = self.request.query_params.get("status")
        if get_user_role(self.request.user) == Role.FIELD:
            if not project_id:
                raise PermissionDenied("Project access denied.")
            require_project_access(self.request.user, project_id)
        if project_id:
            queryset = queryset.filter(project_id=project_id)
        if status_value:
            queryset = queryset.filter(status=status_value)
        return queryset

    def list(self, request, *args, **kwargs):
        queryset = self.get_queryset()
        data = [
            {
                "id": finding.id,
                "rule": finding.rule_id,
                "project": finding.project_id,
                "object_type": finding.object_type,
                "object_id": finding.object_id,
                "severity": finding.severity,
                "title": finding.title,
                "status": finding.status,
                "created_at": finding.created_at,
            }
            for finding in queryset
        ]
        return Response(data, status=status.HTTP_200_OK)


class RiskFindingDetailView(RetrieveAPIView):
    permission_classes = [IsAuthenticated]
    queryset = RiskFinding.objects.all()

    def retrieve(self, request, *args, **kwargs):
        finding = self.get_object()
        if finding.project_id:
            require_project_access(request.user, finding.project_id)
        elif get_user_role(request.user) == Role.FIELD:
            raise PermissionDenied("Project access denied.")
        data = {
            "id": finding.id,
            "rule": finding.rule_id,
            "event": finding.event_id,
            "project": finding.project_id,
            "object_type": finding.object_type,
            "object_id": finding.object_id,
            "score": str(finding.score),
            "severity": finding.severity,
            "title": finding.title,
            "details": finding.details,
            "status": finding.status,
            "acknowledged_by": finding.acknowledged_by_id,
            "acknowledged_at": finding.acknowledged_at,
            "created_at": finding.created_at,
            "updated_at": finding.updated_at,
        }
        return Response(data, status=status.HTTP_200_OK)


class RiskFindingAckView(APIView):
    permission_classes = [IsAuthenticated]
    # HQ/CEO만 ACK 허용 (RBAC에서 강화 예정)

    def post(self, request, pk):
        finding = RiskFinding.objects.filter(pk=pk).first()
        if finding is None:
            return Response({"detail": "Finding not found."}, status=status.HTTP_404_NOT_FOUND)
        if finding.project_id:
            require_project_access(request.user, finding.project_id)
        elif get_user_role(request.user) == Role.FIELD:
            return Response({"detail": "Project access denied."}, status=status.HTTP_403_FORBIDDEN)
        if finding.status == RiskFindingStatus.ACK:
            return Response({"detail": "Finding already acknowledged."}, status=status.HTTP_400_BAD_REQUEST)
        before_status = finding.status
        finding.status = RiskFindingStatus.ACK
        finding.acknowledged_by = request.user
        finding.acknowledged_at = timezone.now()
        finding.save(update_fields=["status", "acknowledged_by", "acknowledged_at"])
        log_action(
            actor=request.user,
            action=RISK_ACK,
            object_type="RISK_FINDING",
            object_id=finding.id,
            project=finding.project,
            request=request,
            before={"status": before_status},
            after={"status": finding.status},
            meta={
                "rule_key": finding.rule.key,
                "severity": finding.severity,
                "previous_status": before_status,
                "new_status": finding.status,
            },
        )
        return Response({"id": finding.id, "status": finding.status}, status=status.HTTP_200_OK)
