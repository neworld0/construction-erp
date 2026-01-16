from decimal import Decimal

from django.conf import settings
from django.core.exceptions import ValidationError
from django.db import models

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
