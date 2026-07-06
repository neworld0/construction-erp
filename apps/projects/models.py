from django.conf import settings
from django.core.exceptions import ValidationError
from django.db import models


class ProjectStatus(models.TextChoices):
    DRAFT = "draft", "Draft"
    SUBMITTED = "submitted", "Submitted"
    APPROVED = "approved", "Approved"
    PLANNED = "planned", "Planned"
    ACTIVE = "active", "Active"
    CLOSED = "closed", "Closed"


class ProjectType(models.TextChoices):
    LANDSCAPE = "landscape", "Landscape"
    CIVIL = "civil", "Civil"
    ARCH = "arch", "Arch"


class BudgetCategory(models.TextChoices):
    MATERIAL = "MATERIAL", "Material"
    SUBCON = "SUBCON", "Subcon"
    EQUIP = "EQUIP", "Equip"
    LABOR = "LABOR", "Labor"
    OVERHEAD = "OVERHEAD", "Overhead"
    OTHER = "OTHER", "Other"


class ProjectContractStatus(models.TextChoices):
    DRAFT = "draft", "DRAFT"
    SUBMITTED = "submitted", "SUBMITTED"
    APPROVED = "approved", "APPROVED"


class Project(models.Model):
    code = models.CharField(max_length=50, unique=True)
    name = models.CharField(max_length=255)
    client_name = models.CharField(max_length=255, blank=True, default="")
    site_address = models.CharField(max_length=255, blank=True, default="")
    project_type = models.CharField(
        max_length=20,
        choices=ProjectType.choices,
        default=ProjectType.LANDSCAPE,
    )
    wbs_template = models.ForeignKey(
        "master.MasterTemplate",
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="projects_wbs",
        limit_choices_to={"category": "WBS"},
    )
    budget_template = models.ForeignKey(
        "master.MasterTemplate",
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="projects_budget",
        limit_choices_to={"category": "BUDGET"},
    )
    contract_amount = models.DecimalField(max_digits=14, decimal_places=2, default=0)
    start_date = models.DateField(null=True, blank=True)
    end_date = models.DateField(null=True, blank=True)
    status = models.CharField(
        max_length=20,
        choices=ProjectStatus.choices,
        default=ProjectStatus.PLANNED,
    )
    is_active = models.BooleanField(default=True)
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        ordering = ["-created_at"]

    def __str__(self) -> str:
        return f"{self.code} - {self.name}"


class BudgetItem(models.Model):
    project = models.ForeignKey(
        Project,
        on_delete=models.CASCADE,
        related_name="budget_items",
    )
    cost_item = models.ForeignKey(
        "cost.CostItem",
        on_delete=models.PROTECT,
        related_name="budget_items",
    )
    category = models.CharField(
        max_length=20,
        choices=BudgetCategory.choices,
        default=BudgetCategory.OTHER,
    )
    name = models.CharField(max_length=120, blank=True, default="")
    planned_amount = models.BigIntegerField(default=0)
    status = models.CharField(
        max_length=16,
        choices=ProjectContractStatus.choices,
        default=ProjectContractStatus.DRAFT,
    )
    note = models.TextField(blank=True, default="")
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        indexes = [
            models.Index(fields=["project", "cost_item"]),
        ]
        # SOURCE_ROW_BUCKET import allows multiple budget rows under the same CBS.
        # Consider source-key based uniqueness later if we need stronger deduplication.

    def __str__(self) -> str:
        label = self.name or self.cost_item.get_display_name()
        return f"{self.project} - {label}"

    def clean(self):
        if self.planned_amount is not None and self.planned_amount < 0:
            raise ValidationError({"planned_amount": "planned_amount must be >= 0."})


class WBSItem(models.Model):
    project = models.ForeignKey(Project, on_delete=models.CASCADE)
    name = models.CharField(max_length=255)
    parent = models.ForeignKey(
        "self",
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
    )
    weight = models.DecimalField(max_digits=6, decimal_places=2, default=0)
    sort_order = models.IntegerField(default=0)
    plan_start_date = models.DateField(null=True, blank=True)
    plan_end_date = models.DateField(null=True, blank=True)
    baseline_version = models.IntegerField(default=1)
    is_baseline = models.BooleanField(default=True)

    class Meta:
        ordering = ["sort_order", "id"]
        indexes = [
            models.Index(fields=["project", "sort_order"]),
        ]

    def __str__(self) -> str:
        return f"{self.project} - {self.name}"


class WBSChangeRequestStatus(models.TextChoices):
    DRAFT = "draft", "DRAFT"
    SUBMITTED = "submitted", "SUBMITTED"
    APPROVED = "approved", "APPROVED"
    REJECTED = "rejected", "REJECTED"
    CANCELED = "canceled", "CANCELED"


class WBSChangeRequestType(models.TextChoices):
    DESIGN_CONTRACT_CHANGE = "design_contract_change", "DESIGN_CONTRACT_CHANGE"
    SCHEDULE_ADJUSTMENT = "schedule_adjustment", "SCHEDULE_ADJUSTMENT"


class WBSChangeRequest(models.Model):
    project = models.ForeignKey(Project, on_delete=models.CASCADE)
    requested_by = models.ForeignKey("auth.User", on_delete=models.PROTECT)
    role_snapshot = models.CharField(max_length=50, blank=True, default="")
    request_type = models.CharField(
        max_length=32,
        choices=WBSChangeRequestType.choices,
        default=WBSChangeRequestType.SCHEDULE_ADJUSTMENT,
    )
    reason = models.TextField(blank=True, default="")
    status = models.CharField(
        max_length=16,
        choices=WBSChangeRequestStatus.choices,
        default=WBSChangeRequestStatus.DRAFT,
    )
    base_version = models.IntegerField(default=1)
    proposed_version = models.IntegerField(null=True, blank=True)
    change_order = models.ForeignKey(
        "contracts.ContractChange",
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
    )
    approved_by = models.ForeignKey(
        "auth.User",
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="approved_wbs_changes",
    )
    approved_at = models.DateTimeField(null=True, blank=True)
    decision_note = models.TextField(blank=True, default="")
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        ordering = ["-created_at"]

    def __str__(self) -> str:
        return f"{self.project_id} {self.request_type} {self.status}"


class WBSChangeLine(models.Model):
    request = models.ForeignKey(
        WBSChangeRequest,
        on_delete=models.CASCADE,
        related_name="lines",
    )
    order = models.IntegerField(default=0)
    task_name = models.CharField(max_length=255)
    weight = models.DecimalField(max_digits=6, decimal_places=2, default=0)
    planned_start = models.DateField(null=True, blank=True)
    planned_end = models.DateField(null=True, blank=True)
    note = models.TextField(blank=True, default="")

    class Meta:
        ordering = ["order", "id"]
        indexes = [
            models.Index(fields=["request", "order"]),
        ]

    def __str__(self) -> str:
        return f"{self.request_id} {self.task_name}"


class ApprovalPackageStatus(models.TextChoices):
    DRAFT = "draft", "DRAFT"
    SUBMITTED = "submitted", "SUBMITTED"
    APPROVED = "approved", "APPROVED"
    REJECTED = "rejected", "REJECTED"
    CANCELED = "canceled", "CANCELED"


class ApprovalPackageItemType(models.TextChoices):
    CHANGE_ORDER = "change_order", "CHANGE_ORDER"
    WBS_CHANGE = "wbs_change", "WBS_CHANGE"
    BUDGET_CHANGE = "budget_change", "BUDGET_CHANGE"
    CONTRACT_CHANGE = "contract_change", "CONTRACT_CHANGE"


class ApprovalPackage(models.Model):
    project = models.ForeignKey(Project, on_delete=models.CASCADE)
    title = models.CharField(max_length=200)
    reason = models.TextField(blank=True, default="")
    created_by = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.PROTECT,
        related_name="approval_packages_created",
    )
    status = models.CharField(
        max_length=16,
        choices=ApprovalPackageStatus.choices,
        default=ApprovalPackageStatus.DRAFT,
    )
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)
    submitted_at = models.DateTimeField(null=True, blank=True)
    decided_at = models.DateTimeField(null=True, blank=True)
    decided_by = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="approval_packages_decided",
    )
    decision_note = models.TextField(blank=True, default="")

    class Meta:
        ordering = ["-created_at"]

    def __str__(self) -> str:
        return f"{self.project_id} {self.title} {self.status}"


class ApprovalPackageItem(models.Model):
    package = models.ForeignKey(
        ApprovalPackage,
        on_delete=models.CASCADE,
        related_name="items",
    )
    item_type = models.CharField(
        max_length=32,
        choices=ApprovalPackageItemType.choices,
    )
    object_id = models.IntegerField()
    status_snapshot = models.CharField(max_length=32, blank=True, default="")
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        constraints = [
            models.UniqueConstraint(
                fields=["package", "item_type", "object_id"],
                name="uq_approval_package_item",
            )
        ]
        indexes = [
            models.Index(fields=["package", "item_type"]),
        ]

    def __str__(self) -> str:
        return f"{self.package_id} {self.item_type} {self.object_id}"


class ProjectContract(models.Model):
    project = models.OneToOneField(
        Project,
        on_delete=models.CASCADE,
        related_name="contract",
    )
    contract_amount = models.DecimalField(max_digits=16, decimal_places=2, default=0)
    contract_start_date = models.DateField(null=True, blank=True)
    contract_end_date = models.DateField(null=True, blank=True)
    contract_file = models.FileField(upload_to="project_contracts/", blank=True)
    memo = models.TextField(blank=True, default="")
    start_date = models.DateField(null=True, blank=True)
    end_date = models.DateField(null=True, blank=True)
    signed_date = models.DateField(null=True, blank=True)
    currency = models.CharField(max_length=3, default="KRW")
    status = models.CharField(
        max_length=16,
        choices=ProjectContractStatus.choices,
        default=ProjectContractStatus.DRAFT,
    )
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    def clean(self):
        if self.contract_amount is not None and self.contract_amount < 0:
            raise ValidationError({"contract_amount": "contract_amount must be >= 0."})
        start_date = self.start_date or self.contract_start_date
        end_date = self.end_date or self.contract_end_date
        if start_date and end_date and start_date > end_date:
            raise ValidationError({"end_date": "end_date must be after start_date."})
