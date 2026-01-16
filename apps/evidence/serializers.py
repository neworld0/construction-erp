from rest_framework import serializers

from .models import Evidence, EvidenceFile


class EvidenceSerializer(serializers.ModelSerializer):
    class Meta:
        model = Evidence
        fields = [
            "id",
            "title",
            "description",
            "object_type",
            "object_id",
            "status",
            "created_by",
            "created_at",
            "updated_at",
        ]
        read_only_fields = ["id", "created_by", "created_at", "updated_at"]


class EvidenceFileSerializer(serializers.ModelSerializer):
    class Meta:
        model = EvidenceFile
        fields = [
            "id",
            "evidence",
            "file",
            "original_name",
            "content_type",
            "size_bytes",
            "sha256",
            "created_by",
            "created_at",
        ]
        read_only_fields = [
            "id",
            "original_name",
            "content_type",
            "size_bytes",
            "sha256",
            "created_by",
            "created_at",
        ]

    def create(self, validated_data):
        file_obj = validated_data["file"]
        validated_data["original_name"] = file_obj.name
        validated_data["content_type"] = getattr(file_obj, "content_type", "")
        validated_data["created_by"] = self.context["request"].user
        return super().create(validated_data)
