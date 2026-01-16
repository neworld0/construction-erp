from django.conf import settings
from django.db import models


class ContractChangeType(models.TextChoices):
    DESIGN_CHANGE = "design_change", "Design Change"
    CHANGE_ORDER = "change_order", "Change Order"


class ContractChangeStatus(models.TextChoices):
    DRAFT = "draft", "Draft"
    SUBMITTED = "submitted", "Submitted"
    APPROVED = "approved", "Approved"
    REJECTED = "rejected", "Rejected"


class ContractChange(models.Model):
    project = models.ForeignKey("projects.Project", on_delete=models.PROTECT)
    change_no = models.IntegerField()
    change_type = models.CharField(max_length=20, choices=ContractChangeType.choices)
    reason = models.TextField()
    contract_amount_delta = models.DecimalField(max_digits=16, decimal_places=2, default=0)
    time_extension_days = models.IntegerField(default=0)
    status = models.CharField(
        max_length=20,
        choices=ContractChangeStatus.choices,
        default=ContractChangeStatus.DRAFT,
    )
    submitted_by = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="submitted_contract_changes",
    )
    submitted_at = models.DateTimeField(null=True, blank=True)
    approved_by = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="approved_contract_changes",
    )
    approved_at = models.DateTimeField(null=True, blank=True)
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        constraints = [
            models.UniqueConstraint(
                fields=["project", "change_no"],
                name="uniq_contract_change_no",
            )
        ]

    def save(self, *args, **kwargs):
        if not self.pk and not self.change_no:
            latest = (
                ContractChange.objects.filter(project=self.project)
                .order_by("-change_no")
                .first()
            )
            self.change_no = (latest.change_no if latest else 0) + 1
        super().save(*args, **kwargs)

    def __str__(self) -> str:
        return f"{self.project_id} #{self.change_no} {self.status}"

    # Evidence(T9-1): DESIGN_CHANGE/CHANGE_ORDER -> evidence_required=True 예정


class ContractSnapshot(models.Model):
    project = models.ForeignKey("projects.Project", on_delete=models.PROTECT)
    version_no = models.IntegerField(default=1)
    base_contract_amount = models.DecimalField(max_digits=16, decimal_places=2)
    start_date = models.DateField(null=True, blank=True)
    end_date = models.DateField(null=True, blank=True)
    is_active = models.BooleanField(default=True)
    source_change = models.ForeignKey(
        ContractChange,
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="snapshots",
    )
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        constraints = [
            models.UniqueConstraint(
                fields=["project", "version_no"], name="uniq_contract_snapshot_version"
            )
        ]
        indexes = [
            models.Index(fields=["project", "is_active"], name="contract_snapshot_active_idx"),
        ]

    @property
    def total_contract_amount(self):
        return self.base_contract_amount

    def __str__(self) -> str:
        return f"{self.project_id} v{self.version_no}"
