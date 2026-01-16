from datetime import date

from rest_framework.generics import ListAPIView
from rest_framework.permissions import IsAuthenticated

from .models import AuditLog
from .serializers import AuditLogSerializer


class AuditLogListView(ListAPIView):
    serializer_class = AuditLogSerializer
    permission_classes = [IsAuthenticated]
    # TODO: HQ/CEO only (RBAC enforcement later).

    def get_queryset(self):
        queryset = AuditLog.objects.all().order_by("-created_at")
        params = self.request.query_params

        project_id = params.get("project_id")
        object_type = params.get("object_type")
        object_id = params.get("object_id")
        action = params.get("action")
        actor_id = params.get("actor_id")
        date_from = _parse_date(params.get("date_from"))
        date_to = _parse_date(params.get("date_to"))

        if project_id:
            queryset = queryset.filter(project_id=project_id)
        if object_type:
            queryset = queryset.filter(object_type=object_type)
        if object_id:
            queryset = queryset.filter(object_id=object_id)
        if action:
            queryset = queryset.filter(action=action)
        if actor_id:
            queryset = queryset.filter(actor_id=actor_id)
        if date_from:
            queryset = queryset.filter(created_at__date__gte=date_from)
        if date_to:
            queryset = queryset.filter(created_at__date__lte=date_to)

        return queryset


def _parse_date(value):
    if not value:
        return None
    try:
        return date.fromisoformat(value)
    except ValueError:
        return None
