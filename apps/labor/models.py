import base64
import hashlib
from datetime import date
from decimal import Decimal, ROUND_DOWN, ROUND_HALF_UP

from django.conf import settings
from django.core.exceptions import ValidationError
from django.db import models

from apps.core.rbac.models import default_asan_legal_entity_id


_SENSITIVE_PREFIX = "enc1:"


def _normalize_identity_value(raw_value: str) -> str:
    return "".join(ch for ch in str(raw_value or "") if ch.isalnum()).upper()


def _mask_rrn_value(raw_value: str) -> str:
    normalized = _normalize_identity_value(raw_value)
    if len(normalized) >= 7:
        return f"{normalized[:6]}-{normalized[6]}******"
    if not normalized:
        return ""
    return f"{normalized[:1]}***"


def _mask_account_number_value(raw_value: str) -> str:
    value = str(raw_value or "").strip()
    if not value:
        return ""
    visible = value[-4:] if len(value) > 4 else value
    return f"***{visible}"


def _looks_encrypted(value: str) -> bool:
    return str(value or "").startswith(_SENSITIVE_PREFIX)


def _sensitive_secret(purpose: str) -> bytes:
    seed = f"{settings.SECRET_KEY}:worker-master:{purpose}"
    return hashlib.sha256(seed.encode("utf-8")).digest()


def _xor_bytes(data: bytes, purpose: str) -> bytes:
    seed = _sensitive_secret(purpose)
    stream = bytearray()
    counter = 0
    while len(stream) < len(data):
        stream.extend(hashlib.sha256(seed + counter.to_bytes(4, "big")).digest())
        counter += 1
    return bytes(item ^ stream[idx] for idx, item in enumerate(data))


def _protect_sensitive_value(raw_value: str, purpose: str) -> str:
    value = str(raw_value or "").strip()
    if not value:
        return ""
    payload = _xor_bytes(value.encode("utf-8"), purpose)
    encoded = base64.urlsafe_b64encode(payload).decode("ascii")
    return f"{_SENSITIVE_PREFIX}{encoded}"


def _unprotect_sensitive_value(value: str, purpose: str) -> str:
    current = str(value or "").strip()
    if not current:
        return ""
    if not _looks_encrypted(current):
        return current
    encoded = current[len(_SENSITIVE_PREFIX) :]
    try:
        payload = base64.urlsafe_b64decode(encoded.encode("ascii"))
        return _xor_bytes(payload, purpose).decode("utf-8")
    except Exception:
        return ""


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
    worker = models.ForeignKey(
        "labor.WorkerMaster",
        on_delete=models.SET_NULL,
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


class WorkerMaster(models.Model):
    name = models.CharField(max_length=120, db_index=True)
    rrn_encrypted = models.CharField(max_length=255, blank=True, default="")
    rrn_masked = models.CharField(max_length=32, blank=True, default="", db_index=True)
    identity_hash = models.CharField(max_length=64, blank=True, default="", db_index=True)
    phone = models.CharField(max_length=40, blank=True, default="")
    address = models.TextField(blank=True, default="")
    bank_name = models.CharField(max_length=120, blank=True, default="")
    bank_code = models.CharField(max_length=30, blank=True, default="")
    account_number_encrypted = models.CharField(max_length=255, blank=True, default="")
    account_holder = models.CharField(max_length=120, blank=True, default="")
    nationality_code = models.CharField(max_length=10, blank=True, default="")
    visa_code = models.CharField(max_length=20, blank=True, default="")
    comwel_job_code = models.CharField(max_length=30, blank=True, default="")
    cwma_job_name = models.CharField(max_length=120, blank=True, default="")
    default_labor_role = models.ForeignKey(
        "labor.LaborRole",
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="worker_masters",
    )
    retirement_deduction_eligible = models.BooleanField(default=True)
    active = models.BooleanField(default=True)
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        ordering = ["name", "id"]
        indexes = [
            models.Index(fields=["name"]),
            models.Index(fields=["active"]),
            models.Index(fields=["identity_hash"]),
        ]

    @staticmethod
    def mask_rrn(raw_value: str) -> str:
        return _mask_rrn_value(raw_value)

    @staticmethod
    def make_identity_hash(raw_value: str) -> str:
        normalized = _normalize_identity_value(raw_value)
        if not normalized:
            return ""
        secret = f"{settings.SECRET_KEY}:{normalized}:worker-master:identity"
        return hashlib.sha256(secret.encode("utf-8")).hexdigest()

    def set_rrn(self, raw_value: str) -> None:
        raw = str(raw_value or "").strip()
        if not raw:
            self.rrn_encrypted = ""
            self.rrn_masked = ""
            self.identity_hash = ""
            return
        self.rrn_masked = self.mask_rrn(raw)
        self.identity_hash = self.make_identity_hash(raw)
        self.rrn_encrypted = _protect_sensitive_value(raw, "rrn")

    def set_account_number(self, raw_value: str) -> None:
        raw = str(raw_value or "").strip()
        if not raw:
            self.account_number_encrypted = ""
            return
        self.account_number_encrypted = _protect_sensitive_value(raw, "account")

    def get_rrn_raw(self) -> str:
        return _unprotect_sensitive_value(self.rrn_encrypted, "rrn")

    def get_account_number_raw(self) -> str:
        return _unprotect_sensitive_value(self.account_number_encrypted, "account")

    @property
    def account_number_masked(self) -> str:
        return _mask_account_number_value(self.get_account_number_raw())

    def save(self, *args, **kwargs):
        rrn_value = str(self.rrn_encrypted or "").strip()
        if rrn_value:
            if _looks_encrypted(rrn_value):
                raw_rrn = self.get_rrn_raw()
                if raw_rrn:
                    if not self.rrn_masked:
                        self.rrn_masked = self.mask_rrn(raw_rrn)
                    if not self.identity_hash:
                        self.identity_hash = self.make_identity_hash(raw_rrn)
            else:
                self.set_rrn(rrn_value)
        else:
            self.rrn_masked = ""
            self.identity_hash = ""

        account_value = str(self.account_number_encrypted or "").strip()
        if account_value:
            if not _looks_encrypted(account_value):
                self.set_account_number(account_value)
        else:
            self.account_number_encrypted = ""

        return super().save(*args, **kwargs)

    def __str__(self) -> str:
        return self.name


class LaborWorkLedgerSource(models.TextChoices):
    MANUAL = "MANUAL", "Manual"
    TIMESHEET = "TIMESHEET", "Timesheet"
    COST = "COST", "Cost"


class LaborWorkLedgerStatus(models.TextChoices):
    DRAFT = "DRAFT", "Draft"
    CONFIRMED = "CONFIRMED", "Confirmed"


class LaborMonthlyPayrollPaymentStatus(models.TextChoices):
    PENDING = "PENDING", "미지급"
    PAID = "PAID", "지급완료"


class LaborWorkLedger(models.Model):
    work_date = models.DateField(db_index=True)
    work_month = models.DateField(db_index=True)
    worker = models.ForeignKey(
        "labor.WorkerMaster",
        on_delete=models.PROTECT,
        related_name="work_ledgers",
    )
    actual_project = models.ForeignKey(
        "projects.Project",
        on_delete=models.PROTECT,
        related_name="labor_work_ledgers_actual",
    )
    report_project = models.ForeignKey(
        "projects.Project",
        on_delete=models.PROTECT,
        related_name="labor_work_ledgers_report",
    )
    labor_role = models.ForeignKey(
        "labor.LaborRole",
        on_delete=models.PROTECT,
        related_name="work_ledgers",
    )
    work_unit = models.DecimalField(max_digits=10, decimal_places=2, default=0)
    work_hours = models.DecimalField(max_digits=10, decimal_places=2, default=0)
    unit_wage = models.BigIntegerField(default=0)
    gross_wage = models.BigIntegerField(default=0)
    income_tax = models.BigIntegerField(default=0)
    local_tax = models.BigIntegerField(default=0)
    employment_insurance = models.BigIntegerField(default=0)
    pension = models.BigIntegerField(default=0)
    health_insurance = models.BigIntegerField(default=0)
    net_pay = models.BigIntegerField(default=0)
    detail_work_type = models.CharField(max_length=120, blank=True, default="")
    source = models.CharField(
        max_length=20,
        choices=LaborWorkLedgerSource.choices,
        default=LaborWorkLedgerSource.MANUAL,
    )
    status = models.CharField(
        max_length=20,
        choices=LaborWorkLedgerStatus.choices,
        default=LaborWorkLedgerStatus.DRAFT,
    )
    timesheet_ref = models.ForeignKey(
        "labor.Timesheet",
        null=True,
        blank=True,
        on_delete=models.SET_NULL,
        related_name="work_ledgers",
    )
    cost_ref = models.ForeignKey(
        "cost.CostActual",
        null=True,
        blank=True,
        on_delete=models.SET_NULL,
        related_name="labor_work_ledgers",
    )
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        ordering = ["-work_date", "-id"]
        indexes = [
            models.Index(fields=["work_month"]),
            models.Index(fields=["worker"]),
            models.Index(fields=["actual_project"]),
            models.Index(fields=["report_project"]),
            models.Index(fields=["status"]),
        ]

    def save(self, *args, **kwargs):
        if self.timesheet_ref_id:
            if not self.work_date:
                self.work_date = self.timesheet_ref.work_date
            if not self.actual_project_id:
                self.actual_project = self.timesheet_ref.project
            if not self.labor_role_id:
                line = self.timesheet_ref.lines.select_related("labor_role").first()
                if line is not None:
                    self.labor_role = line.labor_role
                    if not self.work_unit:
                        self.work_unit = line.headcount
                    if not self.work_hours and line.hours is not None:
                        self.work_hours = line.hours
                    if not self.unit_wage and line.unit_rate:
                        self.unit_wage = int(line.unit_rate)
            if self.source == LaborWorkLedgerSource.MANUAL:
                self.source = LaborWorkLedgerSource.TIMESHEET

        if self.cost_ref_id:
            if not self.work_date:
                self.work_date = self.cost_ref.report_date
            if not self.actual_project_id:
                self.actual_project = self.cost_ref.project
            if self.source == LaborWorkLedgerSource.MANUAL:
                self.source = LaborWorkLedgerSource.COST

        if not self.report_project_id and self.actual_project_id:
            self.report_project = self.actual_project

        if self.work_date:
            self.work_month = self.work_date.replace(day=1)

        work_unit = Decimal(str(self.work_unit or 0))
        unit_wage = Decimal(str(self.unit_wage or 0))
        gross = (work_unit * unit_wage).quantize(Decimal("1"), rounding=ROUND_HALF_UP)
        self.gross_wage = int(gross)
        deductions = sum(
            int(value or 0)
            for value in (
                self.income_tax,
                self.local_tax,
                self.employment_insurance,
                self.pension,
                self.health_insurance,
            )
        )
        self.net_pay = self.gross_wage - deductions
        super().save(*args, **kwargs)

    def __str__(self) -> str:
        return f"{self.work_date} {self.worker} {self.actual_project}"


class LaborMonthlyPayroll(models.Model):
    year_month = models.DateField(db_index=True)
    worker = models.ForeignKey(
        "labor.WorkerMaster",
        on_delete=models.PROTECT,
        related_name="monthly_payrolls",
    )
    project = models.ForeignKey(
        "projects.Project",
        on_delete=models.PROTECT,
        related_name="labor_monthly_payrolls",
    )
    report_project = models.ForeignKey(
        "projects.Project",
        on_delete=models.PROTECT,
        related_name="labor_monthly_payrolls_report",
    )
    total_work_unit = models.DecimalField(max_digits=10, decimal_places=2, default=0)
    gross_wage = models.BigIntegerField(default=0)
    income_tax = models.BigIntegerField(default=0)
    local_tax = models.BigIntegerField(default=0)
    insurance_deductions = models.BigIntegerField(default=0)
    net_pay = models.BigIntegerField(default=0)
    bank_name = models.CharField(max_length=120, blank=True, default="")
    account_number_masked = models.CharField(max_length=32, blank=True, default="")
    payment_status = models.CharField(
        max_length=20,
        choices=LaborMonthlyPayrollPaymentStatus.choices,
        default=LaborMonthlyPayrollPaymentStatus.PENDING,
        db_index=True,
    )
    paid_at = models.DateTimeField(null=True, blank=True)
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        ordering = ["-year_month", "worker__name", "project__name", "id"]
        constraints = [
            models.UniqueConstraint(
                fields=["year_month", "worker", "project", "report_project"],
                name="uniq_labor_monthly_payroll_scope",
            )
        ]

    def __str__(self) -> str:
        return f"{self.year_month} {self.worker} {self.project}"


class ElectronicCardImportBatchStatus(models.TextChoices):
    UPLOADED = "UPLOADED", "업로드됨"
    HEADER_CHECKED = "HEADER_CHECKED", "헤더 확인"
    PARSE_READY = "PARSE_READY", "파싱 준비"
    CONFIRMED = "CONFIRMED", "확정"
    DISCARDED = "DISCARDED", "폐기"


def _electronic_card_upload_to(instance, filename):
    year_month = getattr(instance, "year_month", None)
    if year_month:
        return (
            f"labor/e_card_imports/{year_month.year:04d}/{year_month.month:02d}/{filename}"
        )
    return f"labor/e_card_imports/{filename}"


class ElectronicCardImportBatch(models.Model):
    year_month = models.DateField(db_index=True)
    project = models.ForeignKey(
        "projects.Project",
        on_delete=models.PROTECT,
        related_name="electronic_card_import_batches",
    )
    cwma_project_name = models.CharField(max_length=255, blank=True, default="")
    deduction_join_no = models.CharField(max_length=120, blank=True, default="")
    company_name = models.CharField(max_length=255, blank=True, default="")
    source_file = models.FileField(upload_to=_electronic_card_upload_to)
    original_filename = models.CharField(max_length=255, blank=True, default="")
    status = models.CharField(
        max_length=20,
        choices=ElectronicCardImportBatchStatus.choices,
        default=ElectronicCardImportBatchStatus.UPLOADED,
        db_index=True,
    )
    uploaded_by = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="electronic_card_imports_uploaded",
    )
    uploaded_at = models.DateTimeField(auto_now_add=True)
    confirmed_by = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="electronic_card_imports_confirmed",
    )
    confirmed_at = models.DateTimeField(null=True, blank=True)
    header_check_summary = models.JSONField(blank=True, default=dict)
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        ordering = ["-uploaded_at", "-id"]
        indexes = [
            models.Index(fields=["year_month", "project"]),
            models.Index(fields=["status", "uploaded_at"]),
        ]

    def __str__(self) -> str:
        return f"{self.year_month} {self.project} {self.original_filename or self.source_file.name}"


class ElectronicCardMatchStatus(models.TextChoices):
    MATCHED = "MATCHED", "매칭"
    UNMATCHED = "UNMATCHED", "미매칭"


class ElectronicCardWorkRaw(models.Model):
    batch = models.ForeignKey(
        "labor.ElectronicCardImportBatch",
        on_delete=models.CASCADE,
        related_name="raw_rows",
    )
    row_no = models.IntegerField()
    work_month = models.DateField(db_index=True)
    project_name_raw = models.CharField(max_length=255, blank=True, default="")
    deduction_join_no = models.CharField(max_length=120, blank=True, default="")
    company_name = models.CharField(max_length=255, blank=True, default="")
    worker_name_raw = models.CharField(max_length=120, blank=True, default="")
    rrn_encrypted = models.CharField(max_length=255, blank=True, default="")
    rrn_masked = models.CharField(max_length=32, blank=True, default="")
    identity_hash = models.CharField(max_length=64, blank=True, default="", db_index=True)
    phone = models.CharField(max_length=40, blank=True, default="")
    job_name_raw = models.CharField(max_length=120, blank=True, default="")
    card_issued = models.CharField(max_length=60, blank=True, default="")
    retirement_target = models.CharField(max_length=60, blank=True, default="")
    exclusion_reason = models.CharField(max_length=255, blank=True, default="")
    work_status = models.CharField(max_length=120, blank=True, default="")
    report_status = models.CharField(max_length=120, blank=True, default="")
    error_message = models.TextField(blank=True, default="")
    auto_work_days = models.CharField(max_length=40, blank=True, default="")
    reported_days = models.CharField(max_length=40, blank=True, default="")
    declaration_days = models.CharField(max_length=40, blank=True, default="")
    confirmed_days = models.CharField(max_length=40, blank=True, default="")
    day_01 = models.CharField(max_length=16, blank=True, default="")
    day_02 = models.CharField(max_length=16, blank=True, default="")
    day_03 = models.CharField(max_length=16, blank=True, default="")
    day_04 = models.CharField(max_length=16, blank=True, default="")
    day_05 = models.CharField(max_length=16, blank=True, default="")
    day_06 = models.CharField(max_length=16, blank=True, default="")
    day_07 = models.CharField(max_length=16, blank=True, default="")
    day_08 = models.CharField(max_length=16, blank=True, default="")
    day_09 = models.CharField(max_length=16, blank=True, default="")
    day_10 = models.CharField(max_length=16, blank=True, default="")
    day_11 = models.CharField(max_length=16, blank=True, default="")
    day_12 = models.CharField(max_length=16, blank=True, default="")
    day_13 = models.CharField(max_length=16, blank=True, default="")
    day_14 = models.CharField(max_length=16, blank=True, default="")
    day_15 = models.CharField(max_length=16, blank=True, default="")
    day_16 = models.CharField(max_length=16, blank=True, default="")
    day_17 = models.CharField(max_length=16, blank=True, default="")
    day_18 = models.CharField(max_length=16, blank=True, default="")
    day_19 = models.CharField(max_length=16, blank=True, default="")
    day_20 = models.CharField(max_length=16, blank=True, default="")
    day_21 = models.CharField(max_length=16, blank=True, default="")
    day_22 = models.CharField(max_length=16, blank=True, default="")
    day_23 = models.CharField(max_length=16, blank=True, default="")
    day_24 = models.CharField(max_length=16, blank=True, default="")
    day_25 = models.CharField(max_length=16, blank=True, default="")
    day_26 = models.CharField(max_length=16, blank=True, default="")
    day_27 = models.CharField(max_length=16, blank=True, default="")
    day_28 = models.CharField(max_length=16, blank=True, default="")
    day_29 = models.CharField(max_length=16, blank=True, default="")
    day_30 = models.CharField(max_length=16, blank=True, default="")
    day_31 = models.CharField(max_length=16, blank=True, default="")
    note = models.TextField(blank=True, default="")
    matched_worker = models.ForeignKey(
        "labor.WorkerMaster",
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="electronic_card_raw_rows",
    )
    match_status = models.CharField(
        max_length=12,
        choices=ElectronicCardMatchStatus.choices,
        default=ElectronicCardMatchStatus.UNMATCHED,
        db_index=True,
    )
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        ordering = ["row_no", "id"]
        constraints = [
            models.UniqueConstraint(
                fields=["batch", "row_no"],
                name="uniq_electronic_card_work_raw_row",
            )
        ]
        indexes = [
            models.Index(fields=["batch", "work_month"]),
            models.Index(fields=["batch", "identity_hash", "match_status"]),
        ]

    def __str__(self) -> str:
        return f"{self.batch_id} row {self.row_no} {self.worker_name_raw}"


class ElectronicCardWorkDay(models.Model):
    raw = models.ForeignKey(
        "labor.ElectronicCardWorkRaw",
        on_delete=models.CASCADE,
        related_name="days",
    )
    batch = models.ForeignKey(
        "labor.ElectronicCardImportBatch",
        on_delete=models.CASCADE,
        related_name="day_rows",
    )
    worker = models.ForeignKey(
        "labor.WorkerMaster",
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="electronic_card_day_rows",
    )
    work_date = models.DateField(db_index=True)
    card_value = models.DecimalField(max_digits=5, decimal_places=2, default=0)
    is_worked = models.BooleanField(default=False)
    card_project = models.ForeignKey(
        "projects.Project",
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="electronic_card_day_rows",
    )
    match_status = models.CharField(
        max_length=12,
        choices=ElectronicCardMatchStatus.choices,
        default=ElectronicCardMatchStatus.UNMATCHED,
        db_index=True,
    )
    note = models.TextField(blank=True, default="")
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        ordering = ["work_date", "id"]
        constraints = [
            models.UniqueConstraint(
                fields=["raw", "work_date"],
                name="uniq_electronic_card_work_day_scope",
            )
        ]
        indexes = [
            models.Index(fields=["batch", "work_date"]),
            models.Index(fields=["batch", "worker", "match_status"]),
        ]

    def __str__(self) -> str:
        return f"{self.batch_id} {self.work_date} {self.card_value}"


class LaborReconciliationStatus(models.TextChoices):
    MATCH = "MATCH", "일치"
    ERP_ONLY = "ERP_ONLY", "ERP만 있음"
    CARD_ONLY = "CARD_ONLY", "전자카드만 있음"
    DIFF = "DIFF", "공수 차이"
    UNMATCHED = "UNMATCHED", "미매칭"
    RESOLVED = "RESOLVED", "해결됨"


class LaborReconciliationResolution(models.TextChoices):
    ERP = "ERP", "ERP 기준"
    CARD = "CARD", "전자카드 기준"
    MANUAL = "MANUAL", "수동 확인"
    EXCLUDED = "EXCLUDED", "제외"


class LaborReconciliationResult(models.Model):
    batch = models.ForeignKey(
        "labor.ElectronicCardImportBatch",
        on_delete=models.CASCADE,
        related_name="reconciliation_results",
    )
    year_month = models.DateField(db_index=True)
    project = models.ForeignKey(
        "projects.Project",
        on_delete=models.PROTECT,
        related_name="labor_reconciliation_results",
    )
    worker = models.ForeignKey(
        "labor.WorkerMaster",
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="labor_reconciliation_results",
    )
    work_date = models.DateField(db_index=True)
    erp_work_unit = models.DecimalField(max_digits=10, decimal_places=2, default=0)
    card_work_unit = models.DecimalField(max_digits=10, decimal_places=2, default=0)
    difference = models.DecimalField(max_digits=10, decimal_places=2, default=0)
    status = models.CharField(
        max_length=16,
        choices=LaborReconciliationStatus.choices,
        default=LaborReconciliationStatus.DIFF,
        db_index=True,
    )
    resolution = models.CharField(
        max_length=16,
        choices=LaborReconciliationResolution.choices,
        blank=True,
        default="",
    )
    final_work_unit = models.DecimalField(
        max_digits=10,
        decimal_places=2,
        null=True,
        blank=True,
    )
    hq_comment = models.TextField(blank=True, default="")
    resolved_by = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="labor_reconciliation_results_resolved",
    )
    resolved_at = models.DateTimeField(null=True, blank=True)
    export_included = models.BooleanField(default=True)
    export_value = models.DecimalField(
        max_digits=10,
        decimal_places=2,
        null=True,
        blank=True,
    )
    export_note = models.TextField(blank=True, default="")
    card_day = models.ForeignKey(
        "labor.ElectronicCardWorkDay",
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="reconciliation_results",
    )
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        ordering = ["work_date", "worker_id", "id"]
        indexes = [
            models.Index(fields=["batch", "year_month", "project"]),
            models.Index(fields=["batch", "worker", "work_date", "status"]),
        ]

    def __str__(self) -> str:
        return f"{self.batch_id} {self.work_date} {self.status}"


class LaborConfirmedWorkSourceBasis(models.TextChoices):
    ERP = "ERP", "ERP"
    CARD = "CARD", "전자카드"
    MANUAL = "MANUAL", "수동확정"
    EXCLUDED = "EXCLUDED", "제외"


class LaborConfirmedWorkDay(models.Model):
    batch = models.ForeignKey(
        "labor.ElectronicCardImportBatch",
        on_delete=models.CASCADE,
        related_name="confirmed_work_days",
    )
    year_month = models.DateField(db_index=True)
    worker = models.ForeignKey(
        "labor.WorkerMaster",
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="confirmed_work_days",
    )
    actual_project = models.ForeignKey(
        "projects.Project",
        on_delete=models.PROTECT,
        null=True,
        blank=True,
        related_name="labor_confirmed_work_days_actual",
    )
    report_project = models.ForeignKey(
        "projects.Project",
        on_delete=models.PROTECT,
        related_name="labor_confirmed_work_days_report",
    )
    card_project = models.ForeignKey(
        "projects.Project",
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="labor_confirmed_work_days_card",
    )
    work_date = models.DateField(db_index=True)
    final_work_unit = models.DecimalField(max_digits=10, decimal_places=2, default=0)
    source_basis = models.CharField(
        max_length=16,
        choices=LaborConfirmedWorkSourceBasis.choices,
        default=LaborConfirmedWorkSourceBasis.ERP,
    )
    reconciliation_result = models.ForeignKey(
        "labor.LaborReconciliationResult",
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="confirmed_work_days",
    )
    export_included = models.BooleanField(default=True)
    export_value = models.DecimalField(
        max_digits=10,
        decimal_places=2,
        null=True,
        blank=True,
    )
    export_note = models.TextField(blank=True, default="")
    confirmed_by = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="labor_confirmed_work_days_confirmed",
    )
    confirmed_at = models.DateTimeField()
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        ordering = ["work_date", "worker_id", "id"]
        indexes = [
            models.Index(fields=["year_month", "worker", "report_project", "work_date"]),
            models.Index(fields=["batch", "source_basis", "export_included"]),
        ]
        constraints = [
            models.UniqueConstraint(
                fields=["reconciliation_result"],
                name="uniq_labor_confirmed_work_day_result",
            )
        ]

    def __str__(self) -> str:
        return f"{self.year_month} {self.work_date} {self.final_work_unit}"


class LaborExcelExportType(models.TextChoices):
    CWMA_CARD_REUPLOAD = "CWMA_CARD_REUPLOAD", "CWMA 전자카드 재업로드"


class LaborExcelExportStatus(models.TextChoices):
    GENERATED = "GENERATED", "생성됨"
    DOWNLOADED = "DOWNLOADED", "다운로드됨"
    DISCARDED = "DISCARDED", "폐기"


class LaborComplianceExportType(models.TextChoices):
    WORK_CONFIRMATION = "WORK_CONFIRMATION", "근로내용확인신고"
    DAILY_WAGE_STATEMENT = "DAILY_WAGE_STATEMENT", "일용노무비지급명세서"


def _labor_compliance_export_upload_to(instance, filename):
    return (
        "labor/compliance_exports/"
        f"{instance.year_month.year:04d}/{instance.year_month.month:02d}/{filename}"
    )


class LaborComplianceExport(models.Model):
    """Closed-month statutory/export snapshot.  It is deliberately immutable source data."""

    export_type = models.CharField(max_length=32, choices=LaborComplianceExportType.choices)
    year_month = models.DateField(db_index=True)
    project = models.ForeignKey(
        "projects.Project", on_delete=models.PROTECT, related_name="labor_compliance_exports"
    )
    generated_file = models.FileField(upload_to=_labor_compliance_export_upload_to)
    generated_filename = models.CharField(max_length=255)
    source_summary = models.JSONField(default=dict, blank=True)
    generated_by = models.ForeignKey(
        settings.AUTH_USER_MODEL, on_delete=models.SET_NULL, null=True, blank=True,
        related_name="labor_compliance_exports_generated",
    )
    generated_at = models.DateTimeField(auto_now_add=True)
    downloaded_by = models.ForeignKey(
        settings.AUTH_USER_MODEL, on_delete=models.SET_NULL, null=True, blank=True,
        related_name="labor_compliance_exports_downloaded",
    )
    downloaded_at = models.DateTimeField(null=True, blank=True)

    class Meta:
        ordering = ["-generated_at", "-id"]
        indexes = [
            models.Index(fields=["export_type", "year_month", "project"]),
        ]

    def __str__(self):
        return f"{self.export_type} {self.year_month:%Y-%m} {self.project_id}"


def _labor_excel_export_upload_to(instance, filename):
    year_month = getattr(instance, "year_month", None)
    if year_month:
        return (
            "labor/exports/cwma_card_reupload/"
            f"{year_month.year:04d}/{year_month.month:02d}/{filename}"
        )
    return f"labor/exports/cwma_card_reupload/{filename}"


class LaborExcelExportBatch(models.Model):
    export_type = models.CharField(
        max_length=32,
        choices=LaborExcelExportType.choices,
        default=LaborExcelExportType.CWMA_CARD_REUPLOAD,
        db_index=True,
    )
    year_month = models.DateField(db_index=True)
    project = models.ForeignKey(
        "projects.Project",
        on_delete=models.PROTECT,
        related_name="labor_excel_exports",
    )
    source_batch = models.ForeignKey(
        "labor.ElectronicCardImportBatch",
        on_delete=models.CASCADE,
        related_name="excel_exports",
    )
    generated_file = models.FileField(upload_to=_labor_excel_export_upload_to)
    original_filename = models.CharField(max_length=255, blank=True, default="")
    generated_filename = models.CharField(max_length=255, blank=True, default="")
    generated_by = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="labor_excel_exports_generated",
    )
    generated_at = models.DateTimeField(auto_now_add=True)
    downloaded_by = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="labor_excel_exports_downloaded",
    )
    downloaded_at = models.DateTimeField(null=True, blank=True)
    status = models.CharField(
        max_length=16,
        choices=LaborExcelExportStatus.choices,
        default=LaborExcelExportStatus.GENERATED,
        db_index=True,
    )
    changed_count = models.IntegerField(default=0)
    included_count = models.IntegerField(default=0)
    excluded_count = models.IntegerField(default=0)
    total_export_work_unit = models.DecimalField(
        max_digits=12,
        decimal_places=2,
        default=Decimal("0"),
    )
    note = models.TextField(blank=True, default="")
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        ordering = ["-generated_at", "-id"]
        indexes = [
            models.Index(fields=["export_type"]),
            models.Index(fields=["year_month"]),
            models.Index(fields=["project"]),
            models.Index(fields=["source_batch"]),
            models.Index(fields=["status"]),
        ]

    def __str__(self) -> str:
        return f"{self.export_type} {self.year_month} {self.project_id} {self.generated_filename or self.id}"


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
    worker = models.ForeignKey(
        WorkerMaster,
        on_delete=models.PROTECT,
        null=True,
        blank=True,
        related_name="timesheet_lines",
    )
    labor_role = models.ForeignKey(
        LaborRole, on_delete=models.PROTECT, related_name="timesheet_lines"
    )
    headcount = models.DecimalField(max_digits=10, decimal_places=2)
    hours = models.DecimalField(max_digits=10, decimal_places=2, null=True, blank=True)
    rate_type = models.CharField(
        max_length=10, choices=LaborRateType.choices, default=LaborRateType.DAY
    )
    applied_rate = models.ForeignKey(
        LaborRateTable,
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="applied_timesheet_lines",
    )
    applied_rate_scope = models.CharField(max_length=24, blank=True, default="")
    applied_rate_effective_from = models.DateField(null=True, blank=True)
    applied_rate_resolved_at = models.DateTimeField(null=True, blank=True)
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
    legal_entity = models.ForeignKey(
        "core.LegalEntity",
        on_delete=models.PROTECT,
        related_name="payroll_allocation_batches",
        default=default_asan_legal_entity_id,
        help_text="이 급여 원가를 부담하는 고용 법인입니다.",
    )
    office_payroll_run = models.OneToOneField(
        "OfficePayrollRun",
        on_delete=models.PROTECT,
        null=True,
        blank=True,
        related_name="project_allocation_batch",
    )
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
                fields=["legal_entity", "period_year", "period_month"],
                name="uniq_payroll_batch_entity_period",
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


class OfficePayrollStatus(models.TextChoices):
    DRAFT = "DRAFT", "임시저장"
    SUBMITTED = "SUBMITTED", "검토 대기"
    APPROVED = "APPROVED", "확정"
    PAID = "PAID", "지급 완료"
    REJECTED = "REJECTED", "반려"
    VOID = "VOID", "폐기"


class OfficePayrollCorrectionStatus(models.TextChoices):
    DRAFT = "DRAFT", "임시저장"
    SUBMITTED = "SUBMITTED", "승인 대기"
    APPROVED = "APPROVED", "승인 완료"
    REJECTED = "REJECTED", "반려"
    APPLIED = "APPLIED", "적용 완료"


class OfficeEmployeeProfile(models.Model):
    """HQ employee master for confidential payroll; separate from FIELD workers."""

    user = models.OneToOneField(settings.AUTH_USER_MODEL, on_delete=models.PROTECT, related_name="office_employee_profile")
    employment_legal_entity = models.ForeignKey(
        "core.LegalEntity",
        on_delete=models.PROTECT,
        related_name="office_employees",
        default=default_asan_legal_entity_id,
        help_text="근로계약·급여·원천세·4대보험을 부담하는 고용 법인입니다.",
    )
    employee_no = models.CharField(max_length=40, unique=True)
    department = models.CharField(max_length=100, blank=True, default="")
    birth_date_encrypted = models.CharField(max_length=255, blank=True, default="")
    birth_date_masked = models.CharField(max_length=16, blank=True, default="")
    tax_dependent_count = models.PositiveSmallIntegerField(default=1)
    tax_child_count_8_to_20 = models.PositiveSmallIntegerField(default=0)
    tax_withholding_ratio = models.PositiveSmallIntegerField(default=100, help_text="근로소득 간이세액표 원천징수 선택비율(80/100/120)")
    active = models.BooleanField(default=True)
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        ordering = ["employee_no"]

    def __str__(self):
        return f"{self.employee_no} - {self.user.get_full_name() or self.user.username}"

    @property
    def birth_date(self):
        raw_value = _unprotect_sensitive_value(self.birth_date_encrypted, "office-employee-birth-date")
        try:
            return date.fromisoformat(raw_value) if raw_value else None
        except ValueError:
            return None

    def set_birth_date(self, value):
        if not value:
            self.birth_date_encrypted = ""
            self.birth_date_masked = ""
            return
        birth_date = value if isinstance(value, date) else date.fromisoformat(str(value))
        self.birth_date_encrypted = _protect_sensitive_value(birth_date.isoformat(), "office-employee-birth-date")
        self.birth_date_masked = f"{birth_date.year:04d}-**-**"

    def is_national_pension_eligible_for_month(self, year, month):
        """The month of the 60th birthday remains contributory."""
        birth_date = self.birth_date
        if birth_date is None:
            return True
        return date(year, month, 1) <= date(birth_date.year + 60, birth_date.month, 1)


class IncomeTaxTableVersion(models.Model):
    effective_from = models.DateField(unique=True)
    source_name = models.CharField(max_length=255)
    is_active = models.BooleanField(default=False)
    child_credit_one = models.PositiveIntegerField(default=12500)
    child_credit_two = models.PositiveIntegerField(default=29160)
    child_credit_per_additional = models.PositiveIntegerField(default=25000)
    created_by = models.ForeignKey(settings.AUTH_USER_MODEL, null=True, blank=True, on_delete=models.SET_NULL, related_name="income_tax_table_versions_created")
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ["-effective_from"]


class IncomeTaxTableRow(models.Model):
    version = models.ForeignKey(IncomeTaxTableVersion, on_delete=models.CASCADE, related_name="rows")
    monthly_pay_from = models.PositiveIntegerField()
    monthly_pay_to = models.PositiveIntegerField()
    dependent_count = models.PositiveSmallIntegerField()
    income_tax = models.PositiveIntegerField(default=0)

    class Meta:
        constraints = [models.UniqueConstraint(fields=["version", "monthly_pay_from", "dependent_count"], name="uniq_income_tax_table_row")]
        indexes = [models.Index(fields=["version", "dependent_count", "monthly_pay_from"])]


def resolve_monthly_income_tax(*, taxable_pay, employee, pay_date):
    """Resolve the NTS table amount and retain the inputs used for the result."""
    version = IncomeTaxTableVersion.objects.filter(is_active=True, effective_from__lte=pay_date).order_by("-effective_from").first()
    if version is None:
        raise ValidationError("적용일 기준의 근로소득 간이세액표가 등록되지 않았습니다. HQ가 공식 표를 등록해 주세요.")
    family_count = min(max(int(employee.tax_dependent_count or 1), 1), 11)
    row = IncomeTaxTableRow.objects.filter(version=version, dependent_count=family_count, monthly_pay_from__lte=taxable_pay, monthly_pay_to__gt=taxable_pay).order_by("-monthly_pay_from").first()
    if row is None:
        raise ValidationError("월 과세급여에 해당하는 근로소득 간이세액표 구간이 없습니다.")
    ratio = int(employee.tax_withholding_ratio or 100)
    if ratio not in (80, 100, 120):
        raise ValidationError("원천징수 선택비율은 80%, 100%, 120%만 가능합니다.")
    child_count = int(employee.tax_child_count_8_to_20 or 0)
    if child_count == 1:
        child_credit = version.child_credit_one
    elif child_count == 2:
        child_credit = version.child_credit_two
    elif child_count >= 3:
        child_credit = version.child_credit_two + (child_count - 2) * version.child_credit_per_additional
    else:
        child_credit = 0
    tax_after_child_credit = max(int(row.income_tax) - child_credit, 0)
    tax_amount = int(
        (Decimal(tax_after_child_credit) * Decimal(ratio) / Decimal("100")).quantize(
            Decimal("1"), rounding=ROUND_DOWN
        )
    )
    return tax_amount, version, {
        "dependent_count": family_count,
        "child_count_8_to_20": child_count,
        "withholding_ratio": ratio,
        "child_tax_credit": child_credit,
    }


class OfficeEmployeeNumberSequence(models.Model):
    year = models.IntegerField(unique=True)
    last_number = models.PositiveIntegerField(default=0)


class OfficePayrollRun(models.Model):
    period_year = models.IntegerField()
    period_month = models.IntegerField()
    legal_entity = models.ForeignKey(
        "core.LegalEntity",
        on_delete=models.PROTECT,
        related_name="office_payroll_runs",
        default=default_asan_legal_entity_id,
        help_text="본사 직원 급여를 지급하는 고용 법인입니다.",
    )
    status = models.CharField(max_length=12, choices=OfficePayrollStatus.choices, default=OfficePayrollStatus.DRAFT)
    note = models.TextField(blank=True, default="")
    created_by = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.PROTECT, related_name="office_payroll_runs_created")
    submitted_at = models.DateTimeField(null=True, blank=True)
    approved_by = models.ForeignKey(settings.AUTH_USER_MODEL, null=True, blank=True, on_delete=models.SET_NULL, related_name="office_payroll_runs_approved")
    approved_at = models.DateTimeField(null=True, blank=True)
    paid_at = models.DateTimeField(null=True, blank=True)
    voided_by = models.ForeignKey(settings.AUTH_USER_MODEL, null=True, blank=True, on_delete=models.SET_NULL, related_name="office_payroll_runs_voided")
    voided_at = models.DateTimeField(null=True, blank=True)
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        # A voided run remains as an audit record, but must not prevent HQ from
        # preparing a replacement payroll register for the same month.
        constraints = [
            models.UniqueConstraint(
                fields=["legal_entity", "period_year", "period_month"],
                condition=~models.Q(status="VOID"),
                name="uniq_active_office_payroll_run_entity_period",
            )
        ]
        ordering = ["-period_year", "-period_month", "-id"]

    @property
    def gross_total(self):
        return self.slips.aggregate(total=models.Sum("gross_pay"))["total"] or 0

    @property
    def deduction_total(self):
        return self.slips.aggregate(total=models.Sum("total_deduction"))["total"] or 0

    @property
    def net_total(self):
        return self.slips.aggregate(total=models.Sum("net_pay"))["total"] or 0

    @property
    def payment_date(self):
        """Regular payday: the fifth day of the month after the payroll period."""
        if self.period_month == 12:
            return date(self.period_year + 1, 1, 5)
        return date(self.period_year, self.period_month + 1, 5)


class OfficePayrollCorrection(models.Model):
    """Audited correction package for a finalized office payroll run."""

    run = models.ForeignKey(OfficePayrollRun, on_delete=models.PROTECT, related_name="corrections")
    status = models.CharField(max_length=12, choices=OfficePayrollCorrectionStatus.choices, default=OfficePayrollCorrectionStatus.DRAFT)
    reason = models.TextField(blank=True, default="")
    rejection_reason = models.TextField(blank=True, default="")
    original_snapshot = models.JSONField(default=list)
    proposed_snapshot = models.JSONField(default=list)
    requested_by = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.PROTECT, related_name="office_payroll_corrections_requested")
    submitted_at = models.DateTimeField(null=True, blank=True)
    approved_by = models.ForeignKey(settings.AUTH_USER_MODEL, null=True, blank=True, on_delete=models.SET_NULL, related_name="office_payroll_corrections_approved")
    approved_at = models.DateTimeField(null=True, blank=True)
    applied_by = models.ForeignKey(settings.AUTH_USER_MODEL, null=True, blank=True, on_delete=models.SET_NULL, related_name="office_payroll_corrections_applied")
    applied_at = models.DateTimeField(null=True, blank=True)
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        ordering = ["-id"]
        indexes = [models.Index(fields=["run", "status"])]

    def __str__(self):
        return f"급여대장 #{self.run_id} 정정 #{self.id}"


class OfficePayrollDeductionPolicy(models.Model):
    """Effective-dated, HQ-maintained employee deduction assumptions."""
    year = models.IntegerField(unique=True)
    national_pension_rate = models.DecimalField(max_digits=7, decimal_places=5, default=Decimal("0.04750"))
    health_insurance_rate = models.DecimalField(max_digits=7, decimal_places=5, default=Decimal("0.03595"))
    long_term_care_rate = models.DecimalField(max_digits=7, decimal_places=5, default=Decimal("0.13140"))
    employment_insurance_rate = models.DecimalField(max_digits=7, decimal_places=5, default=Decimal("0.00900"))
    income_tax_rate = models.DecimalField(max_digits=7, decimal_places=5, default=Decimal("0.00000"))
    meal_allowance_default = models.BigIntegerField(default=200_000)
    fuel_allowance_default = models.BigIntegerField(default=100_000)
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        ordering = ["-year"]


def _round_down_to_tens(value):
    """Return a won amount after discarding a remainder below ten won."""
    return int(
        (Decimal(value) / Decimal("10")).quantize(Decimal("1"), rounding=ROUND_DOWN)
        * Decimal("10")
    )


class OfficePayslip(models.Model):
    run = models.ForeignKey(OfficePayrollRun, on_delete=models.CASCADE, related_name="slips")
    employee = models.ForeignKey(OfficeEmployeeProfile, on_delete=models.PROTECT, related_name="payslips")
    base_pay = models.BigIntegerField(default=0)
    meal_allowance_pay = models.BigIntegerField(default=200_000)
    fuel_allowance_pay = models.BigIntegerField(default=100_000)
    # Existing generic allowances are migrated to this field without changing
    # their amount, so historical payroll totals and audit evidence remain valid.
    site_allowance_pay = models.BigIntegerField(default=0)
    overtime_pay = models.BigIntegerField(default=0)
    bonus_pay = models.BigIntegerField(default=0)
    income_tax = models.BigIntegerField(default=0)
    local_income_tax = models.BigIntegerField(default=0)
    national_pension = models.BigIntegerField(default=0)
    health_insurance = models.BigIntegerField(default=0)
    long_term_care = models.BigIntegerField(default=0)
    employment_insurance = models.BigIntegerField(default=0)
    other_deduction = models.BigIntegerField(default=0)
    gross_pay = models.BigIntegerField(default=0)
    total_deduction = models.BigIntegerField(default=0)
    net_pay = models.BigIntegerField(default=0)
    auto_income_tax = models.BigIntegerField(default=0)
    auto_local_income_tax = models.BigIntegerField(default=0)
    auto_national_pension = models.BigIntegerField(default=0)
    auto_national_pension_eligible = models.BooleanField(default=True)
    auto_health_insurance = models.BigIntegerField(default=0)
    auto_long_term_care = models.BigIntegerField(default=0)
    auto_employment_insurance = models.BigIntegerField(default=0)
    # Snapshot the official table and employee inputs used for an automatic
    # calculation. Later master-data changes must not obscure how a reviewed
    # or finalized payslip was calculated.
    auto_income_tax_table_version = models.ForeignKey(
        IncomeTaxTableVersion,
        null=True,
        blank=True,
        on_delete=models.SET_NULL,
        related_name="calculated_payslips",
    )
    auto_tax_dependent_count = models.PositiveSmallIntegerField(default=1)
    auto_tax_child_count_8_to_20 = models.PositiveSmallIntegerField(default=0)
    auto_tax_withholding_ratio = models.PositiveSmallIntegerField(default=100)
    auto_child_tax_credit = models.BigIntegerField(default=0)
    auto_calculated_at = models.DateTimeField(null=True, blank=True)
    issued_at = models.DateTimeField(null=True, blank=True)
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        constraints = [models.UniqueConstraint(fields=["run", "employee"], name="uniq_office_payslip_run_employee")]
        ordering = ["employee__employee_no"]

    def recalculate_totals(self):
        """Refresh derived totals in memory so HQ can review a draft calculation."""
        earnings = (
            (self.base_pay or 0)
            + (self.meal_allowance_pay or 0)
            + (self.fuel_allowance_pay or 0)
            + (self.site_allowance_pay or 0)
            + (self.overtime_pay or 0)
            + (self.bonus_pay or 0)
        )
        deductions = (self.income_tax or 0) + (self.local_income_tax or 0) + (self.national_pension or 0) + (self.health_insurance or 0) + (self.long_term_care or 0) + (self.employment_insurance or 0) + (self.other_deduction or 0)
        if earnings < 0 or deductions < 0:
            raise ValidationError("급여와 공제액은 0 이상이어야 합니다.")
        self.gross_pay, self.total_deduction, self.net_pay = earnings, deductions, earnings - deductions

    def save(self, *args, **kwargs):
        self.recalculate_totals()
        super().save(*args, **kwargs)

    def apply_auto_deductions(self, policy):
        """Populate reviewable defaults. HQ may replace the actual deduction fields."""
        from django.utils import timezone

        # Fixed meal and fuel benefits are the company's non-taxable items.
        # Other cash compensation is taxable remuneration and is included in
        # the statutory-insurance calculation base.
        insurance_base = Decimal(
            (self.base_pay or 0)
            + (self.site_allowance_pay or 0)
            + (self.overtime_pay or 0)
            + (self.bonus_pay or 0)
        )
        self.auto_national_pension_eligible = self.employee.is_national_pension_eligible_for_month(self.run.period_year, self.run.period_month)
        self.auto_national_pension = int((insurance_base * policy.national_pension_rate).quantize(Decimal("1"), rounding=ROUND_DOWN)) if self.auto_national_pension_eligible else 0
        # Health-insurance notices use amounts rounded down to the nearest ten
        # won.  Long-term care follows the rounded health-insurance amount.
        self.auto_health_insurance = _round_down_to_tens(insurance_base * policy.health_insurance_rate)
        self.auto_long_term_care = _round_down_to_tens(Decimal(self.auto_health_insurance) * policy.long_term_care_rate)
        self.auto_employment_insurance = int((insurance_base * policy.employment_insurance_rate).quantize(Decimal("1"), rounding=ROUND_DOWN))
        # Company policy: monthly meal and fuel allowances are fixed non-taxable
        # benefits.  They remain part of gross pay, but are excluded from the
        # income-tax table base and social-insurance base.
        taxable_pay = int(
            (self.base_pay or 0)
            + (self.site_allowance_pay or 0)
            + (self.overtime_pay or 0)
            + (self.bonus_pay or 0)
        )
        self.auto_income_tax, version, tax_inputs = resolve_monthly_income_tax(
            taxable_pay=taxable_pay,
            employee=self.employee,
            pay_date=date(self.run.period_year, self.run.period_month, 1),
        )
        self.auto_income_tax_table_version = version
        self.auto_tax_dependent_count = tax_inputs["dependent_count"]
        self.auto_tax_child_count_8_to_20 = tax_inputs["child_count_8_to_20"]
        self.auto_tax_withholding_ratio = tax_inputs["withholding_ratio"]
        self.auto_child_tax_credit = tax_inputs["child_tax_credit"]
        self.auto_local_income_tax = int((Decimal(self.auto_income_tax) * Decimal("0.1")).quantize(Decimal("1"), rounding=ROUND_DOWN))
        self.income_tax = self.auto_income_tax
        self.local_income_tax = self.auto_local_income_tax
        self.national_pension = self.auto_national_pension
        self.health_insurance = self.auto_health_insurance
        self.long_term_care = self.auto_long_term_care
        self.employment_insurance = self.auto_employment_insurance
        self.auto_calculated_at = timezone.now()
