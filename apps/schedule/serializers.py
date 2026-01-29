from datetime import date

from rest_framework import serializers

from apps.closing.guards import guard_write

from .models import (
    DailyProgress,
    PlanChangeRequest,
    PlanChangeStatus,
    PlanChangeType,
    SchedulePlan,
    ScheduleTask,
)


class DailyProgressSerializer(serializers.ModelSerializer):
    class Meta:
        model = DailyProgress
        fields = [
            "id",
            "project",
            "plan",
            "task",
            "report_date",
            "progress_percent",
            "reporter",
            "note",
            "created_at",
            "updated_at",
        ]
        read_only_fields = ["id", "plan", "created_at", "updated_at"]

    def validate_progress_percent(self, value):
        if value < 0 or value > 100:
            raise serializers.ValidationError("progress_percent must be 0~100.")
        return value

    def validate_report_date(self, value):
        return value

    def validate(self, attrs):
        project = attrs.get("project")
        task = attrs.get("task")
        report_date = attrs.get("report_date")
        if project and report_date:
            guard_write(
                project=project,
                target_date=report_date,
                message_context="??? ??????.",
                exc=serializers.ValidationError,
            )

        if task and project and task.plan.project_id != project.id:
            raise serializers.ValidationError({"task": "task must belong to project plan."})

        return attrs

    def create(self, validated_data):
        project = validated_data.get("project")
        if project:
            plan = SchedulePlan.objects.filter(project=project, is_active=True).first()
            if plan is None:
                raise serializers.ValidationError({"project": "active plan not found."})
            validated_data["plan"] = plan
            task = validated_data.get("task")
            if task and task.plan_id != plan.id:
                raise serializers.ValidationError({"task": "task must belong to active plan."})
        return super().create(validated_data)


class PlanChangeRequestSerializer(serializers.ModelSerializer):
    class Meta:
        model = PlanChangeRequest
        fields = [
            "id",
            "project",
            "base_plan",
            "change_type",
            "reason",
            "proposed_payload",
            "status",
            "requested_by",
            "requested_at",
            "approved_by",
            "approved_at",
            "contract_change",
            "created_at",
            "updated_at",
        ]
        read_only_fields = [
            "id",
            "status",
            "requested_by",
            "requested_at",
            "approved_by",
            "approved_at",
            "created_at",
            "updated_at",
        ]

    def validate(self, attrs):
        project = attrs.get("project")
        base_plan = attrs.get("base_plan")
        if project and base_plan and base_plan.project_id != project.id:
            raise serializers.ValidationError({"base_plan": "base_plan must belong to project."})
        if base_plan and not base_plan.is_active:
            raise serializers.ValidationError({"base_plan": "base_plan must be active."})
        return attrs
