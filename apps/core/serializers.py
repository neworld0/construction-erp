from django.utils import timezone
from rest_framework import serializers

from apps.audit.constants import APPROVAL_SUBMIT
from apps.audit.services.logger import log_action
from apps.cost.models import CostActual, CostActualStatus
from apps.core.services.approvals import approve_request, reject_request

from .models import ApprovalRequest, ApprovalStatus


class ApprovalRequestSerializer(serializers.ModelSerializer):
    class Meta:
        model = ApprovalRequest
        fields = [
            "id",
            "object_type",
            "object_id",
            "status",
            "submitted_by",
            "submitted_at",
            "approved_by",
            "approved_at",
            "comment",
            "reject_reason",
            "created_at",
            "updated_at",
        ]
        read_only_fields = fields


class ApprovalSubmitSerializer(serializers.Serializer):
    object_type = serializers.CharField(max_length=50)
    object_id = serializers.IntegerField()
    comment = serializers.CharField(allow_blank=True, required=False)

    def validate_object_type(self, value):
        if value != "COST_ACTUAL":
            raise serializers.ValidationError("Unsupported object_type.")
        return value

    def validate(self, attrs):
        object_type = attrs.get("object_type")
        object_id = attrs.get("object_id")

        if object_type == "COST_ACTUAL":
            try:
                cost_actual = CostActual.objects.get(id=object_id)
            except CostActual.DoesNotExist:
                raise serializers.ValidationError({"object_id": "CostActual not found."})

            if cost_actual.status not in (CostActualStatus.DRAFT, CostActualStatus.SUBMITTED):
                raise serializers.ValidationError(
                    {"object_id": "CostActual must be draft or submitted."}
                )

            attrs["cost_actual"] = cost_actual

        return attrs

    def create(self, validated_data):
        cost_actual = validated_data["cost_actual"]
        comment = validated_data.get("comment", "")
        user = self.context["request"].user

        approvals = ApprovalRequest.objects.filter(
            object_type="COST_ACTUAL",
            object_id=cost_actual.id,
        ).order_by("id")
        approval = approvals.first()
        before_status = approval.status if approval else None
        if approval is None:
            approval = ApprovalRequest(object_type="COST_ACTUAL", object_id=cost_actual.id)
        else:
            approvals.exclude(id=approval.id).delete()
        approval.status = ApprovalStatus.SUBMITTED
        approval.submitted_by = user
        approval.submitted_at = timezone.now()
        approval.comment = comment
        approval.reject_reason = ""
        approval.save()
        log_action(
            actor=user,
            action=APPROVAL_SUBMIT,
            object_type="APPROVAL_REQUEST",
            object_id=approval.id,
            project=cost_actual.project,
            request=self.context.get("request"),
            before={"status": before_status},
            after={"status": approval.status},
        )
        return approval


class ApprovalDecisionSerializer(serializers.Serializer):
    comment = serializers.CharField(allow_blank=True, required=False)
    reject_reason = serializers.CharField(allow_blank=True, required=False)

    def approve(self, approval: ApprovalRequest):
        if approval.status != ApprovalStatus.SUBMITTED:
            raise serializers.ValidationError("Approval request is not submitted.")

        user = self.context["request"].user
        return approve_request(
            approval.id,
            user,
            comment=self.validated_data.get("comment"),
            request=self.context.get("request"),
        )

    def reject(self, approval: ApprovalRequest):
        if approval.status != ApprovalStatus.SUBMITTED:
            raise serializers.ValidationError("Approval request is not submitted.")

        return reject_request(
            approval.id,
            self.context["request"].user,
            reject_reason=self.validated_data.get("reject_reason"),
            comment=self.validated_data.get("comment"),
            request=self.context.get("request"),
        )
