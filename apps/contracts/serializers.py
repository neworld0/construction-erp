from rest_framework import serializers

from .models import ContractChange, ContractChangeStatus


class ContractChangeSerializer(serializers.ModelSerializer):
    class Meta:
        model = ContractChange
        fields = [
            "id",
            "project",
            "change_no",
            "change_type",
            "reason",
            "contract_amount_delta",
            "time_extension_days",
            "status",
            "submitted_by",
            "submitted_at",
            "approved_by",
            "approved_at",
            "created_at",
            "updated_at",
        ]
        read_only_fields = [
            "id",
            "change_no",
            "status",
            "submitted_by",
            "submitted_at",
            "approved_by",
            "approved_at",
            "created_at",
            "updated_at",
        ]
