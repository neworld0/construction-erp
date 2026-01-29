from django.conf import settings
from django.db import models


# Placeholder for optional master data models.
# The seed loader discovers CostItem from installed apps.


class FavoriteCostItem(models.Model):
    user = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.CASCADE)
    project = models.ForeignKey(
        "projects.Project",
        on_delete=models.CASCADE,
        null=True,
        blank=True,
    )
    cost_item = models.ForeignKey("cost.CostItem", on_delete=models.CASCADE)
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        constraints = [
            models.UniqueConstraint(
                fields=["user", "project", "cost_item"],
                name="uniq_favorite_costitem",
            )
        ]


class CBSChangeRequestStatus(models.TextChoices):
    DRAFT = "DRAFT", "Draft"
    SUBMITTED = "SUBMITTED", "Submitted"
    APPROVED = "APPROVED", "Approved"
    REJECTED = "REJECTED", "Rejected"
    CANCELED = "CANCELED", "Canceled"


class CBSChangeRequestType(models.TextChoices):
    CREATE = "CREATE", "Create"
    UPDATE = "UPDATE", "Update"
    DEACTIVATE = "DEACTIVATE", "Deactivate"


class CBSChangeRequest(models.Model):
    cost_item = models.ForeignKey(
        "cost.CostItem",
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
    )
    request_type = models.CharField(
        max_length=20,
        choices=CBSChangeRequestType.choices,
        default=CBSChangeRequestType.UPDATE,
    )
    requested_by = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.PROTECT,
        related_name="cbs_change_requests",
    )
    status = models.CharField(
        max_length=20,
        choices=CBSChangeRequestStatus.choices,
        default=CBSChangeRequestStatus.DRAFT,
    )
    proposed = models.JSONField(default=dict)
    reason = models.TextField(blank=True, default="")
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)
    approved_by = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="approved_cbs_change_requests",
    )
    approved_at = models.DateTimeField(null=True, blank=True)
    decision_note = models.TextField(blank=True, default="")


class MasterTemplateCategory(models.TextChoices):
    WBS = "WBS", "WBS"
    BUDGET = "BUDGET", "BUDGET"


class MasterTemplateDomain(models.TextChoices):
    LANDSCAPE = "LANDSCAPE", "LANDSCAPE"
    CIVIL = "CIVIL", "CIVIL"
    BUILDING = "BUILDING", "BUILDING"


class MasterTemplate(models.Model):
    name = models.CharField(max_length=120)
    category = models.CharField(max_length=16, choices=MasterTemplateCategory.choices)
    domain = models.CharField(max_length=16, choices=MasterTemplateDomain.choices)
    version = models.IntegerField()
    is_active = models.BooleanField(default=True)
    created_by = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="created_master_templates",
    )
    note = models.TextField(blank=True, default="")
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        constraints = [
            models.UniqueConstraint(
                fields=["category", "domain", "version"],
                name="uniq_master_template_category_domain_version",
            )
        ]
        indexes = [
            models.Index(fields=["category", "domain", "is_active"]),
        ]

    def __str__(self) -> str:
        return f"{self.domain}-{self.category}-v{self.version} {self.name}"


class MasterWBSTemplateItem(models.Model):
    template = models.ForeignKey(
        MasterTemplate,
        on_delete=models.CASCADE,
        related_name="wbs_items",
    )
    order = models.IntegerField(default=0)
    task_name = models.CharField(max_length=255)
    weight = models.DecimalField(max_digits=5, decimal_places=2, default=0)
    default_offset_start_days = models.IntegerField(null=True, blank=True)
    default_duration_days = models.IntegerField(null=True, blank=True)

    class Meta:
        ordering = ["order", "id"]
        indexes = [
            models.Index(fields=["template", "order"]),
        ]

    def clean(self):
        if self.template and self.template.category != MasterTemplateCategory.WBS:
            raise models.ValidationError("template category must be WBS.")


class MasterBudgetTemplateItem(models.Model):
    template = models.ForeignKey(
        MasterTemplate,
        on_delete=models.CASCADE,
        related_name="budget_items",
    )
    order = models.IntegerField(default=0)
    cost_item = models.ForeignKey(
        "cost.CostItem",
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="master_budget_items",
    )
    cost_item_code_snapshot = models.CharField(max_length=64, blank=True, default="")
    label = models.CharField(max_length=128)
    is_labor = models.BooleanField(default=False)
    default_amount = models.BigIntegerField(null=True, blank=True)

    class Meta:
        ordering = ["order", "id"]
        indexes = [
            models.Index(fields=["template", "order"]),
        ]

    def clean(self):
        if self.template and self.template.category != MasterTemplateCategory.BUDGET:
            raise models.ValidationError("template category must be BUDGET.")
