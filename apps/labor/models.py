from django.conf import settings
from django.core.exceptions import ValidationError
from django.db import models


class LaborRoleGroup(models.TextChoices):
    FOREMAN = "FOREMAN", "Foreman"
    SKILLED = "SKILLED", "Skilled"
    UNSKILLED = "UNSKILLED", "Unskilled"
    OPERATOR = "OPERATOR", "Operator"
    ENGINEER = "ENGINEER", "Engineer"
    ADMIN = "ADMIN", "Admin"


class LaborRole(models.Model):
    code = models.CharField(max_length=30, unique=True, db_index=True)
    name = models.CharField(max_length=120, db_index=True)
    role_group = models.CharField(
        max_length=20, choices=LaborRoleGroup.choices, blank=True, default=""
    )
    is_active = models.BooleanField(default=True)
    sort_order = models.IntegerField(default=0)
    default_cbs = models.ForeignKey(
        "cost.CostItem",
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="labor_roles",
    )
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        ordering = ["sort_order", "code"]
        indexes = [
            models.Index(fields=["code"]),
            models.Index(fields=["name"]),
            models.Index(fields=["is_active"]),
        ]

    def __str__(self) -> str:
        return f"{self.code} - {self.name}"


class LaborRateType(models.TextChoices):
    DAY = "DAY", "Per day"
    HOUR = "HOUR", "Per hour"


class LaborRateScope(models.TextChoices):
    GLOBAL = "GLOBAL", "Global"
    PROJECT = "PROJECT", "Project"


class LaborRateTable(models.Model):
    labor_role = models.ForeignKey(
        LaborRole, on_delete=models.CASCADE, related_name="rates"
    )
    rate_type = models.CharField(
        max_length=10, choices=LaborRateType.choices, default=LaborRateType.DAY
    )
    unit_rate = models.BigIntegerField()
    currency = models.CharField(max_length=3, default="KRW")
    effective_from = models.DateField()
    effective_to = models.DateField(null=True, blank=True)
    scope_type = models.CharField(
        max_length=10, choices=LaborRateScope.choices, default=LaborRateScope.GLOBAL
    )
    project = models.ForeignKey(
        "projects.Project",
        on_delete=models.CASCADE,
        null=True,
        blank=True,
        related_name="labor_rates",
    )
    is_active = models.BooleanField(default=True)
    note = models.CharField(max_length=255, blank=True)
    created_by = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        null=True,
        blank=True,
        on_delete=models.SET_NULL,
        related_name="labor_rates_created",
    )
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        indexes = [
            models.Index(
                fields=[
                    "labor_role",
                    "scope_type",
                    "project",
                    "effective_from",
                    "effective_to",
                    "is_active",
                ]
            )
        ]
        ordering = ["-effective_from", "labor_role_id"]

    def clean(self) -> None:
        if self.unit_rate is None or self.unit_rate <= 0:
            raise ValidationError({"unit_rate": "unit_rate must be > 0."})
        if self.scope_type == LaborRateScope.GLOBAL and self.project_id is not None:
            raise ValidationError({"project": "project must be empty for GLOBAL rates."})
        if self.scope_type == LaborRateScope.PROJECT and not self.project_id:
            raise ValidationError({"project": "project is required for PROJECT rates."})
        if self.effective_to and self.effective_to < self.effective_from:
            raise ValidationError({"effective_to": "effective_to must be >= effective_from."})

    def __str__(self) -> str:
        scope = self.scope_type
        return f"{self.labor_role.code} {self.rate_type} {scope}"


class TimesheetStatus(models.TextChoices):
    DRAFT = "DRAFT", "Draft"
    SUBMITTED = "SUBMITTED", "Submitted"
    APPROVED = "APPROVED", "Approved"
    REJECTED = "REJECTED", "Rejected"


class TimesheetNumberSequence(models.Model):
    key = models.CharField(max_length=20, unique=True)
    last_number = models.IntegerField(default=0)

    class Meta:
        ordering = ["key"]

    def __str__(self) -> str:
        return f"{self.key}:{self.last_number}"


class Timesheet(models.Model):
    sheet_no = models.CharField(max_length=20, unique=True, db_index=True)
    project = models.ForeignKey(
        "projects.Project", on_delete=models.CASCADE, related_name="timesheets"
    )
    work_date = models.DateField()
    status = models.CharField(
        max_length=12, choices=TimesheetStatus.choices, default=TimesheetStatus.DRAFT
    )
    note = models.TextField(blank=True)
    created_by = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.CASCADE,
        related_name="timesheets_created",
    )
    submitted_at = models.DateTimeField(null=True, blank=True)
    approved_by = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="timesheets_approved",
    )
    approved_at = models.DateTimeField(null=True, blank=True)
    rejected_by = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="timesheets_rejected",
    )
    rejected_at = models.DateTimeField(null=True, blank=True)
    reject_reason = models.TextField(blank=True)
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        ordering = ["-work_date", "-id"]
        indexes = [
            models.Index(fields=["project", "work_date"]),
            models.Index(fields=["status"]),
        ]

    def __str__(self) -> str:
        return self.sheet_no


class TimesheetLine(models.Model):
    timesheet = models.ForeignKey(
        Timesheet, on_delete=models.CASCADE, related_name="lines"
    )
    labor_role = models.ForeignKey(
        LaborRole, on_delete=models.PROTECT, related_name="timesheet_lines"
    )
    headcount = models.DecimalField(max_digits=10, decimal_places=2)
    hours = models.DecimalField(max_digits=10, decimal_places=2, null=True, blank=True)
    rate_type = models.CharField(
        max_length=10, choices=LaborRateType.choices, default=LaborRateType.DAY
    )
    unit_rate = models.BigIntegerField()
    amount = models.BigIntegerField()
    memo = models.CharField(max_length=255, blank=True)

    class Meta:
        ordering = ["id"]
        indexes = [
            models.Index(fields=["timesheet"]),
            models.Index(fields=["labor_role"]),
        ]

    def __str__(self) -> str:
        return f"{self.timesheet.sheet_no} - {self.labor_role.code}"


class PayrollAllocationStatus(models.TextChoices):
    DRAFT = "DRAFT", "Draft"
    SUBMITTED = "SUBMITTED", "Submitted"
    APPROVED = "APPROVED", "Approved"
    REJECTED = "REJECTED", "Rejected"


class PayrollBatchNumberSequence(models.Model):
    key = models.CharField(max_length=20, unique=True)
    last_number = models.IntegerField(default=0)

    class Meta:
        ordering = ["key"]

    def __str__(self) -> str:
        return f"{self.key}:{self.last_number}"


class PayrollAllocationBatch(models.Model):
    batch_no = models.CharField(max_length=20, unique=True, db_index=True)
    period_year = models.IntegerField()
    period_month = models.IntegerField()
    status = models.CharField(
        max_length=12,
        choices=PayrollAllocationStatus.choices,
        default=PayrollAllocationStatus.DRAFT,
    )
    total_amount = models.BigIntegerField()
    note = models.TextField(blank=True)
    created_by = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.CASCADE,
        related_name="payroll_batches_created",
    )
    submitted_at = models.DateTimeField(null=True, blank=True)
    approved_by = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        null=True,
        blank=True,
        on_delete=models.SET_NULL,
        related_name="payroll_batches_approved",
    )
    approved_at = models.DateTimeField(null=True, blank=True)
    rejected_by = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        null=True,
        blank=True,
        on_delete=models.SET_NULL,
        related_name="payroll_batches_rejected",
    )
    rejected_at = models.DateTimeField(null=True, blank=True)
    reject_reason = models.TextField(blank=True)
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        constraints = [
            models.UniqueConstraint(
                fields=["period_year", "period_month"],
                name="uniq_payroll_batch_period",
            )
        ]
        ordering = ["-period_year", "-period_month", "-id"]
        indexes = [
            models.Index(fields=["period_year", "period_month"]),
            models.Index(fields=["status"]),
        ]

    def __str__(self) -> str:
        return self.batch_no


class PayrollAllocationLine(models.Model):
    batch = models.ForeignKey(
        PayrollAllocationBatch, on_delete=models.CASCADE, related_name="lines"
    )
    project = models.ForeignKey(
        "projects.Project",
        on_delete=models.CASCADE,
        related_name="payroll_allocations",
    )
    cbs = models.ForeignKey(
        "cost.CostItem",
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="payroll_allocations",
    )
    amount = models.BigIntegerField()
    memo = models.CharField(max_length=255, blank=True)

    class Meta:
        constraints = [
            models.UniqueConstraint(
                fields=["batch", "project"],
                name="uniq_payroll_batch_project",
            )
        ]
        indexes = [
            models.Index(fields=["batch", "project"]),
        ]

    def __str__(self) -> str:
        return f"{self.batch.batch_no} - {self.project_id}"
