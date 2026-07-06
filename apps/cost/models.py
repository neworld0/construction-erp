from decimal import Decimal

from django.conf import settings
from django.db import models
from django.db.models import Q, Sum



class CostItemCategory(models.TextChoices):
    LABOR = "labor", "Labor"
    MATERIAL = "material", "Material"
    EQUIP = "equip", "Equip"
    SUBCON = "subcon", "Subcon"
    OTHER = "other", "Other"


COST_ITEM_CATEGORY_LABELS = {
    CostItemCategory.MATERIAL: "재료비",
    CostItemCategory.LABOR: "노무비",
    CostItemCategory.OTHER: "경비",
    CostItemCategory.SUBCON: "하도급",
    CostItemCategory.EQUIP: "경비",
    "overhead": "경비",
}

COST_ITEM_TYPE_LABELS = {
    "D": "직접비",
    "I": "간접비",
    "L": "노무비",
    "M": "재료비",
    "E": "경비",
    "S": "하도급",
    "O": "기타",
    "G": "일반관리비",
    "P": "이윤",
}

COST_ITEM_WORK_TYPE_LABELS = {
    "07": "토공",
    "08": "포장",
    "09": "교량보수",
    "11": "교통안전",
    "12": "운반/폐기물/장비",
    "99": "공통",
}


class CostItem(models.Model):
    code = models.CharField(max_length=50, unique=True)
    name = models.CharField(max_length=255)
    cost_type = models.CharField(max_length=1, blank=True, default="")
    work_type = models.CharField(max_length=2, blank=True, default="")
    category = models.CharField(max_length=20, choices=CostItemCategory.choices)
    unit = models.CharField(max_length=30, blank=True, default="")
    is_direct = models.BooleanField(default=True)
    is_active = models.BooleanField(default=True)
    sort_order = models.IntegerField(default=0)
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        ordering = ["sort_order", "-created_at"]

    def get_category_label_ko(self) -> str:
        value = str(self.category or "").strip().lower()
        return COST_ITEM_CATEGORY_LABELS.get(value, self.category or "-")

    def get_cost_type_label_ko(self) -> str:
        value = str(self.cost_type or "").strip().upper()
        return COST_ITEM_TYPE_LABELS.get(value, self.cost_type or "-")

    def get_work_type_label_ko(self) -> str:
        value = str(self.work_type or "").strip()
        return COST_ITEM_WORK_TYPE_LABELS.get(value, value or "-")

    def get_cost_type_display_ko(self) -> str:
        value = str(self.cost_type or "").strip().upper()
        label = self.get_cost_type_label_ko()
        if value and label != value:
            return f"{value} - {label}"
        return label

    def get_work_type_display_ko(self) -> str:
        value = str(self.work_type or "").strip()
        label = self.get_work_type_label_ko()
        if value and label != value:
            return f"{value} - {label}"
        return label

    def get_display_name(self) -> str:
        primary = getattr(self, "aliases", None)
        if primary is not None:
            alias = primary.filter(is_primary=True).order_by("-updated_at").first()
            if alias and alias.alias:
                return alias.alias
        return self.name

    def __str__(self) -> str:
        return f"{self.code} - {self.get_display_name()}"


class CostItemAlias(models.Model):
    cost_item = models.ForeignKey(
        CostItem,
        related_name="aliases",
        on_delete=models.CASCADE,
    )
    alias = models.CharField(max_length=120)
    is_primary = models.BooleanField(default=True)
    note = models.TextField(blank=True, default="")
    created_by = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="cost_item_aliases",
    )
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        constraints = [
            models.UniqueConstraint(
                fields=["cost_item"],
                condition=Q(is_primary=True),
                name="uniq_costitem_primary_alias",
            ),
            models.UniqueConstraint(
                fields=["cost_item", "alias"],
                name="uniq_costitem_alias",
            ),
        ]
        ordering = ["-updated_at"]


class CostActualStatus(models.TextChoices):
    DRAFT = "draft", "Draft"
    SUBMITTED = "submitted", "Submitted"
    APPROVED = "approved", "Approved"
    REJECTED = "rejected", "Rejected"
    CLOSED = "closed", "Closed"


class CostActual(models.Model):
    project = models.ForeignKey("projects.Project", on_delete=models.PROTECT)
    report_date = models.DateField()
    source_daily_report = models.OneToOneField(
        "field.DailyReport", on_delete=models.SET_NULL, null=True, blank=True
    )
    status = models.CharField(
        max_length=20,
        choices=CostActualStatus.choices,
        default=CostActualStatus.DRAFT,
    )
    total_amount = models.DecimalField(max_digits=16, decimal_places=2, default=0)
    approved_by = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="approved_cost_actuals",
    )
    approved_at = models.DateTimeField(null=True, blank=True)
    closed_at = models.DateTimeField(null=True, blank=True)
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        ordering = ["-report_date", "-updated_at"]

    def recalculate_total(self):
        total = self.lines.aggregate(total=Sum("amount"))["total"] or Decimal("0")
        self.total_amount = total
        self.save(update_fields=["total_amount"])


class CostActualLine(models.Model):
    cost_actual = models.ForeignKey(CostActual, related_name="lines", on_delete=models.CASCADE)
    cost_item = models.ForeignKey(CostItem, on_delete=models.PROTECT)
    description = models.CharField(max_length=255, blank=True, default="")
    quantity = models.DecimalField(max_digits=14, decimal_places=3, default=0)
    unit_price = models.DecimalField(max_digits=14, decimal_places=2, default=0)
    amount = models.DecimalField(max_digits=16, decimal_places=2, default=0)
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    def save(self, *args, **kwargs):
        quantity = self.quantity or Decimal("0")
        unit_price = self.unit_price or Decimal("0")
        self.amount = quantity * unit_price
        super().save(*args, **kwargs)
        self.cost_actual.recalculate_total()

    def delete(self, *args, **kwargs):
        cost_actual = self.cost_actual
        super().delete(*args, **kwargs)
        cost_actual.recalculate_total()


def _contract_snapshot_field():
    return models.ForeignKey(
        "contracts.ContractSnapshot",
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="revenue_recognitions",
    )


class RevenueRecognition(models.Model):
    project = models.ForeignKey("projects.Project", on_delete=models.PROTECT)
    contract_snapshot = _contract_snapshot_field()
    as_of_date = models.DateField()
    progress_percent = models.DecimalField(max_digits=6, decimal_places=3)
    recognized_revenue = models.DecimalField(max_digits=16, decimal_places=2)
    delta_revenue = models.DecimalField(max_digits=16, decimal_places=2, default=0)
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        constraints = [
            models.UniqueConstraint(
                fields=["project", "contract_snapshot", "as_of_date"],
                name="uniq_revenue_recognition_asof",
            )
        ]
        ordering = ["-as_of_date"]

    def save(self, *args, **kwargs):
        snapshot = self.contract_snapshot
        if snapshot is not None and not hasattr(snapshot, "total_contract_amount"):
            snapshot = None
        if snapshot is None:
            snapshot = _get_active_snapshot(self.project)

        total_amount = Decimal("0")
        if snapshot is not None:
            total_amount = getattr(snapshot, "total_contract_amount", None)
            if total_amount is None:
                total_amount = getattr(snapshot, "total_amount", Decimal("0"))
        progress_ratio = (self.progress_percent or Decimal("0")) / Decimal("100")
        self.recognized_revenue = (total_amount or Decimal("0")) * progress_ratio

        snapshot_field = self._meta.get_field("contract_snapshot")
        filter_kwargs = {"project": self.project, "as_of_date__lt": self.as_of_date}
        if isinstance(snapshot_field, models.ForeignKey):
            filter_kwargs["contract_snapshot_id"] = getattr(self, "contract_snapshot_id", None)
        else:
            filter_kwargs["contract_snapshot"] = self.contract_snapshot

        previous = (
            RevenueRecognition.objects.filter(**filter_kwargs)
            .order_by("-as_of_date")
            .first()
        )
        previous_amount = previous.recognized_revenue if previous else Decimal("0")
        self.delta_revenue = self.recognized_revenue - previous_amount

        super().save(*args, **kwargs)


def _get_active_snapshot(project):
    if project is None:
        return None

    for attr in ("active_contract_snapshot", "contract_snapshot", "current_snapshot"):
        snapshot = getattr(project, attr, None)
        if snapshot:
            return snapshot

    for related_name in ("contract_snapshots", "contractsnapshot_set", "contract_snapshots_set"):
        manager = getattr(project, related_name, None)
        if manager is None:
            continue
        try:
            return manager.filter(is_active=True).first()
        except Exception:
            continue

    return None
