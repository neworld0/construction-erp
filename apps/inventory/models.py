from django.conf import settings
from django.core.exceptions import ValidationError
from django.db import models
from django.db.models import Q


class WarehouseType(models.TextChoices):
    HQ = "hq", "HQ"
    SITE = "site", "SITE"


class Warehouse(models.Model):
    name = models.CharField(max_length=120)
    code = models.CharField(max_length=50, unique=True)
    warehouse_type = models.CharField(
        max_length=10,
        choices=WarehouseType.choices,
    )
    project = models.ForeignKey(
        "projects.Project",
        on_delete=models.CASCADE,
        null=True,
        blank=True,
        related_name="warehouses",
    )
    is_active = models.BooleanField(default=True)
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        indexes = [
            models.Index(fields=["warehouse_type", "project"]),
        ]
        constraints = [
            models.CheckConstraint(
                check=Q(warehouse_type=WarehouseType.HQ, project__isnull=True)
                | Q(warehouse_type=WarehouseType.SITE, project__isnull=False),
                name="chk_warehouse_type_project",
            ),
        ]

    def __str__(self) -> str:
        return f"{self.code} - {self.name}"

    def clean(self):
        if self.warehouse_type == WarehouseType.HQ and self.project_id is not None:
            raise ValidationError({"project": "HQ warehouse must not have project."})
        if self.warehouse_type == WarehouseType.SITE and self.project_id is None:
            raise ValidationError({"project": "SITE warehouse must have project."})


class Location(models.Model):
    warehouse = models.ForeignKey(
        Warehouse,
        on_delete=models.CASCADE,
        related_name="locations",
    )
    name = models.CharField(max_length=120)
    code = models.CharField(max_length=30)
    is_default = models.BooleanField(default=False)
    is_active = models.BooleanField(default=True)
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        constraints = [
            models.UniqueConstraint(
                fields=["warehouse", "code"], name="uq_location_warehouse_code"
            ),
            models.UniqueConstraint(
                fields=["warehouse"],
                condition=Q(is_default=True),
                name="uq_location_default_per_warehouse",
            ),
        ]
        indexes = [
            models.Index(fields=["warehouse", "is_active"]),
        ]

    def __str__(self) -> str:
        return f"{self.warehouse.code} - {self.code}"


class UoM(models.Model):
    code = models.CharField(max_length=10, unique=True)
    name = models.CharField(max_length=60)
    is_active = models.BooleanField(default=True)
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        indexes = [
            models.Index(fields=["code", "is_active"]),
        ]

    def __str__(self) -> str:
        return f"{self.code} - {self.name}"


class ItemCategory(models.Model):
    name = models.CharField(max_length=80, unique=True)
    code = models.CharField(max_length=10, blank=True, default="")
    parent = models.ForeignKey(
        "self",
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="children",
    )
    sort_order = models.IntegerField(default=0)
    is_active = models.BooleanField(default=True)
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        indexes = [
            models.Index(fields=["name", "is_active"]),
            models.Index(fields=["code"]),
        ]

    def __str__(self) -> str:
        return self.name


class ItemMaster(models.Model):
    code = models.CharField(max_length=30, unique=True, db_index=True)
    name = models.CharField(max_length=120, db_index=True)
    category = models.ForeignKey(
        ItemCategory,
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="items",
    )
    uom = models.ForeignKey(UoM, on_delete=models.PROTECT, related_name="items")
    spec = models.TextField(blank=True, default="")
    description = models.TextField(blank=True, default="")
    is_active = models.BooleanField(default=True)
    barcode = models.CharField(max_length=60, blank=True, default="", db_index=True)
    standard_cost = models.BigIntegerField(null=True, blank=True)
    cost_updated_at = models.DateTimeField(null=True, blank=True)
    created_by = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="created_item_masters",
    )
    updated_by = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="updated_item_masters",
    )
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        indexes = [
            models.Index(fields=["code", "is_active"]),
            models.Index(fields=["name"]),
            models.Index(fields=["barcode"]),
        ]

    def __str__(self) -> str:
        return f"{self.code} - {self.name}"


class ItemCodeSequence(models.Model):
    key = models.CharField(max_length=20, unique=True)
    last_number = models.IntegerField(default=0)
    updated_at = models.DateTimeField(auto_now=True)

    def __str__(self) -> str:
        return f"{self.key}:{self.last_number}"


class InventoryTxType(models.TextChoices):
    RECEIPT = "RECEIPT", "Receipt"
    ISSUE = "ISSUE", "Issue"
    ADJUST = "ADJUST", "Adjust"


class InventoryRefType(models.TextChoices):
    MANUAL = "MANUAL", "Manual"
    TRANSFER = "TRANSFER", "Transfer"
    ISSUE_TO_WORK = "ISSUE_TO_WORK", "Issue to work"
    PURCHASE = "PURCHASE", "Purchase"


class TransferDirection(models.TextChoices):
    HQ_TO_SITE = "HQ_TO_SITE", "HQ_TO_SITE"
    SITE_TO_HQ = "SITE_TO_HQ", "SITE_TO_HQ"


class TransferStatus(models.TextChoices):
    DRAFT = "DRAFT", "DRAFT"
    SUBMITTED = "SUBMITTED", "SUBMITTED"
    ISSUED = "ISSUED", "ISSUED"
    RECEIVED = "RECEIVED", "RECEIVED"
    CANCELLED = "CANCELLED", "CANCELLED"


class TransferNumberSequence(models.Model):
    key = models.CharField(max_length=20, unique=True)
    last_number = models.IntegerField(default=0)
    updated_at = models.DateTimeField(auto_now=True)

    def __str__(self) -> str:
        return f"{self.key}:{self.last_number}"


class IssueStatus(models.TextChoices):
    DRAFT = "DRAFT", "DRAFT"
    SUBMITTED = "SUBMITTED", "SUBMITTED"
    APPROVED = "APPROVED", "APPROVED"
    REJECTED = "REJECTED", "REJECTED"


class IssueNumberSequence(models.Model):
    key = models.CharField(max_length=20, unique=True)
    last_number = models.IntegerField(default=0)
    updated_at = models.DateTimeField(auto_now=True)

    def __str__(self) -> str:
        return f"{self.key}:{self.last_number}"


class Transfer(models.Model):
    transfer_no = models.CharField(max_length=30, unique=True, db_index=True)
    direction = models.CharField(max_length=20, choices=TransferDirection.choices)
    project = models.ForeignKey(
        "projects.Project",
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="transfers",
    )
    from_warehouse = models.ForeignKey(
        Warehouse,
        on_delete=models.PROTECT,
        related_name="transfer_out",
    )
    from_location = models.ForeignKey(
        Location,
        on_delete=models.PROTECT,
        null=True,
        blank=True,
        related_name="transfer_out",
    )
    to_warehouse = models.ForeignKey(
        Warehouse,
        on_delete=models.PROTECT,
        related_name="transfer_in",
    )
    to_location = models.ForeignKey(
        Location,
        on_delete=models.PROTECT,
        null=True,
        blank=True,
        related_name="transfer_in",
    )
    tx_date = models.DateField()
    status = models.CharField(
        max_length=16,
        choices=TransferStatus.choices,
        default=TransferStatus.DRAFT,
    )
    note = models.TextField(blank=True, default="")
    created_by = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.PROTECT,
        related_name="created_transfers",
    )
    submitted_at = models.DateTimeField(null=True, blank=True)
    issued_at = models.DateTimeField(null=True, blank=True)
    received_at = models.DateTimeField(null=True, blank=True)
    cancelled_at = models.DateTimeField(null=True, blank=True)
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        indexes = [
            models.Index(fields=["project", "status"]),
            models.Index(fields=["tx_date", "status"]),
        ]

    def __str__(self) -> str:
        return f"{self.transfer_no} {self.status}"

    def clean(self):
        if self.from_warehouse_id and self.to_warehouse_id:
            if self.from_warehouse_id == self.to_warehouse_id:
                raise ValidationError("from_warehouse and to_warehouse must differ.")
        if self.direction == TransferDirection.HQ_TO_SITE:
            if self.project_id is None:
                raise ValidationError({"project": "Project is required for HQ_TO_SITE."})
            if self.from_warehouse and self.from_warehouse.warehouse_type != WarehouseType.HQ:
                raise ValidationError({"from_warehouse": "from_warehouse must be HQ."})
            if self.to_warehouse and self.to_warehouse.warehouse_type != WarehouseType.SITE:
                raise ValidationError({"to_warehouse": "to_warehouse must be SITE."})
            if self.to_warehouse and self.project_id != self.to_warehouse.project_id:
                raise ValidationError({"to_warehouse": "to_warehouse project mismatch."})
        if self.direction == TransferDirection.SITE_TO_HQ:
            if self.project_id is None:
                raise ValidationError({"project": "Project is required for SITE_TO_HQ."})
            if self.from_warehouse and self.from_warehouse.warehouse_type != WarehouseType.SITE:
                raise ValidationError({"from_warehouse": "from_warehouse must be SITE."})
            if self.to_warehouse and self.to_warehouse.warehouse_type != WarehouseType.HQ:
                raise ValidationError({"to_warehouse": "to_warehouse must be HQ."})
            if self.from_warehouse and self.project_id != self.from_warehouse.project_id:
                raise ValidationError({"from_warehouse": "from_warehouse project mismatch."})


class TransferLine(models.Model):
    transfer = models.ForeignKey(
        Transfer,
        on_delete=models.CASCADE,
        related_name="lines",
    )
    item = models.ForeignKey(
        ItemMaster,
        on_delete=models.PROTECT,
        related_name="transfer_lines",
    )
    uom = models.ForeignKey(UoM, on_delete=models.PROTECT)
    qty = models.DecimalField(max_digits=18, decimal_places=3)
    note = models.CharField(max_length=255, blank=True, default="")

    class Meta:
        constraints = [
            models.UniqueConstraint(
                fields=["transfer", "item"], name="uq_transfer_line_item"
            )
        ]
        indexes = [
            models.Index(fields=["transfer", "item"]),
        ]

    def clean(self):
        if self.qty is None or self.qty <= 0:
            raise ValidationError({"qty": "qty must be greater than zero."})
        if self.item_id and self.uom_id and self.uom_id != self.item.uom_id:
            raise ValidationError({"uom": "UoM must match item default unit."})


class IssueToWork(models.Model):
    issue_no = models.CharField(max_length=30, unique=True, db_index=True)
    project = models.ForeignKey("projects.Project", on_delete=models.PROTECT)
    warehouse = models.ForeignKey(
        Warehouse,
        on_delete=models.PROTECT,
        related_name="issue_to_work",
    )
    location = models.ForeignKey(
        Location,
        on_delete=models.PROTECT,
        null=True,
        blank=True,
        related_name="issue_to_work",
    )
    issue_date = models.DateField()
    status = models.CharField(
        max_length=16,
        choices=IssueStatus.choices,
        default=IssueStatus.DRAFT,
    )
    note = models.TextField(blank=True, default="")
    created_by = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.PROTECT,
        related_name="created_issue_to_work",
    )
    submitted_at = models.DateTimeField(null=True, blank=True)
    approved_at = models.DateTimeField(null=True, blank=True)
    approved_by = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="approved_issue_to_work",
    )
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        indexes = [
            models.Index(fields=["project", "issue_date"]),
            models.Index(fields=["status", "issue_date"]),
        ]

    def __str__(self) -> str:
        return f"{self.issue_no} {self.status}"


class IssueToWorkLine(models.Model):
    issue = models.ForeignKey(
        IssueToWork,
        on_delete=models.CASCADE,
        related_name="lines",
    )
    item = models.ForeignKey(
        ItemMaster,
        on_delete=models.PROTECT,
        related_name="issue_to_work_lines",
    )
    qty = models.DecimalField(max_digits=18, decimal_places=3)
    uom = models.ForeignKey(UoM, on_delete=models.PROTECT)
    cbs = models.ForeignKey(
        "cost.CostItem",
        on_delete=models.PROTECT,
        related_name="issue_to_work_lines",
    )
    unit_cost = models.BigIntegerField(null=True, blank=True)
    amount = models.BigIntegerField(null=True, blank=True)
    memo = models.CharField(max_length=255, blank=True, default="")

    class Meta:
        constraints = [
            models.UniqueConstraint(fields=["issue", "item"], name="uq_issue_line_item"),
        ]
        indexes = [
            models.Index(fields=["issue", "item"]),
        ]

    def clean(self):
        if self.qty is None or self.qty <= 0:
            raise ValidationError({"qty": "qty must be greater than zero."})
        if self.item_id and self.uom_id and self.uom_id != self.item.uom_id:
            raise ValidationError({"uom": "UoM must match item default unit."})


class InventoryLedger(models.Model):
    tx_type = models.CharField(max_length=20, choices=InventoryTxType.choices)
    tx_date = models.DateField()
    warehouse = models.ForeignKey(
        Warehouse,
        on_delete=models.PROTECT,
        related_name="ledger_entries",
    )
    location = models.ForeignKey(
        Location,
        on_delete=models.PROTECT,
        null=True,
        blank=True,
        related_name="ledger_entries",
    )
    item = models.ForeignKey(
        ItemMaster,
        on_delete=models.PROTECT,
        related_name="ledger_entries",
    )
    qty_delta = models.DecimalField(max_digits=18, decimal_places=3)
    uom = models.ForeignKey(UoM, on_delete=models.PROTECT, related_name="ledger_entries")
    unit_cost = models.BigIntegerField(null=True, blank=True)
    amount = models.BigIntegerField(null=True, blank=True)
    ref_type = models.CharField(
        max_length=20, choices=InventoryRefType.choices, default=InventoryRefType.MANUAL
    )
    ref_id = models.BigIntegerField(null=True, blank=True)
    note = models.TextField(blank=True, default="")
    created_by = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.PROTECT,
        related_name="inventory_ledgers",
    )
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        indexes = [
            models.Index(fields=["tx_date", "warehouse"]),
            models.Index(fields=["item", "tx_date"]),
        ]

    def clean(self):
        if not self.qty_delta:
            raise ValidationError({"qty_delta": "qty_delta must not be zero."})
        if self.warehouse and not self.warehouse.is_active:
            raise ValidationError({"warehouse": "Warehouse must be active."})
        if self.item and not self.item.is_active:
            raise ValidationError({"item": "Item must be active."})
        if self.uom_id and self.item_id and self.uom_id != self.item.uom_id:
            raise ValidationError({"uom": "UoM must match item default unit."})


class Stock(models.Model):
    warehouse = models.ForeignKey(
        Warehouse,
        on_delete=models.PROTECT,
        related_name="stocks",
    )
    location = models.ForeignKey(
        Location,
        on_delete=models.PROTECT,
        null=True,
        blank=True,
        related_name="stocks",
    )
    item = models.ForeignKey(
        ItemMaster,
        on_delete=models.PROTECT,
        related_name="stocks",
    )
    qty_on_hand = models.DecimalField(max_digits=18, decimal_places=3, default=0)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        constraints = [
            models.UniqueConstraint(
                fields=["warehouse", "location", "item"],
                name="uq_stock_warehouse_location_item",
            )
        ]
        indexes = [
            models.Index(fields=["warehouse", "item"]),
        ]

    def clean(self):
        if self.qty_on_hand is None:
            raise ValidationError({"qty_on_hand": "qty_on_hand required."})
