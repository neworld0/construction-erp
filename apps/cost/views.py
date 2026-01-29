from decimal import Decimal

from django.utils import timezone
from rest_framework import status, viewsets
from rest_framework.exceptions import PermissionDenied
from rest_framework.generics import GenericAPIView
from rest_framework.permissions import IsAuthenticated
from rest_framework.response import Response

from apps.projects.models import Project
from apps.closing.guards import guard_write

from .models import CostActual, CostActualStatus, CostItem, RevenueRecognition
from .serializers import (
    CostActualCreateFromDailyReportSerializer,
    CostActualSerializer,
    CostItemSerializer,
    RevenueRecognitionCreateSerializer,
    RevenueRecognitionSerializer,
)
from .services.accrual_cost import get_accrual_cost_by_project, get_accrual_cost_by_snapshot
from apps.risk.services.engine import emit_event
from apps.core.rbac.models import Role
from apps.core.rbac.permissions import get_user_role, require_project_access


class CostItemViewSet(viewsets.ModelViewSet):
    queryset = (
        CostItem.objects.filter(is_active=True)
        .prefetch_related("aliases")
        .order_by("sort_order", "-created_at")
    )
    serializer_class = CostItemSerializer
    # HQ만 생성/수정 허용하도록 RBAC에서 제어 예정
    permission_classes = [IsAuthenticated]

    def destroy(self, request, *args, **kwargs):
        instance = self.get_object()
        instance.is_active = False
        instance.save(update_fields=["is_active"])
        return Response(status=status.HTTP_204_NO_CONTENT)


class CostActualViewSet(viewsets.ModelViewSet):
    queryset = CostActual.objects.all()
    serializer_class = CostActualSerializer
    permission_classes = [IsAuthenticated]
    http_method_names = ["get", "patch", "post", "head", "options"]

    def create(self, request, *args, **kwargs):
        return Response(status=status.HTTP_405_METHOD_NOT_ALLOWED)

    def update(self, request, *args, **kwargs):
        instance = self.get_object()
        guard_write(
            project=instance.project,
            target_date=instance.report_date,
            message_context="?? ??????.",
            exc=PermissionDenied,
        )
        if instance.status == CostActualStatus.CLOSED:
            return Response(
                {"detail": "Closed cost actual cannot be modified."},
                status=status.HTTP_400_BAD_REQUEST,
            )
        return super().update(request, *args, **kwargs)

    def partial_update(self, request, *args, **kwargs):
        instance = self.get_object()
        guard_write(
            project=instance.project,
            target_date=instance.report_date,
            message_context="?? ??????.",
            exc=PermissionDenied,
        )
        if instance.status == CostActualStatus.CLOSED:
            return Response(
                {"detail": "Closed cost actual cannot be modified."},
                status=status.HTTP_400_BAD_REQUEST,
            )
        return super().partial_update(request, *args, **kwargs)

    def from_daily_report(self, request, *args, **kwargs):
        serializer = CostActualCreateFromDailyReportSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        cost_actual = serializer.save()
        response_serializer = self.get_serializer(cost_actual)
        return Response(response_serializer.data, status=status.HTTP_201_CREATED)

    def approve(self, request, *args, **kwargs):
        # HQ만 승인/마감 허용하도록 RBAC에서 강화 예정
        cost_actual = self.get_object()
        if cost_actual.status not in (CostActualStatus.DRAFT, CostActualStatus.SUBMITTED):
            return Response(
                {"detail": "Only draft or submitted cost actual can be approved."},
                status=status.HTTP_400_BAD_REQUEST,
            )
        cost_actual.status = CostActualStatus.APPROVED
        cost_actual.approved_by = request.user
        cost_actual.approved_at = timezone.now()
        cost_actual.save(update_fields=["status", "approved_by", "approved_at"])
        emit_event(
            "COST_APPROVED",
            "COST_ACTUAL",
            cost_actual.id,
            {"status": "approved"},
            actor=request.user,
        )
        return Response(self.get_serializer(cost_actual).data, status=status.HTTP_200_OK)

    def close(self, request, *args, **kwargs):
        # HQ만 승인/마감 허용하도록 RBAC에서 강화 예정
        cost_actual = self.get_object()
        if cost_actual.status != CostActualStatus.APPROVED:
            return Response(
                {"detail": "Only approved cost actual can be closed."},
                status=status.HTTP_400_BAD_REQUEST,
            )
        cost_actual.status = CostActualStatus.CLOSED
        cost_actual.closed_at = timezone.now()
        cost_actual.save(update_fields=["status", "closed_at"])
        emit_event(
            "COST_APPROVED",
            "COST_ACTUAL",
            cost_actual.id,
            {"status": "closed"},
            actor=request.user,
        )
        return Response(self.get_serializer(cost_actual).data, status=status.HTTP_200_OK)


class AccrualCostView(GenericAPIView):
    permission_classes = [IsAuthenticated]
    # FIELD_USER는 배정된 Project만 조회 (T1-1-4 연계)

    def get(self, request, *args, **kwargs):
        project_id = request.query_params.get("project_id")
        snapshot_id = request.query_params.get("snapshot_id")

        if not project_id and not snapshot_id:
            return Response(
                {"detail": "project_id or snapshot_id is required."},
                status=status.HTTP_400_BAD_REQUEST,
            )

        if snapshot_id:
            snapshot = None
            try:
                snapshot_model = CostActual._meta.get_field("contract_snapshot").remote_field.model
                snapshot = snapshot_model.objects.filter(id=snapshot_id).first()
            except Exception:
                snapshot = None
            if snapshot is None:
                return Response(
                    {"detail": "snapshot not found."},
                    status=status.HTTP_400_BAD_REQUEST,
                )
            project_id = getattr(snapshot, "project_id", None)
            if project_id:
                require_project_access(request.user, project_id)
            summary = get_accrual_cost_by_snapshot(snapshot)
            return Response(_serialize_summary(summary), status=status.HTTP_200_OK)

        project = Project.objects.filter(id=project_id).first()
        if project is None:
            return Response({"detail": "project not found."}, status=status.HTTP_400_BAD_REQUEST)

        require_project_access(request.user, project_id)
        summary = get_accrual_cost_by_project(project)
        return Response(_serialize_summary(summary), status=status.HTTP_200_OK)


def _serialize_summary(summary):
    return {
        "total_cost": str(summary["total_cost"] or Decimal("0")),
        "by_category": {
            key: str(value or Decimal("0")) for key, value in summary["by_category"].items()
        },
    }


class RevenueRecognitionView(GenericAPIView):
    permission_classes = [IsAuthenticated]
    # RBAC will restrict this endpoint by role in a later phase.

    def get(self, request, *args, **kwargs):
        project_id = request.query_params.get("project_id")
        snapshot_id = request.query_params.get("snapshot_id")
        queryset = RevenueRecognition.objects.all().order_by("-as_of_date", "-id")

        if snapshot_id:
            resolved_project_id = RevenueRecognition.objects.filter(
                contract_snapshot=snapshot_id
            ).values_list("project_id", flat=True).first()
            if resolved_project_id:
                require_project_access(request.user, resolved_project_id)
            elif get_user_role(request.user) == Role.FIELD:
                return Response(
                    {"detail": "Project access denied."},
                    status=status.HTTP_403_FORBIDDEN,
                )
            queryset = queryset.filter(contract_snapshot=snapshot_id)
        elif project_id:
            require_project_access(request.user, project_id)
            queryset = queryset.filter(project_id=project_id)
        else:
            return Response(
                {"detail": "project_id or snapshot_id is required."},
                status=status.HTTP_400_BAD_REQUEST,
            )

        serializer = RevenueRecognitionSerializer(queryset, many=True)
        return Response(serializer.data, status=status.HTTP_200_OK)

    def post(self, request, *args, **kwargs):
        serializer = RevenueRecognitionCreateSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        record = serializer.save()
        return Response(
            RevenueRecognitionSerializer(record).data, status=status.HTTP_201_CREATED
        )
