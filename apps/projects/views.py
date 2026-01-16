from rest_framework import status, viewsets
from rest_framework.permissions import IsAuthenticated
from rest_framework.response import Response

from apps.core.rbac.models import ProjectAssignment, Role
from apps.core.rbac.permissions import get_user_role, require_project_access

from .models import Project
from .serializers import ProjectSerializer


class ProjectViewSet(viewsets.ModelViewSet):
    queryset = Project.objects.filter(is_active=True).order_by("-created_at")
    serializer_class = ProjectSerializer
    # RBAC(T8-SEC-1)에서 Role/Project 접근 통제 예정
    permission_classes = [IsAuthenticated]

    def get_queryset(self):
        queryset = super().get_queryset()
        if get_user_role(self.request.user) == Role.FIELD:
            allowed_ids = ProjectAssignment.objects.filter(
                user=self.request.user, is_active=True
            ).values_list("project_id", flat=True)
            return queryset.filter(id__in=allowed_ids)
        return queryset

    def get_object(self):
        obj = super().get_object()
        require_project_access(self.request.user, obj.id)
        return obj

    def destroy(self, request, *args, **kwargs):
        instance = self.get_object()
        instance.is_active = False
        instance.save(update_fields=["is_active"])
        return Response(status=status.HTTP_204_NO_CONTENT)
