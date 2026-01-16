from datetime import date

from rest_framework import status, viewsets
from rest_framework.permissions import IsAuthenticated
from rest_framework.response import Response
from rest_framework.views import APIView

from django.utils import timezone

from .models import DailyProgress, PlanChangeRequest, PlanChangeStatus, PlanChangeType
from .serializers import DailyProgressSerializer, PlanChangeRequestSerializer
from .services.plan_change import approve_change_request
from apps.evidence.services.policy import check_evidence_required
from .services.progress_agg import get_project_progress
from apps.audit.constants import PLAN_CHANGE_REJECT, PLAN_CHANGE_SUBMIT
from apps.audit.services.logger import log_action
from apps.core.rbac.permissions import require_project_access


class DailyProgressViewSet(viewsets.ModelViewSet):
    queryset = DailyProgress.objects.all().order_by("-report_date", "-created_at")
    serializer_class = DailyProgressSerializer
    permission_classes = [IsAuthenticated]
    http_method_names = ["get", "post", "patch", "head", "options"]

    def get_queryset(self):
        queryset = super().get_queryset()
        project_id = self.request.query_params.get("project_id")
        if project_id:
            queryset = queryset.filter(project_id=project_id)
        return queryset

    def perform_create(self, serializer):
        progress = serializer.save()
        payload = {
            "prev_progress": None,
            "new_progress": str(progress.progress_percent),
            "delta_percent": str(progress.progress_percent),
        }
        emit_event(
            "DAILY_PROGRESS",
            "PROJECT",
            progress.project_id,
            payload,
            actor=self.request.user,
        )

    def perform_update(self, serializer):
        instance = self.get_object()
        prev_progress = instance.progress_percent
        progress = serializer.save()
        delta = (progress.progress_percent or 0) - (prev_progress or 0)
        payload = {
            "prev_progress": str(prev_progress or 0),
            "new_progress": str(progress.progress_percent),
            "delta_percent": str(delta),
        }
        emit_event(
            "DAILY_PROGRESS",
            "PROJECT",
            progress.project_id,
            payload,
            actor=self.request.user,
        )


class ProgressSummaryView(APIView):
    permission_classes = [IsAuthenticated]
    # FIELD_USER는 배정 프로젝트만 조회(T1-1-4 연계)

    def get(self, request, *args, **kwargs):
        project_id = request.query_params.get("project_id")
        as_of_date_str = request.query_params.get("as_of_date")

        if not project_id:
            data = get_project_progress(None, None)
            return Response(_serialize_summary(data), status=status.HTTP_200_OK)

        require_project_access(request.user, project_id)

        as_of_date = None
        if as_of_date_str:
            try:
                as_of_date = date.fromisoformat(as_of_date_str)
            except ValueError:
                return Response(
                    {"detail": "as_of_date must be YYYY-MM-DD."},
                    status=status.HTTP_400_BAD_REQUEST,
                )

        data = get_project_progress(project_id, as_of_date)
        return Response(_serialize_summary(data), status=status.HTTP_200_OK)


def _serialize_summary(data):
    return {
        "project_id": data["project_id"],
        "plan_id": data["plan_id"],
        "plan_version_no": data["plan_version_no"],
        "as_of_date": data["as_of_date"].isoformat() if data["as_of_date"] else None,
        "overall_progress_percent": str(data["overall_progress_percent"]),
        "tasks": [
            {
                "task_id": task["task_id"],
                "name": task["name"],
                "weight_percent": str(task["weight_percent"]),
                "latest_progress_percent": str(task["latest_progress_percent"]),
            }
            for task in data["tasks"]
        ],
    }


class PlanChangeRequestViewSet(viewsets.ModelViewSet):
    queryset = PlanChangeRequest.objects.all().order_by("-created_at")
    serializer_class = PlanChangeRequestSerializer
    permission_classes = [IsAuthenticated]
    http_method_names = ["get", "post", "head", "options"]

    def submit(self, request, *args, **kwargs):
        change_request = self.get_object()
        if change_request.status != PlanChangeStatus.DRAFT:
            return Response(
                {"detail": "Only draft change requests can be submitted."},
                status=status.HTTP_400_BAD_REQUEST,
            )
        if change_request.change_type == PlanChangeType.CHANGE_ORDER:
            if change_request.contract_change is None:
                return Response(
                    {"detail": "contract_change is required for change_order."},
                    status=status.HTTP_400_BAD_REQUEST,
                )
            if change_request.contract_change.status != "approved":
                return Response(
                    {"detail": "contract_change must be approved."},
                    status=status.HTTP_400_BAD_REQUEST,
                )
        ok, reason = check_evidence_required("PLAN_CHANGE_REQUEST", change_request.id, "SUBMIT")
        if not ok:
            return Response({"detail": reason}, status=status.HTTP_400_BAD_REQUEST)
        before_status = change_request.status
        change_request.status = PlanChangeStatus.SUBMITTED
        change_request.requested_by = request.user
        change_request.requested_at = timezone.now()
        change_request.save(update_fields=["status", "requested_by", "requested_at"])
        log_action(
            actor=request.user,
            action=PLAN_CHANGE_SUBMIT,
            object_type="PLAN_CHANGE_REQUEST",
            object_id=change_request.id,
            project=change_request.project,
            request=request,
            before={"status": before_status},
            after={"status": change_request.status},
        )
        return Response(self.get_serializer(change_request).data, status=status.HTTP_200_OK)

    def approve(self, request, *args, **kwargs):
        # HQ/CEO approval gating will be enforced by RBAC later.
        change_request = self.get_object()
        if change_request.status != PlanChangeStatus.SUBMITTED:
            return Response(
                {"detail": "Only submitted change requests can be approved."},
                status=status.HTTP_400_BAD_REQUEST,
            )
        if change_request.change_type == PlanChangeType.CHANGE_ORDER:
            if change_request.contract_change is None:
                return Response(
                    {"detail": "contract_change is required for change_order."},
                    status=status.HTTP_400_BAD_REQUEST,
                )
            if change_request.contract_change.status != "approved":
                return Response(
                    {"detail": "contract_change must be approved."},
                    status=status.HTTP_400_BAD_REQUEST,
                )
        ok, reason = check_evidence_required("PLAN_CHANGE_REQUEST", change_request.id, "APPROVE")
        if not ok:
            return Response({"detail": reason}, status=status.HTTP_400_BAD_REQUEST)
        approve_change_request(change_request.id, request.user, request=request)
        change_request.refresh_from_db()
        # AuditLog(T8-2) integration point.
        return Response(self.get_serializer(change_request).data, status=status.HTTP_200_OK)

    def reject(self, request, *args, **kwargs):
        # HQ/CEO approval gating will be enforced by RBAC later.
        change_request = self.get_object()
        if change_request.status != PlanChangeStatus.SUBMITTED:
            return Response(
                {"detail": "Only submitted change requests can be rejected."},
                status=status.HTTP_400_BAD_REQUEST,
            )
        before_status = change_request.status
        change_request.status = PlanChangeStatus.REJECTED
        change_request.save(update_fields=["status"])
        log_action(
            actor=request.user,
            action=PLAN_CHANGE_REJECT,
            object_type="PLAN_CHANGE_REQUEST",
            object_id=change_request.id,
            project=change_request.project,
            request=request,
            before={"status": before_status},
            after={"status": change_request.status},
        )
        return Response(self.get_serializer(change_request).data, status=status.HTTP_200_OK)
