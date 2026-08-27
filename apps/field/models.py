from decimal import Decimal

from django.conf import settings
from django.core.exceptions import ValidationError
from django.db import models
from django.db.models import Q

from apps.cost.models import CostItem
from apps.projects.models import Project


class DailyReportStatus(models.TextChoices):
    DRAFT = "draft", "Draft"
    SUBMITTED = "submitted", "Submitted"
    APPROVED = "approved", "Approved"
    REJECTED = "rejected", "Rejected"


class DailyReport(models.Model):
    project = models.ForeignKey(Project, on_delete=models.PROTECT)
    report_date = models.DateField()
    reporter = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.PROTECT)
    note = models.TextField(blank=True, default="")
    status = models.CharField(
        max_length=20,
        choices=DailyReportStatus.choices,
        default=DailyReportStatus.DRAFT,
    )
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        pass

    def __str__(self) -> str:
        return f"{self.project} - {self.report_date}"


class DailyReportLine(models.Model):
    report = models.ForeignKey(DailyReport, related_name="lines", on_delete=models.CASCADE)
    cost_item = models.ForeignKey(CostItem, on_delete=models.PROTECT)
    description = models.CharField(max_length=255, blank=True, default="")
    quantity = models.DecimalField(max_digits=14, decimal_places=3, default=0)
    unit_price = models.DecimalField(max_digits=14, decimal_places=2, default=0)
    amount = models.DecimalField(max_digits=16, decimal_places=2, default=0)
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    def clean(self):
        if self.quantity is not None and self.quantity < 0:
            raise ValidationError({"quantity": "quantity must be >= 0."})
        if self.unit_price is not None and self.unit_price < 0:
            raise ValidationError({"unit_price": "unit_price must be >= 0."})

    def save(self, *args, **kwargs):
        self.clean()
        quantity = self.quantity or Decimal("0")
        unit_price = self.unit_price or Decimal("0")
        self.amount = quantity * unit_price
        super().save(*args, **kwargs)

    def __str__(self) -> str:
        return f"{self.report_id} - {self.cost_item}"


class RetroactiveEntryRequestType(models.TextChoices):
    PROGRESS = "PROGRESS", "진행률"


class RetroactiveEntryRequestStatus(models.TextChoices):
    PENDING = "PENDING", "승인 대기"
    APPROVED = "APPROVED", "승인됨"
    REJECTED = "REJECTED", "반려됨"
    USED = "USED", "사용 완료"


class RetroactiveEntryRequest(models.Model):
    request_type = models.CharField(
        max_length=20,
        choices=RetroactiveEntryRequestType.choices,
        default=RetroactiveEntryRequestType.PROGRESS,
    )
    project = models.ForeignKey(Project, on_delete=models.PROTECT, related_name="retroactive_entry_requests")
    target_date = models.DateField()
    requested_by = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.PROTECT,
        related_name="retroactive_entry_requests",
    )
    reason = models.TextField()
    status = models.CharField(
        max_length=20,
        choices=RetroactiveEntryRequestStatus.choices,
        default=RetroactiveEntryRequestStatus.PENDING,
    )
    requested_at = models.DateTimeField(auto_now_add=True)
    reviewed_by = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        null=True,
        blank=True,
        on_delete=models.PROTECT,
        related_name="retroactive_entry_requests_reviewed",
    )
    reviewed_at = models.DateTimeField(null=True, blank=True)
    review_comment = models.TextField(blank=True, default="")
    used_at = models.DateTimeField(null=True, blank=True)
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        ordering = ["-requested_at", "-id"]
        indexes = [
            models.Index(fields=["status", "request_type"]),
            models.Index(fields=["requested_by", "project", "target_date"]),
        ]
        constraints = [
            models.UniqueConstraint(
                fields=["requested_by", "project", "target_date", "request_type"],
                condition=Q(status__in=["PENDING", "APPROVED"]),
                name="uq_active_retro_request_scope",
            )
        ]

    def __str__(self) -> str:
        return f"{self.project_id} {self.target_date} {self.request_type} {self.status}"


class SiteDailyLogStatus(models.TextChoices):
    DRAFT = "DRAFT", "임시저장"
    SUBMITTED = "SUBMITTED", "제출"
    APPROVED = "APPROVED", "승인"
    REJECTED = "REJECTED", "반려"


class SiteDailyLog(models.Model):
    """A site narrative and reconciliation reference, never a cost source."""

    project = models.ForeignKey(
        Project, on_delete=models.PROTECT, related_name="site_daily_logs"
    )
    report_date = models.DateField()
    reporter = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.PROTECT,
        related_name="site_daily_logs_reported",
    )
    today_work = models.TextField(blank=True, default="")
    tomorrow_work = models.TextField(blank=True, default="")
    special_notes = models.TextField(blank=True, default="")
    status = models.CharField(
        max_length=12,
        choices=SiteDailyLogStatus.choices,
        default=SiteDailyLogStatus.DRAFT,
    )
    submitted_at = models.DateTimeField(null=True, blank=True)
    approved_by = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        null=True,
        blank=True,
        on_delete=models.PROTECT,
        related_name="site_daily_logs_approved",
    )
    approved_at = models.DateTimeField(null=True, blank=True)
    rejected_by = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        null=True,
        blank=True,
        on_delete=models.PROTECT,
        related_name="site_daily_logs_rejected",
    )
    rejected_at = models.DateTimeField(null=True, blank=True)
    reject_reason = models.TextField(blank=True, default="")
    approval_snapshot = models.JSONField(default=dict, blank=True)
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        ordering = ["-report_date", "-updated_at", "-id"]
        indexes = [models.Index(fields=["project", "report_date", "status"])]
        constraints = [
            models.UniqueConstraint(
                fields=["project", "report_date"], name="uq_site_daily_log_project_date"
            )
        ]

    def __str__(self) -> str:
        return f"{self.project_id} {self.report_date} {self.status}"


class SiteDailyLogWorkLine(models.Model):
    site_daily_log = models.ForeignKey(
        SiteDailyLog, on_delete=models.CASCADE, related_name="work_lines"
    )
    progress_mapping = models.ForeignKey(
        "projects.ProjectWorkProgressMapping", on_delete=models.PROTECT
    )
    uom = models.ForeignKey("inventory.UoM", on_delete=models.PROTECT)
    planned_qty = models.DecimalField(max_digits=18, decimal_places=3, default=0)
    prior_approved_qty = models.DecimalField(max_digits=18, decimal_places=3, default=0)
    today_qty = models.DecimalField(max_digits=18, decimal_places=3, default=0)
    cumulative_qty = models.DecimalField(max_digits=18, decimal_places=3, default=0)
    memo = models.TextField(blank=True, default="")
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        constraints = [
            models.UniqueConstraint(
                fields=["site_daily_log", "progress_mapping"],
                name="uq_site_daily_log_work_line_mapping",
            ),
            models.CheckConstraint(
                condition=Q(today_qty__gte=0),
                name="chk_site_daily_log_work_line_today_qty_nonnegative",
            ),
        ]

    def clean(self):
        errors = {}
        if self.site_daily_log_id and self.progress_mapping_id:
            if self.site_daily_log.project_id != self.progress_mapping.project_id:
                errors["progress_mapping"] = "작업 매핑은 공사일보와 같은 프로젝트에 속해야 합니다."
        if self.uom_id and self.progress_mapping_id and self.uom_id != self.progress_mapping.uom_id:
            errors["uom"] = "작업 단위는 승인된 작업 매핑의 단위와 같아야 합니다."
        if self.today_qty is not None and self.today_qty < 0:
            errors["today_qty"] = "금일수량은 0 이상이어야 합니다."
        if errors:
            raise ValidationError(errors)
        super().clean()


class EquipmentUsageUnit(models.TextChoices):
    UNIT = "UNIT", "대"
    HOUR = "HOUR", "시간"
    DAY = "DAY", "일"
    COUNT = "COUNT", "회"


class EquipmentOwnershipType(models.TextChoices):
    OWNED = "OWNED", "자체"
    RENTED = "RENTED", "임차"


class SiteDailyLogEquipmentLine(models.Model):
    site_daily_log = models.ForeignKey(
        SiteDailyLog, on_delete=models.CASCADE, related_name="equipment_lines"
    )
    cost_actual = models.ForeignKey(
        "cost.CostActual", null=True, blank=True, on_delete=models.PROTECT
    )
    equipment_name = models.CharField(max_length=120)
    specification = models.CharField(max_length=120, blank=True, default="")
    usage_unit = models.CharField(max_length=10, choices=EquipmentUsageUnit.choices)
    ownership_type = models.CharField(
        max_length=10,
        choices=EquipmentOwnershipType.choices,
        default=EquipmentOwnershipType.RENTED,
    )
    today_usage_qty = models.DecimalField(max_digits=18, decimal_places=3, default=0)
    cumulative_usage_qty = models.DecimalField(max_digits=18, decimal_places=3, default=0)
    memo = models.TextField(blank=True, default="")

    class Meta:
        indexes = [models.Index(fields=["site_daily_log", "equipment_name"])]
        constraints = [
            models.CheckConstraint(
                condition=Q(today_usage_qty__gte=0),
                name="chk_site_daily_log_equipment_today_qty_nonnegative",
            )
        ]

    def clean(self):
        if self.cost_actual_id and self.cost_actual.project_id != self.site_daily_log.project_id:
            raise ValidationError({"cost_actual": "연결 원가는 공사일보와 같은 프로젝트에 속해야 합니다."})
        super().clean()


class SiteDailyLogReceiptRef(models.Model):
    site_daily_log = models.ForeignKey(
        SiteDailyLog, on_delete=models.CASCADE, related_name="receipt_refs"
    )
    inventory_ledger = models.ForeignKey("inventory.InventoryLedger", on_delete=models.PROTECT)
    source_type = models.CharField(max_length=30)
    qty_snapshot = models.DecimalField(max_digits=18, decimal_places=3)
    unit_cost_snapshot = models.DecimalField(max_digits=16, decimal_places=2, default=0)
    amount_snapshot = models.DecimalField(max_digits=16, decimal_places=2, default=0)
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        constraints = [
            models.UniqueConstraint(
                fields=["site_daily_log", "inventory_ledger"],
                name="uq_site_daily_log_receipt_ledger",
            )
        ]


class SiteDailyLogEvidence(models.Model):
    site_daily_log = models.ForeignKey(
        SiteDailyLog, on_delete=models.CASCADE, related_name="evidence_links"
    )
    evidence = models.ForeignKey("evidence.Evidence", on_delete=models.PROTECT)
    purpose = models.CharField(max_length=80, blank=True, default="")
    sort_order = models.PositiveIntegerField(default=0)

    class Meta:
        constraints = [
            models.UniqueConstraint(
                fields=["site_daily_log", "evidence"],
                name="uq_site_daily_log_evidence",
            )
        ]


class SiteDailyLogCorrectionStatus(models.TextChoices):
    DRAFT = "DRAFT", "임시저장"
    SUBMITTED = "SUBMITTED", "승인 대기"
    APPROVED = "APPROVED", "승인"
    REJECTED = "REJECTED", "반려"


class SiteDailyLogCorrectionRequest(models.Model):
    site_daily_log = models.ForeignKey(
        SiteDailyLog, on_delete=models.PROTECT, related_name="correction_requests"
    )
    project = models.ForeignKey(Project, on_delete=models.PROTECT)
    requested_by = models.ForeignKey(
        settings.AUTH_USER_MODEL, on_delete=models.PROTECT, related_name="site_daily_log_corrections_requested"
    )
    original_snapshot = models.JSONField(default=dict)
    proposed_payload = models.JSONField(default=dict)
    impact_snapshot = models.JSONField(default=dict)
    reason = models.TextField()
    status = models.CharField(
        max_length=12,
        choices=SiteDailyLogCorrectionStatus.choices,
        default=SiteDailyLogCorrectionStatus.DRAFT,
    )
    submitted_at = models.DateTimeField(null=True, blank=True)
    approved_by = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        null=True,
        blank=True,
        on_delete=models.PROTECT,
        related_name="site_daily_log_corrections_approved",
    )
    approved_at = models.DateTimeField(null=True, blank=True)
    rejected_by = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        null=True,
        blank=True,
        on_delete=models.PROTECT,
        related_name="site_daily_log_corrections_rejected",
    )
    rejected_at = models.DateTimeField(null=True, blank=True)
    rejection_reason = models.TextField(blank=True, default="")
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        indexes = [models.Index(fields=["project", "status"])]
        constraints = [
            models.UniqueConstraint(
                fields=["site_daily_log"],
                condition=Q(status__in=["DRAFT", "SUBMITTED"]),
                name="uq_active_site_daily_log_correction",
            )
        ]

    def clean(self):
        if self.site_daily_log_id and self.project_id and self.site_daily_log.project_id != self.project_id:
            raise ValidationError({"project": "정정 요청은 원본 공사일보와 같은 프로젝트에 속해야 합니다."})
        super().clean()
