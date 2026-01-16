from datetime import date

from rest_framework import serializers

from apps.cost.models import CostItem

from .models import DailyReport, DailyReportLine, DailyReportStatus


class DailyReportLineSerializer(serializers.ModelSerializer):
    class Meta:
        model = DailyReportLine
        fields = [
            "id",
            "cost_item",
            "description",
            "quantity",
            "unit_price",
            "amount",
            "created_at",
            "updated_at",
        ]
        read_only_fields = ["id", "amount", "created_at", "updated_at"]

    def validate_cost_item(self, value):
        if value is None:
            return value
        if isinstance(value, CostItem) and not value.is_active:
            raise serializers.ValidationError("inactive cost_item is not allowed.")
        return value

    def validate_quantity(self, value):
        if value is not None and value < 0:
            raise serializers.ValidationError("quantity must be >= 0.")
        return value

    def validate_unit_price(self, value):
        if value is not None and value < 0:
            raise serializers.ValidationError("unit_price must be >= 0.")
        return value


class DailyReportSerializer(serializers.ModelSerializer):
    lines = DailyReportLineSerializer(many=True)

    class Meta:
        model = DailyReport
        fields = [
            "id",
            "project",
            "report_date",
            "reporter",
            "note",
            "status",
            "lines",
            "created_at",
            "updated_at",
        ]
        read_only_fields = ["id", "status", "created_at", "updated_at"]

    def validate_report_date(self, value):
        if value and value > date.today():
            raise serializers.ValidationError("report_date cannot be in the future.")
        return value

    def create(self, validated_data):
        lines_data = validated_data.pop("lines", [])
        report = DailyReport.objects.create(**validated_data)
        for line_data in lines_data:
            DailyReportLine.objects.create(report=report, **line_data)
        return report

    def update(self, instance, validated_data):
        lines_data = validated_data.pop("lines", None)
        for field, value in validated_data.items():
            setattr(instance, field, value)
        instance.save()

        if lines_data is not None:
            instance.lines.all().delete()
            for line_data in lines_data:
                DailyReportLine.objects.create(report=instance, **line_data)

        return instance
