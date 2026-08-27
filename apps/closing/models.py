from datetime import date

from django.conf import settings
from django.contrib.contenttypes.fields import GenericForeignKey
from django.contrib.contenttypes.models import ContentType
from django.core.exceptions import ValidationError
from django.db import models
from django.utils import timezone


class ClosingStatus(models.TextChoices):
    OPEN = "OPEN", "Open"
    CLOSED = "CLOSED", "Closed"


class ClosingApprovalPolicy(models.TextChoices):
    HQ_SINGLE = "HQ_SINGLE", "HQ 단독 확정"
    HQ_DUAL = "HQ_DUAL", "HQ 2단계 통제"
    CEO = "CEO", "CEO 예외 승인"


class ClosingPeriod(models.Model):
    legal_entity = models.ForeignKey(
        "core.LegalEntity",
        on_delete=models.PROTECT,
        related_name="closing_periods",
    )
    year = models.IntegerField()
    month = models.IntegerField()
    status = models.CharField(
        max_length=10, choices=ClosingStatus.choices, default=ClosingStatus.OPEN
    )
    approval_policy = models.CharField(
        max_length=16,
        choices=ClosingApprovalPolicy.choices,
        default=ClosingApprovalPolicy.HQ_SINGLE,
        help_text="월 마감 확정 절차입니다. 기존 마감은 CEO 승인 방식으로 보존됩니다.",
    )
    closed_at = models.DateTimeField(null=True, blank=True)
    closed_by = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="closed_periods",
    )
    note = models.TextField(blank=True, default="")
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        constraints = [
            models.UniqueConstraint(
                fields=["legal_entity", "year", "month"], name="uniq_closing_period_entity_year_month"
            )
        ]

    def clean(self) -> None:
        if not (1 <= self.month <= 12):
            raise ValidationError({"month": "month must be between 1 and 12."})
        return super().clean()

    def close(self, actor=None, note=None) -> None:
        if self.status == ClosingStatus.CLOSED:
            raise ValidationError("ClosingPeriod is already closed.")
        self.status = ClosingStatus.CLOSED
        self.closed_at = timezone.now()
        self.closed_by = actor
        if note is not None:
            self.note = note

    def __str__(self) -> str:
        return f"{self.legal_entity.code} {self.year}-{self.month:02d} {self.status}"


class ProjectCloseStatus(models.TextChoices):
    OPEN = "OPEN", "Open"
    CLOSING = "CLOSING", "Closing"
    CLOSED = "CLOSED", "Closed"


class ProjectClose(models.Model):
    project = models.OneToOneField(
        "projects.Project",
        on_delete=models.CASCADE,
        related_name="close",
    )
    status = models.CharField(
        max_length=16,
        choices=ProjectCloseStatus.choices,
        default=ProjectCloseStatus.OPEN,
    )
    close_effective_date = models.DateField(null=True, blank=True)
    closed_at = models.DateTimeField(null=True, blank=True)
    closed_by = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="closed_projects",
    )
    note = models.TextField(blank=True, default="")
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        constraints = [
            models.UniqueConstraint(
                fields=["project"], name="uniq_project_close_project"
            )
        ]

    def __str__(self) -> str:
        return f"{self.project_id} {self.status}"


class AdjustmentTargetType(models.TextChoices):
    COST = "COST", "Cost"
    LABOR = "LABOR", "Labor"
    INVENTORY = "INVENTORY", "Inventory"


class AdjustmentStatus(models.TextChoices):
    DRAFT = "DRAFT", "Draft"
    SUBMITTED = "SUBMITTED", "Submitted"
    APPROVED = "APPROVED", "Approved"
    REJECTED = "REJECTED", "Rejected"


class Adjustment(models.Model):
    target_type = models.CharField(
        max_length=20, choices=AdjustmentTargetType.choices
    )
    target_content_type = models.ForeignKey(
        ContentType, on_delete=models.SET_NULL, null=True, blank=True
    )
    target_object_id = models.PositiveIntegerField(null=True, blank=True)
    target_ref = GenericForeignKey("target_content_type", "target_object_id")
    project = models.ForeignKey(
        "projects.Project", on_delete=models.CASCADE, related_name="adjustments"
    )
    cbs = models.ForeignKey(
        "cost.CostItem",
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="adjustments",
    )
    period_year = models.IntegerField()
    period_month = models.IntegerField()
    amount_delta = models.BigIntegerField()
    reason = models.TextField()
    status = models.CharField(
        max_length=16, choices=AdjustmentStatus.choices, default=AdjustmentStatus.DRAFT
    )
    created_by = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="created_adjustments",
    )
    approved_by = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="approved_adjustments",
    )
    approved_at = models.DateTimeField(null=True, blank=True)
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        indexes = [
            models.Index(fields=["project", "period_year", "period_month"]),
            models.Index(fields=["status", "target_type"]),
        ]

    def clean(self) -> None:
        if not (1 <= self.period_month <= 12):
            raise ValidationError({"period_month": "month must be between 1 and 12."})
        period_closed = ClosingPeriod.objects.filter(
            legal_entity=self.project.legal_entity, year=self.period_year, month=self.period_month, status=ClosingStatus.CLOSED
        ).exists()
        if not period_closed:
            raise ValidationError(
                {"period_month": "마감된 월에만 정정할 수 있습니다."}
            )
        return super().clean()

    @property
    def period_date(self) -> date:
        return date(self.period_year, self.period_month, 1)

    def __str__(self) -> str:
        return f"{self.project_id} {self.target_type} {self.period_year}-{self.period_month:02d}"
