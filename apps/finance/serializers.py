from rest_framework import serializers

from apps.finance.models import CashEvent


class CashEventSerializer(serializers.ModelSerializer):
    class Meta:
        model = CashEvent
        fields = [
            "id",
            "project",
            "contract_snapshot",
            "account",
            "event_type",
            "status",
            "amount",
            "event_date",
            "description",
            "created_by",
            "created_at",
        ]
        read_only_fields = ["id", "created_by", "created_at"]
