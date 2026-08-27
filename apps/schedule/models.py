from django.conf import settings
from django.core.exceptions import ValidationError
from django.db import models
from django.db.models import Q


class SchedulePlan(models.Model):
    project = models.ForeignKey("projects.Project", on_delete=models.PROTECT)
    version_no = models.IntegerField(default=1)
    name = models.CharField(max_length=255, default="Baseline")
    is_active = models.BooleanField(default=True)
    created_by = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="created_schedule_plans",
    )
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        constraints = [
            models.UniqueConstraint(
                fields=["project", "version_no"],
                name="uniq_schedule_plan_version",
            ),
            models.UniqueConstraint(
                fields=["project"],
                condition=Q(is_active=True),
                name="uniq_schedule_plan_active",
            ),
        ]

    # Plan 직접 수정은 허용하되, 이후 T6-3에서 "변경요청으로만 버전업"을 강제 예정
    def __str__(self) -> str:
        return f"{self.project} v{self.version_no}"


class ScheduleTask(models.Model):
    plan = models.ForeignKey(SchedulePlan, related_name="tasks", on_delete=models.CASCADE)
    name = models.CharField(max_length=255)
    start_date = models.DateField(null=True, blank=True)
    end_date = models.DateField(null=True, blank=True)
    weight_percent = models.DecimalField(max_digits=6, decimal_places=3, default=0)
    sort_order = models.IntegerField(default=0)
    is_active = models.BooleanField(default=True)

    def __str__(self) -> str:
        return f"{self.plan_id} - {self.name}"


class DailyProgress(models.Model):
    project = models.ForeignKey("projects.Project", on_delete=models.PROTECT)
    plan = models.ForeignKey(SchedulePlan, on_delete=models.PROTECT)
    task = models.ForeignKey(ScheduleTask, on_delete=models.PROTECT)
    report_date = models.DateField()
    progress_percent = models.DecimalField(max_digits=6, decimal_places=3)
    status = models.CharField(
        max_length=20,
        choices=[
                ("draft", "Draft"),
                ("submitted", "Submitted"),
                ("approved", "Approved"),
                ("rejected", "Rejected"),
                ("voided", "Voided"),
            ],
        default="submitted",
    )
    reporter = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.PROTECT)
    approved_by = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="approved_daily_progresses",
    )
    approved_at = models.DateTimeField(null=True, blank=True)
    rejected_by = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="rejected_daily_progresses",
    )
    rejected_at = models.DateTimeField(null=True, blank=True)
    reject_reason = models.TextField(blank=True, default="")
    note = models.TextField(blank=True, default="")
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        constraints = [
            models.UniqueConstraint(
                fields=["project", "task", "report_date", "reporter"],
                name="uniq_daily_progress_reporter",
            ),
        ]

    def clean(self):
        if self.progress_percent is not None:
            if self.progress_percent < 0 or self.progress_percent > 100:
                raise ValidationError({"progress_percent": "progress_percent must be 0~100."})
        if self.plan_id and self.project_id and self.plan.project_id != self.project_id:
            raise ValidationError({"plan": "plan must belong to project."})
        if self.task_id and self.plan_id and self.task.plan_id != self.plan_id:
            raise ValidationError({"task": "task must belong to plan."})

    def save(self, *args, **kwargs):
        if not self.plan_id and self.project_id:
            active_plan = SchedulePlan.objects.filter(
                project_id=self.project_id, is_active=True
            ).first()
            if active_plan is None:
                raise ValidationError("Active plan not found for project.")
            self.plan = active_plan
        # Past entries are allowed; audit log integration will be added later.
        self.clean()
        super().save(*args, **kwargs)

    def __str__(self) -> str:
        return f"{self.project_id} {self.task_id} {self.report_date}"


class ProgressCorrectionType(models.TextChoices):
    CORRECT = "CORRECT", "Correct"
    CANCEL = "CANCEL", "Cancel"


class ProgressCorrectionStatus(models.TextChoices):
    HQ_REVIEW = "HQ_REVIEW", "HQ Review"
    CEO_REVIEW = "CEO_REVIEW", "CEO Review"
    APPROVED = "APPROVED", "Approved"
    REJECTED = "REJECTED", "Rejected"


class ProgressCorrectionRequest(models.Model):
    """Immutable request record for changing an already approved progress row."""

    original_progress = models.ForeignKey(
        DailyProgress, on_delete=models.PROTECT, related_name="correction_requests"
    )
    project = models.ForeignKey("projects.Project", on_delete=models.PROTECT)
    correction_type = models.CharField(max_length=10, choices=ProgressCorrectionType.choices)
    proposed_progress_percent = models.DecimalField(
        max_digits=6, decimal_places=3, null=True, blank=True
    )
    proposed_note = models.TextField(blank=True, default="")
    reason = models.TextField()
    # Snapshots make the pre-correction approved value independently auditable.
    original_report_date = models.DateField()
    original_progress_percent = models.DecimalField(max_digits=6, decimal_places=3)
    original_note = models.TextField(blank=True, default="")
    status = models.CharField(
        max_length=16,
        choices=ProgressCorrectionStatus.choices,
        default=ProgressCorrectionStatus.HQ_REVIEW,
    )
    requested_by = models.ForeignKey(
        settings.AUTH_USER_MODEL, on_delete=models.PROTECT, related_name="requested_progress_corrections"
    )
    hq_reviewed_by = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.PROTECT,
        null=True,
        blank=True,
        related_name="hq_reviewed_progress_corrections",
    )
    hq_review_comment = models.TextField(blank=True, default="")
    hq_reviewed_at = models.DateTimeField(null=True, blank=True)
    approved_by = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.PROTECT,
        null=True,
        blank=True,
        related_name="approved_progress_corrections",
    )
    approved_at = models.DateTimeField(null=True, blank=True)
    rejection_reason = models.TextField(blank=True, default="")
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        indexes = [
            models.Index(fields=["status", "project"]),
            models.Index(fields=["original_progress", "status"]),
        ]
        constraints = [
            models.UniqueConstraint(
                fields=["original_progress"],
                condition=Q(status__in=["HQ_REVIEW", "CEO_REVIEW"]),
                name="uq_active_progress_correction",
            )
        ]

    def clean(self):
        if self.correction_type == ProgressCorrectionType.CORRECT:
            if self.proposed_progress_percent is None:
                raise ValidationError({"proposed_progress_percent": "정정 진행률을 입력해 주세요."})
            if not 0 <= self.proposed_progress_percent <= 100:
                raise ValidationError({"proposed_progress_percent": "진행률은 0~100 사이여야 합니다."})
        elif self.proposed_progress_percent is not None:
            raise ValidationError({"proposed_progress_percent": "취소 요청에는 진행률을 입력할 수 없습니다."})
        return super().clean()


class PlanChangeType(models.TextChoices):
    FIELD_REQUEST = "field_request", "Field Request"
    DESIGN_CHANGE = "design_change", "Design Change"
    CHANGE_ORDER = "change_order", "Change Order"
    FORCE_MAJEURE = "force_majeure", "Force Majeure"


class PlanChangeStatus(models.TextChoices):
    DRAFT = "draft", "Draft"
    SUBMITTED = "submitted", "Submitted"
    APPROVED = "approved", "Approved"
    REJECTED = "rejected", "Rejected"


def _contract_change_field():
    installed_apps = set(getattr(settings, "INSTALLED_APPS", []))
    if "apps.contracts" in installed_apps or "contracts" in installed_apps:
        return models.ForeignKey(
            "contracts.ContractChange",
            on_delete=models.SET_NULL,
            null=True,
            blank=True,
        )
    return models.PositiveIntegerField(null=True, blank=True)


class PlanChangeRequest(models.Model):
    project = models.ForeignKey("projects.Project", on_delete=models.PROTECT)
    base_plan = models.ForeignKey(SchedulePlan, on_delete=models.PROTECT)
    change_type = models.CharField(max_length=30, choices=PlanChangeType.choices)
    reason = models.TextField()
    proposed_payload = models.JSONField()
    status = models.CharField(
        max_length=20,
        choices=PlanChangeStatus.choices,
        default=PlanChangeStatus.DRAFT,
    )
    requested_by = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="requested_plan_changes",
    )
    requested_at = models.DateTimeField(null=True, blank=True)
    approved_by = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="approved_plan_changes",
    )
    approved_at = models.DateTimeField(null=True, blank=True)
    contract_change = _contract_change_field()
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    # DESIGN_CHANGE는 계약변경 필수 아님 (evidence_required 예정)
    def __str__(self) -> str:
        return f"{self.project_id} {self.change_type} {self.status}"
