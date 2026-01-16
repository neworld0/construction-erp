from datetime import date

from rest_framework import status
from rest_framework.permissions import IsAuthenticated
from rest_framework.response import Response
from rest_framework.views import APIView

from apps.core.rbac.models import Role
from apps.core.rbac.permissions import require_project_access, require_role
from apps.finance.serializers import CashEventSerializer
from apps.finance.services.cash_summary import get_cash_summary
from .services.profit_loss import get_profit_loss_by_project, get_profit_loss_by_snapshot


class ProfitLossView(APIView):
    permission_classes = [IsAuthenticated]
    # FIELD_USER는 배정된 프로젝트만 조회(T1-1-4에서 적용)

    def get(self, request, *args, **kwargs):
        snapshot_id = request.query_params.get("snapshot_id")
        project_id = request.query_params.get("project_id")

        if snapshot_id:
            data = get_profit_loss_by_snapshot(snapshot_id)
            project_id = data.get("project_id")
            if not project_id:
                return Response(
                    {"detail": "snapshot project not found."},
                    status=status.HTTP_400_BAD_REQUEST,
                )
            require_project_access(request.user, project_id)
            return Response(data, status=status.HTTP_200_OK)

        if project_id:
            require_project_access(request.user, project_id)
            data = get_profit_loss_by_project(project_id)
            return Response(data, status=status.HTTP_200_OK)

        return Response(
            {"detail": "snapshot_id or project_id is required."},
            status=status.HTTP_400_BAD_REQUEST,
        )


class CashSummaryView(APIView):
    permission_classes = [IsAuthenticated]
    # FIELD_USER는 배정 프로젝트만 조회(T1-1-4 연계)

    def get(self, request, *args, **kwargs):
        project_id = request.query_params.get("project_id")
        date_from = request.query_params.get("from")
        date_to = request.query_params.get("to")

        if not project_id:
            return Response(
                {"detail": "project_id is required."},
                status=status.HTTP_400_BAD_REQUEST,
            )

        require_project_access(request.user, project_id)

        parsed_from = None
        parsed_to = None
        if date_from:
            try:
                parsed_from = date.fromisoformat(date_from)
            except ValueError:
                return Response(
                    {"detail": "from must be YYYY-MM-DD."},
                    status=status.HTTP_400_BAD_REQUEST,
                )
        if date_to:
            try:
                parsed_to = date.fromisoformat(date_to)
            except ValueError:
                return Response(
                    {"detail": "to must be YYYY-MM-DD."},
                    status=status.HTTP_400_BAD_REQUEST,
                )

        summary = get_cash_summary(project_id, parsed_from, parsed_to)
        return Response(
            {key: str(value) for key, value in summary.items()},
            status=status.HTTP_200_OK,
        )


class CashEventCreateView(APIView):
    permission_classes = [IsAuthenticated]
    # HQ/CEO만 생성 허용 (RBAC 강화 예정)

    def post(self, request, *args, **kwargs):
        require_role(request.user, [Role.CEO, Role.HQ])
        serializer = CashEventSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        event = serializer.save(created_by=request.user)
        return Response(
            CashEventSerializer(event).data,
            status=status.HTTP_201_CREATED,
        )
