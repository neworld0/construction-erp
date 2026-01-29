from rest_framework import status, viewsets
from rest_framework.decorators import action
from rest_framework.exceptions import PermissionDenied
from rest_framework.permissions import IsAuthenticated
from rest_framework.response import Response

from .models import DailyReport, DailyReportStatus
from .serializers import DailyReportSerializer
from apps.closing.guards import guard_write


class DailyReportViewSet(viewsets.ModelViewSet):
    queryset = DailyReport.objects.order_by("-report_date", "-updated_at")
    serializer_class = DailyReportSerializer
    permission_classes = [IsAuthenticated]

    @action(detail=True, methods=["post"])
    def submit(self, request, *args, **kwargs):
        report = self.get_object()
        guard_write(
            project=report.project,
            target_date=report.report_date,
            message_context="????? ??????.",
            exc=PermissionDenied,
        )
        if report.status != DailyReportStatus.DRAFT:
            return Response(
                {"detail": "Only draft reports can be submitted."},
                status=status.HTTP_400_BAD_REQUEST,
            )
        report.status = DailyReportStatus.SUBMITTED
        report.save(update_fields=["status"])
        return Response(self.get_serializer(report).data, status=status.HTTP_200_OK)
