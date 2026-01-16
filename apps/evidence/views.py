from rest_framework import status
from rest_framework.generics import ListCreateAPIView, RetrieveAPIView
from rest_framework.parsers import FormParser, MultiPartParser
from rest_framework.permissions import IsAuthenticated
from django.http import FileResponse
from rest_framework.response import Response
from rest_framework.views import APIView
from django.core.exceptions import PermissionDenied

from apps.audit.constants import EVIDENCE_CREATE, EVIDENCE_FILE_ADD, FILE_DOWNLOAD
from apps.audit.services.logger import log_action
from apps.core.rbac.models import Role
from apps.core.rbac.permissions import get_user_role, require_project_access
from .models import Evidence, EvidenceFile
from .serializers import EvidenceFileSerializer, EvidenceSerializer
from .services.resolve import resolve_project_for_evidence, resolve_project_for_evidence_file


class EvidenceListCreateView(ListCreateAPIView):
    serializer_class = EvidenceSerializer
    permission_classes = [IsAuthenticated]

    def get_queryset(self):
        queryset = Evidence.objects.all().order_by("-created_at")
        object_type = self.request.query_params.get("object_type")
        object_id = self.request.query_params.get("object_id")
        role = get_user_role(self.request.user)
        if object_type:
            queryset = queryset.filter(object_type=object_type)
        if object_id:
            queryset = queryset.filter(object_id=object_id)
        if role == Role.FIELD:
            if not object_type or not object_id:
                raise PermissionDenied("Project access denied.")
            evidence = Evidence.objects.filter(
                object_type=object_type, object_id=object_id
            ).first()
            if evidence:
                project = resolve_project_for_evidence(evidence)
                if project is None:
                    raise PermissionDenied("Project access denied.")
                require_project_access(self.request.user, project.id)
        return queryset

    def perform_create(self, serializer):
        evidence = serializer.save(created_by=self.request.user)
        project = resolve_project_for_evidence(evidence)
        log_action(
            actor=self.request.user,
            action=EVIDENCE_CREATE,
            object_type="EVIDENCE",
            object_id=evidence.id,
            project=project,
            request=self.request,
            after={"title": evidence.title},
            meta={"object_type": evidence.object_type, "object_id": evidence.object_id},
        )


class EvidenceDetailView(RetrieveAPIView):
    serializer_class = EvidenceSerializer
    permission_classes = [IsAuthenticated]
    queryset = Evidence.objects.all()

    def retrieve(self, request, *args, **kwargs):
        evidence = self.get_object()
        project = resolve_project_for_evidence(evidence)
        if project is None and get_user_role(request.user) == Role.FIELD:
            raise PermissionDenied("Project access denied.")
        if project is not None:
            require_project_access(request.user, project.id)
        return Response(self.get_serializer(evidence).data, status=status.HTTP_200_OK)


class EvidenceFileUploadView(APIView):
    permission_classes = [IsAuthenticated]
    parser_classes = [MultiPartParser, FormParser]

    def post(self, request, pk):
        evidence = Evidence.objects.filter(pk=pk).first()
        if evidence is None:
            return Response({"detail": "Evidence not found."}, status=status.HTTP_404_NOT_FOUND)
        project = resolve_project_for_evidence(evidence)
        if project is None and get_user_role(request.user) == Role.FIELD:
            return Response({"detail": "Project access denied."}, status=status.HTTP_403_FORBIDDEN)
        if project is not None:
            require_project_access(request.user, project.id)

        serializer = EvidenceFileSerializer(
            data={"evidence": evidence.id, "file": request.FILES.get("file")},
            context={"request": request},
        )
        serializer.is_valid(raise_exception=True)
        file_obj = serializer.save()
        log_action(
            actor=request.user,
            action=EVIDENCE_FILE_ADD,
            object_type="EVIDENCE",
            object_id=evidence.id,
            project=project,
            request=request,
            after={"file_id": file_obj.id},
            meta={
                "original_name": file_obj.original_name,
                "size_bytes": file_obj.size_bytes,
                "content_type": file_obj.content_type,
                "sha256": file_obj.sha256,
            },
        )
        return Response(EvidenceFileSerializer(file_obj).data, status=status.HTTP_201_CREATED)


class EvidenceFileDownloadView(APIView):
    permission_classes = [IsAuthenticated]

    def get(self, request, pk):
        project, object_type, object_id, evidence, evidence_file = resolve_project_for_evidence_file(pk)
        require_project_access(request.user, project.id)

        log_action(
            actor=request.user,
            action=FILE_DOWNLOAD,
            object_type="EVIDENCE_FILE",
            object_id=evidence_file.id,
            project=project,
            request=request,
            meta={
                "original_name": evidence_file.original_name,
                "size_bytes": evidence_file.size_bytes,
                "sha256": evidence_file.sha256,
                "linked_object_type": object_type,
                "linked_object_id": object_id,
            },
        )

        response = FileResponse(evidence_file.file.open("rb"))
        content_type = evidence_file.content_type or "application/octet-stream"
        response["Content-Type"] = content_type
        response["Content-Disposition"] = f'attachment; filename="{evidence_file.original_name}"'
        return response
