from django.conf import settings
from django.db import models


class CashEventStatus(models.TextChoices):
    PLANNED = "planned", "Planned"
    CONFIRMED = "confirmed", "Confirmed"


class CashEventType(models.TextChoices):
    IN = "in", "In"
    OUT = "out", "Out"


class CashAccount(models.Model):
    name = models.CharField(max_length=255)
    bank_name = models.CharField(max_length=255, blank=True, default="")
    masked_account_no = models.CharField(max_length=100, blank=True, default="")
    is_active = models.BooleanField(default=True)

    def __str__(self) -> str:
        return self.name


class CashEvent(models.Model):
    project = models.ForeignKey("projects.Project", on_delete=models.PROTECT)
    contract_snapshot = models.ForeignKey(
        "contracts.ContractSnapshot",
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="cash_events",
    )
    account = models.ForeignKey(
        CashAccount, on_delete=models.SET_NULL, null=True, blank=True
    )
    event_type = models.CharField(max_length=10, choices=CashEventType.choices)
    status = models.CharField(max_length=20, choices=CashEventStatus.choices)
    amount = models.DecimalField(max_digits=16, decimal_places=2)
    event_date = models.DateField()
    description = models.TextField()
    created_by = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.PROTECT)
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        indexes = [
            models.Index(fields=["project", "event_date"], name="cash_event_project_date_idx"),
            models.Index(fields=["status", "event_date"], name="cash_event_status_date_idx"),
        ]

    def save(self, *args, **kwargs):
        if self.contract_snapshot is None and self.project_id:
            from apps.contracts.services import get_active_contract_snapshot

            self.contract_snapshot = get_active_contract_snapshot(self.project_id)
        super().save(*args, **kwargs)
