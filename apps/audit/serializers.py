from rest_framework import serializers

from .models import AuditLog


class AuditLogSerializer(serializers.ModelSerializer):
    class Meta:
        model = AuditLog
        fields = [
            "created_at",
            "actor",
            "action",
            "object_type",
            "object_id",
            "project",
            "meta_json",
        ]
