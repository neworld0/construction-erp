from django.conf import settings
from django.core.exceptions import ValidationError
from django.db import models


class CashEventStatus(models.TextChoices):
    PLANNED = "planned", "Planned"
    CONFIRMED = "confirmed", "Confirmed"
    CANCELLED = "cancelled", "Cancelled"


class CashEventType(models.TextChoices):
    IN = "in", "In"
    OUT = "out", "Out"


class CashAccount(models.Model):
    legal_entity = models.ForeignKey(
        "core.LegalEntity",
        on_delete=models.PROTECT,
        related_name="cash_accounts",
        help_text="은행 계좌와 현금 계정의 법적 소유 법인입니다.",
    )
    name = models.CharField(max_length=255)
    bank_name = models.CharField(max_length=255, blank=True, default="")
    masked_account_no = models.CharField(max_length=100, blank=True, default="")
    is_active = models.BooleanField(default=True)

    def __str__(self) -> str:
        return f"{self.legal_entity.code} - {self.name}"


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

    def clean(self):
        if self.account_id and self.project_id and self.account.legal_entity_id != self.project.legal_entity_id:
            raise ValidationError({"account": "현금 계정의 소유 법인과 프로젝트 계약 법인이 일치해야 합니다."})

    def save(self, *args, **kwargs):
        if self.contract_snapshot is None and self.project_id:
            from apps.contracts.services import get_active_contract_snapshot

            self.contract_snapshot = get_active_contract_snapshot(self.project_id)
        super().save(*args, **kwargs)


class ProgressBillingStatus(models.TextChoices):
    ISSUED = "ISSUED", "Issued"
    COLLECTED = "COLLECTED", "Collected"


class AdvancePayment(models.Model):
    """Contract advance received from the owner; never counted as revenue."""

    project = models.OneToOneField("projects.Project", on_delete=models.PROTECT, related_name="advance_payment")
    contract_amount_snapshot = models.DecimalField(max_digits=16, decimal_places=2)
    advance_rate_percent = models.DecimalField(max_digits=6, decimal_places=3)
    advance_amount = models.DecimalField(max_digits=16, decimal_places=2)
    received_amount = models.DecimalField(max_digits=16, decimal_places=2)
    received_date = models.DateField()
    cash_event = models.OneToOneField(CashEvent, on_delete=models.PROTECT, related_name="advance_payment", null=True, blank=True)
    memo = models.TextField(blank=True, default="")
    created_by = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.PROTECT, related_name="created_advance_payments")
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        constraints = [
            models.CheckConstraint(condition=models.Q(advance_rate_percent__gte=0, advance_rate_percent__lte=100), name="advance_payment_rate_range"),
        ]


class ProgressBilling(models.Model):
    """Immutable progress-billing claim: gross earned amount, advance recovery, and net receivable."""

    project = models.ForeignKey("projects.Project", on_delete=models.PROTECT, related_name="progress_billings")
    billing_date = models.DateField()
    contract_amount_snapshot = models.DecimalField(max_digits=16, decimal_places=2)
    approved_progress_percent = models.DecimalField(max_digits=6, decimal_places=3)
    cumulative_earned_amount = models.DecimalField(max_digits=16, decimal_places=2)
    previously_billed_amount = models.DecimalField(max_digits=16, decimal_places=2, default=0)
    gross_claim_amount = models.DecimalField(max_digits=16, decimal_places=2)
    cumulative_advance_deduction = models.DecimalField(max_digits=16, decimal_places=2, default=0)
    advance_deduction_amount = models.DecimalField(max_digits=16, decimal_places=2, default=0)
    net_claim_amount = models.DecimalField(max_digits=16, decimal_places=2)
    advance_balance_after = models.DecimalField(max_digits=16, decimal_places=2, default=0)
    status = models.CharField(max_length=16, choices=ProgressBillingStatus.choices, default=ProgressBillingStatus.ISSUED)
    cash_event = models.OneToOneField(CashEvent, on_delete=models.PROTECT, related_name="progress_billing", null=True, blank=True)
    memo = models.TextField(blank=True, default="")
    issued_by = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.PROTECT, related_name="issued_progress_billings")
    issued_at = models.DateTimeField(auto_now_add=True)
    collected_by = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.SET_NULL, null=True, blank=True, related_name="collected_progress_billings")
    collected_at = models.DateTimeField(null=True, blank=True)

    class Meta:
        constraints = [
            models.UniqueConstraint(fields=["project", "billing_date"], name="uniq_progress_billing_date"),
        ]
        ordering = ["-billing_date", "-id"]


class BillingReportType(models.TextChoices):
    PROGRESS = "PROGRESS", "Progress billing"
    COMPLETION = "COMPLETION", "Completion billing"


class BillingReportStatus(models.TextChoices):
    DRAFT = "DRAFT", "Draft"
    ENGINEER_INPUT_REQUIRED = "ENGINEER_INPUT_REQUIRED", "Engineer input required"
    HQ_APPROVED = "HQ_APPROVED", "HQ approved"
    CEO_REVIEW = "CEO_REVIEW", "CEO review required"
    REJECTED = "REJECTED", "CEO rejected"
    LOCKED = "LOCKED", "Locked"


class OwnerConfirmationStatus(models.TextChoices):
    PENDING = "PENDING", "발주처 확정 통보 대기"
    CONFIRMED = "CONFIRMED", "발주처 확정 통보 수령"


class TaxInvoiceStatus(models.TextChoices):
    ISSUED = "ISSUED", "발행"
    CANCELLED = "CANCELLED", "취소"


class BillingReport(models.Model):
    """Read-only calculation snapshot plus engineer-authored report content."""

    project = models.ForeignKey("projects.Project", on_delete=models.PROTECT, related_name="billing_reports")
    report_type = models.CharField(max_length=16, choices=BillingReportType.choices)
    billing_round = models.PositiveIntegerField(default=1)
    billing_date = models.DateField()
    approved_progress_percent = models.DecimalField(max_digits=6, decimal_places=3)
    contract_amount_snapshot = models.DecimalField(max_digits=16, decimal_places=2)
    previous_billing_amount = models.DecimalField(max_digits=16, decimal_places=2, default=0)
    current_gross_billing_amount = models.DecimalField(max_digits=16, decimal_places=2)
    cumulative_billing_amount = models.DecimalField(max_digits=16, decimal_places=2)
    remaining_billing_amount = models.DecimalField(max_digits=16, decimal_places=2)
    advance_received_amount = models.DecimalField(max_digits=16, decimal_places=2, default=0)
    previous_advance_deduction = models.DecimalField(max_digits=16, decimal_places=2, default=0)
    current_advance_deduction = models.DecimalField(max_digits=16, decimal_places=2, default=0)
    remaining_advance_balance = models.DecimalField(max_digits=16, decimal_places=2, default=0)
    net_claim_amount = models.DecimalField(max_digits=16, decimal_places=2)
    status = models.CharField(max_length=32, choices=BillingReportStatus.choices, default=BillingReportStatus.DRAFT)
    engineer_notes = models.JSONField(default=dict, blank=True)
    attachment_checklist = models.JSONField(default=dict, blank=True)
    generated_by = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.PROTECT, related_name="generated_billing_reports")
    generated_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)
    hq_reviewed_by = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.SET_NULL, null=True, blank=True, related_name="hq_reviewed_billing_reports")
    hq_reviewed_at = models.DateTimeField(null=True, blank=True)
    ceo_approved_by = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.SET_NULL, null=True, blank=True, related_name="ceo_approved_billing_reports")
    ceo_approved_at = models.DateTimeField(null=True, blank=True)
    ceo_rejected_by = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.SET_NULL, null=True, blank=True, related_name="ceo_rejected_billing_reports")
    ceo_rejected_at = models.DateTimeField(null=True, blank=True)
    reject_reason = models.TextField(blank=True, default="")
    locked_at = models.DateTimeField(null=True, blank=True)
    owner_confirmation_status = models.CharField(
        max_length=16,
        choices=OwnerConfirmationStatus.choices,
        default=OwnerConfirmationStatus.PENDING,
    )
    owner_confirmation_date = models.DateField(null=True, blank=True)
    owner_confirmation_reference = models.CharField(max_length=120, blank=True, default="")
    owner_confirmation_note = models.TextField(blank=True, default="")
    owner_confirmed_by = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="owner_confirmed_billing_reports",
    )
    owner_confirmed_at = models.DateTimeField(null=True, blank=True)

    class Meta:
        constraints = [
            models.UniqueConstraint(fields=["project", "report_type", "billing_round"], name="uniq_billing_report_round"),
        ]
        ordering = ["-billing_date", "-id"]


class TaxInvoice(models.Model):
    """Tax invoice issued only after the owner confirms a billing report."""

    billing_report = models.OneToOneField(
        BillingReport,
        on_delete=models.PROTECT,
        related_name="tax_invoice",
    )
    invoice_number = models.CharField(max_length=120, unique=True)
    supply_date = models.DateField()
    supply_amount = models.DecimalField(max_digits=16, decimal_places=2)
    tax_amount = models.DecimalField(max_digits=16, decimal_places=2)
    status = models.CharField(
        max_length=16,
        choices=TaxInvoiceStatus.choices,
        default=TaxInvoiceStatus.ISSUED,
    )
    issued_by = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.PROTECT,
        related_name="issued_tax_invoices",
    )
    issued_at = models.DateTimeField(auto_now_add=True)
    memo = models.TextField(blank=True, default="")

    class Meta:
        ordering = ["-supply_date", "-id"]



class ExpenseExecutionStatus(models.TextChoices):
    READY = "READY", "CEO 승인 완료"
    SCHEDULED = "SCHEDULED", "지급 예정"
    PAID = "PAID", "지급 완료"
    CANCELLED = "CANCELLED", "집행 취소"


class ExpenseExecution(models.Model):
    """HQ payment execution record created from a CEO-approved cost request."""

    cost_actual = models.OneToOneField(
        "cost.CostActual", on_delete=models.PROTECT, related_name="expense_execution"
    )
    amount_snapshot = models.DecimalField(max_digits=16, decimal_places=2)
    status = models.CharField(
        max_length=16, choices=ExpenseExecutionStatus.choices,
        default=ExpenseExecutionStatus.READY, db_index=True,
    )
    cash_event = models.OneToOneField(
        CashEvent, on_delete=models.PROTECT, related_name="expense_execution",
        null=True, blank=True,
    )
    ceo_approved_by = models.ForeignKey(
        settings.AUTH_USER_MODEL, on_delete=models.SET_NULL, null=True, blank=True,
        related_name="ceo_approved_expense_executions",
    )
    ceo_approved_at = models.DateTimeField(null=True, blank=True)
    scheduled_date = models.DateField(null=True, blank=True)
    scheduled_by = models.ForeignKey(
        settings.AUTH_USER_MODEL, on_delete=models.SET_NULL, null=True, blank=True,
        related_name="scheduled_expense_executions",
    )
    paid_date = models.DateField(null=True, blank=True)
    paid_by = models.ForeignKey(
        settings.AUTH_USER_MODEL, on_delete=models.SET_NULL, null=True, blank=True,
        related_name="paid_expense_executions",
    )
    payment_reference = models.CharField(max_length=120, blank=True, default="")
    memo = models.TextField(blank=True, default="")
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        ordering = ["-created_at", "-id"]
