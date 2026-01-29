from django.utils import timezone
from rest_framework import status, viewsets
from rest_framework.exceptions import PermissionDenied
from rest_framework.permissions import IsAuthenticated
from rest_framework.response import Response

from apps.audit.constants import CONTRACT_REJECT, CONTRACT_SUBMIT
from apps.audit.services.logger import log_action
from .services import approve_contract_change
from .models import ContractChange, ContractChangeStatus
from .serializers import ContractChangeSerializer
from apps.evidence.services.policy import check_evidence_required
from apps.closing.guards import guard_write


class ContractChangeViewSet(viewsets.ModelViewSet):
    queryset = ContractChange.objects.all().order_by("-created_at")
    serializer_class = ContractChangeSerializer
    permission_classes = [IsAuthenticated]

    def update(self, request, *args, **kwargs):
        instance = self.get_object()
        guard_write(
            project=instance.project,
            target_date=timezone.localdate(),
            message_context="계약 변경 기준일입니다.",
            exc=PermissionDenied,
        )
        if instance.status == ContractChangeStatus.APPROVED:
            return Response(
                {"detail": "Approved contract change cannot be modified."},
                status=status.HTTP_400_BAD_REQUEST,
            )
        return super().update(request, *args, **kwargs)

    def partial_update(self, request, *args, **kwargs):
        instance = self.get_object()
        guard_write(
            project=instance.project,
            target_date=timezone.localdate(),
            message_context="계약 변경 기준일입니다.",
            exc=PermissionDenied,
        )
        if instance.status == ContractChangeStatus.APPROVED:
            return Response(
                {"detail": "Approved contract change cannot be modified."},
                status=status.HTTP_400_BAD_REQUEST,
            )
        return super().partial_update(request, *args, **kwargs)

    def submit(self, request, *args, **kwargs):
        change = self.get_object()
        guard_write(
            project=change.project,
            target_date=timezone.localdate(),
            message_context="계약 변경 제출 기준일입니다.",
            exc=PermissionDenied,
        )
        if change.status != ContractChangeStatus.DRAFT:
            return Response(
                {"detail": "Only draft contract changes can be submitted."},
                status=status.HTTP_400_BAD_REQUEST,
            )
        ok, reason = check_evidence_required("CONTRACT_CHANGE", change.id, "SUBMIT")
        if not ok:
            return Response({"detail": reason}, status=status.HTTP_400_BAD_REQUEST)
        before_status = change.status
        change.status = ContractChangeStatus.SUBMITTED
        change.submitted_by = request.user
        change.submitted_at = timezone.now()
        change.save(update_fields=["status", "submitted_by", "submitted_at"])
        log_action(
            actor=request.user,
            action=CONTRACT_SUBMIT,
            object_type="CONTRACT_CHANGE",
            object_id=change.id,
            project=change.project,
            request=request,
            before={"status": before_status},
            after={"status": change.status},
            meta={
                "contract_amount_delta": str(change.contract_amount_delta),
                "time_extension_days": change.time_extension_days,
            },
        )
        return Response(self.get_serializer(change).data, status=status.HTTP_200_OK)

    def approve(self, request, *args, **kwargs):
        # HQ/CEO approval will be enforced by RBAC later.
        change = self.get_object()
        if change.status != ContractChangeStatus.SUBMITTED:
            return Response(
                {"detail": "Only submitted contract changes can be approved."},
                status=status.HTTP_400_BAD_REQUEST,
            )
        ok, reason = check_evidence_required("CONTRACT_CHANGE", change.id, "APPROVE")
        if not ok:
            return Response({"detail": reason}, status=status.HTTP_400_BAD_REQUEST)
        change = approve_contract_change(change.id, request.user, request=request)
        return Response(self.get_serializer(change).data, status=status.HTTP_200_OK)

    def reject(self, request, *args, **kwargs):
        # HQ/CEO approval will be enforced by RBAC later.
        change = self.get_object()
        if change.status != ContractChangeStatus.SUBMITTED:
            return Response(
                {"detail": "Only submitted contract changes can be rejected."},
                status=status.HTTP_400_BAD_REQUEST,
            )
        before_status = change.status
        change.status = ContractChangeStatus.REJECTED
        change.save(update_fields=["status"])
        log_action(
            actor=request.user,
            action=CONTRACT_REJECT,
            object_type="CONTRACT_CHANGE",
            object_id=change.id,
            project=change.project,
            request=request,
            before={"status": before_status},
            after={"status": change.status},
            meta={
                "contract_amount_delta": str(change.contract_amount_delta),
                "time_extension_days": change.time_extension_days,
            },
        )
        return Response(self.get_serializer(change).data, status=status.HTTP_200_OK)
