from datetime import date

from django.db import models
from rest_framework import serializers

from apps.field.models import DailyReport, DailyReportStatus
from apps.closing.guards import guard_write

from .models import CostActual, CostActualLine, CostItem, RevenueRecognition, _get_active_snapshot


class CostItemSerializer(serializers.ModelSerializer):
    display_name = serializers.SerializerMethodField()
    class Meta:
        model = CostItem
        fields = [
            "id",
            "code",
            "name",
            "display_name",
            "cost_type",
            "work_type",
            "category",
            "unit",
            "is_direct",
            "is_active",
            "sort_order",
            "created_at",
            "updated_at",
        ]
        read_only_fields = ["id", "created_at", "updated_at"]

    def get_display_name(self, obj):
        return obj.get_display_name()

    def validate_code(self, value):
        if not value or not value.strip():
            raise serializers.ValidationError("code must not be blank.")
        return value.strip()

    def validate_name(self, value):
        if not value or not value.strip():
            raise serializers.ValidationError("name must not be blank.")
        return value.strip()

    def validate_sort_order(self, value):
        if value < 0:
            raise serializers.ValidationError("sort_order must be >= 0.")
        return value


class CostActualLineSerializer(serializers.ModelSerializer):
    class Meta:
        model = CostActualLine
        fields = [
            "id",
            "cost_item",
            "description",
            "quantity",
            "unit_price",
            "amount",
            "vat_treatment",
            "supply_amount",
            "vat_amount",
            "accounting_cost_amount",
            "created_at",
            "updated_at",
        ]
        read_only_fields = ["id", "amount", "supply_amount", "vat_amount", "accounting_cost_amount", "created_at", "updated_at"]


class CostActualSerializer(serializers.ModelSerializer):
    lines = CostActualLineSerializer(many=True, read_only=True)

    class Meta:
        model = CostActual
        fields = [
            "id",
            "project",
            "report_date",
            "source_daily_report",
            "status",
            "total_amount",
            "approved_by",
            "approved_at",
            "closed_at",
            "lines",
            "created_at",
            "updated_at",
        ]
        read_only_fields = [
            "id",
            "status",
            "total_amount",
            "approved_by",
            "approved_at",
            "closed_at",
            "created_at",
            "updated_at",
        ]


class CostActualCreateFromDailyReportSerializer(serializers.Serializer):
    daily_report_id = serializers.IntegerField()

    def validate_daily_report_id(self, value):
        try:
            report = DailyReport.objects.get(id=value)
        except DailyReport.DoesNotExist:
            raise serializers.ValidationError("daily_report not found.")

        guard_write(
            project=report.project,
            target_date=report.report_date,
            message_context="?? ??????.",
            exc=serializers.ValidationError,
        )

        if report.status != DailyReportStatus.SUBMITTED:
            raise serializers.ValidationError("daily_report must be submitted.")

        if hasattr(report, "costactual"):
            raise serializers.ValidationError("cost actual already exists for this report.")

        inactive_lines = report.lines.filter(cost_item__is_active=False)
        if inactive_lines.exists():
            raise serializers.ValidationError("inactive cost_item exists in report lines.")

        return value

    def create(self, validated_data):
        report = DailyReport.objects.get(id=validated_data["daily_report_id"])

        cost_actual = CostActual.objects.create(
            project=report.project,
            report_date=report.report_date,
            source_daily_report=report,
        )

        for line in report.lines.all():
            CostActualLine.objects.create(
                cost_actual=cost_actual,
                cost_item=line.cost_item,
                description=line.description,
                quantity=line.quantity,
                unit_price=line.unit_price,
            )

        cost_actual.recalculate_total()
        return cost_actual


class RevenueRecognitionSerializer(serializers.ModelSerializer):
    class Meta:
        model = RevenueRecognition
        fields = [
            "id",
            "project",
            "contract_snapshot",
            "as_of_date",
            "progress_percent",
            "recognized_revenue",
            "delta_revenue",
            "created_at",
        ]
        read_only_fields = fields


class RevenueRecognitionCreateSerializer(serializers.Serializer):
    project_id = serializers.IntegerField()
    as_of_date = serializers.DateField()
    progress_percent = serializers.DecimalField(max_digits=6, decimal_places=3)
    snapshot_id = serializers.IntegerField(required=False, allow_null=True)

    def validate_progress_percent(self, value):
        if value < 0 or value > 100:
            raise serializers.ValidationError("progress_percent must be between 0 and 100.")
        return value

    def validate_as_of_date(self, value):
        if value > date.today():
            raise serializers.ValidationError("as_of_date cannot be in the future.")
        return value

    def validate(self, attrs):
        project_id = attrs["project_id"]
        snapshot_id = attrs.get("snapshot_id")

        try:
            project = RevenueRecognition._meta.get_field("project").remote_field.model.objects.get(
                id=project_id
            )
        except RevenueRecognition._meta.get_field("project").remote_field.model.DoesNotExist:
            raise serializers.ValidationError({"project_id": "project not found."})

        snapshot = None
        snapshot_field = RevenueRecognition._meta.get_field("contract_snapshot")
        if snapshot_id:
            if isinstance(snapshot_field, models.ForeignKey):
                snapshot = snapshot_field.remote_field.model.objects.filter(id=snapshot_id).first()
                if snapshot is None or getattr(snapshot, "project_id", None) != project.id:
                    raise serializers.ValidationError({"snapshot_id": "snapshot does not match project."})
            else:
                active_snapshot = _get_active_snapshot(project)
                if active_snapshot is not None and getattr(active_snapshot, "id", None) != snapshot_id:
                    raise serializers.ValidationError({"snapshot_id": "snapshot does not match project."})
                snapshot = active_snapshot

        attrs["project"] = project
        attrs["snapshot"] = snapshot
        return attrs

    def create(self, validated_data):
        project = validated_data["project"]
        snapshot = validated_data.get("snapshot")
        progress_percent = validated_data["progress_percent"]
        as_of_date = validated_data["as_of_date"]

        record = RevenueRecognition(
            project=project,
            as_of_date=as_of_date,
            progress_percent=progress_percent,
        )

        snapshot_field = RevenueRecognition._meta.get_field("contract_snapshot")
        if snapshot is not None:
            if isinstance(snapshot_field, models.ForeignKey):
                record.contract_snapshot = snapshot
            else:
                record.contract_snapshot = getattr(snapshot, "id", None)

        record.save()
        return record
