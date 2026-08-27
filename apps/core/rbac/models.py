from django.conf import settings
import hashlib
from pathlib import Path

from django.core.exceptions import ValidationError
from django.core.validators import FileExtensionValidator
from django.db import models


class Role(models.TextChoices):
    CEO = "ceo", "CEO"
    HQ = "hq", "HQ"
    FIELD = "field", "Field"


class LegalEntityAccessScope(models.TextChoices):
    FIELD = "FIELD", "현장"
    ENTITY_HQ = "ENTITY_HQ", "법인 HQ"
    GROUP_HQ = "GROUP_HQ", "그룹 HQ"
    CEO_VIEW = "CEO_VIEW", "CEO 조회"


class OrganizationGroup(models.Model):
    code = models.CharField(max_length=40, unique=True)
    name = models.CharField(max_length=120)
    is_active = models.BooleanField(default=True)
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        ordering = ["code"]

    def __str__(self):
        return f"{self.code} - {self.name}"


class LegalEntity(models.Model):
    group = models.ForeignKey(OrganizationGroup, on_delete=models.PROTECT, related_name="legal_entities")
    code = models.CharField(max_length=20, unique=True)
    name = models.CharField(max_length=120)
    legal_name = models.CharField(max_length=120)
    business_registration_number = models.CharField(max_length=30, blank=True, default="")
    corporate_registration_number = models.CharField(max_length=30, blank=True, default="")
    currency_code = models.CharField(max_length=3, default="KRW")
    is_active = models.BooleanField(default=True)
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        ordering = ["code"]

    def __str__(self):
        return f"{self.code} - {self.legal_name}"


def default_asan_legal_entity_id():
    """Compatibility default for older internal creation paths.

    User-facing flows select an entity explicitly. Legacy records and older
    seeds have a confirmed ASAN owner, so an omitted internal value is kept
    deterministic rather than becoming null or crossing to MISAN.
    """
    return LegalEntity.objects.get(code="ASAN").id


class LegalEntityLicense(models.Model):
    legal_entity = models.ForeignKey(LegalEntity, on_delete=models.PROTECT, related_name="licenses")
    license_type = models.CharField(max_length=120)
    registration_number = models.CharField(max_length=80)
    registered_on = models.DateField()
    registered_by = models.CharField(max_length=120)
    valid_from = models.DateField(null=True, blank=True)
    valid_to = models.DateField(null=True, blank=True)
    is_active = models.BooleanField(default=True)
    evidence_note = models.TextField(blank=True, default="")
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        constraints = [
            models.UniqueConstraint(
                fields=["legal_entity", "license_type", "registration_number"],
                name="uniq_legal_entity_license_registration",
            )
        ]
        ordering = ["legal_entity__code", "license_type"]

    def clean(self):
        if self.valid_to and self.valid_from and self.valid_to < self.valid_from:
            raise ValidationError({"valid_to": "유효 종료일은 시작일보다 빠를 수 없습니다."})

    def __str__(self):
        return f"{self.legal_entity.code} - {self.license_type}"


class LegalEntityLicensePerformanceSource(models.TextChoices):
    MANUAL = "MANUAL", "수기 입력"
    CERTIFICATE = "CERTIFICATE", "실적증명서"
    API = "API", "외부 API"
    IMPORT = "IMPORT", "파일 가져오기"


class LegalEntityLicenseConstructionPerformance(models.Model):
    """A dated, auditable tender-eligibility performance snapshot.

    The values are deliberately stored as supplied evidence rather than derived
    from internal project revenue: bid qualification often follows external
    certificate rules and can include historical work not held by this ERP.
    """

    license = models.ForeignKey(
        LegalEntityLicense,
        on_delete=models.PROTECT,
        related_name="construction_performances",
    )
    work_category = models.CharField(max_length=120)
    external_category_code = models.CharField(max_length=60, blank=True, default="")
    as_of_date = models.DateField(help_text="3년·5년 실적을 산정한 기준일")
    three_year_amount = models.DecimalField(max_digits=18, decimal_places=0, default=0)
    five_year_amount = models.DecimalField(max_digits=18, decimal_places=0, default=0)
    source = models.CharField(
        max_length=16,
        choices=LegalEntityLicensePerformanceSource.choices,
        default=LegalEntityLicensePerformanceSource.MANUAL,
    )
    evidence_note = models.TextField(blank=True, default="")
    created_by = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="created_legal_entity_license_performances",
    )
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        constraints = [
            models.UniqueConstraint(
                fields=["license", "work_category", "as_of_date"],
                name="uniq_license_work_category_performance_snapshot",
            ),
        ]
        indexes = [
            models.Index(fields=["license", "as_of_date"]),
            models.Index(fields=["external_category_code", "as_of_date"]),
        ]
        ordering = ["-as_of_date", "license__license_type", "work_category"]

    def clean(self):
        errors = {}
        if self.three_year_amount is not None and self.three_year_amount < 0:
            errors["three_year_amount"] = "3년 실적은 0원 이상이어야 합니다."
        if self.five_year_amount is not None and self.five_year_amount < 0:
            errors["five_year_amount"] = "5년 실적은 0원 이상이어야 합니다."
        if (
            self.three_year_amount is not None
            and self.five_year_amount is not None
            and self.five_year_amount < self.three_year_amount
        ):
            errors["five_year_amount"] = "5년 실적은 동일 기준의 3년 실적보다 작을 수 없습니다."
        if errors:
            raise ValidationError(errors)

    def __str__(self):
        return f"{self.license} / {self.work_category} / {self.as_of_date}"


def _license_performance_evidence_upload_to(instance, filename):
    safe_name = Path(filename).name
    return f"legal_entity_license_performance/{instance.performance_id}/{safe_name}"


def _file_sha256(file_obj):
    hasher = hashlib.sha256()
    for chunk in file_obj.chunks():
        hasher.update(chunk)
    if hasattr(file_obj, "seek"):
        file_obj.seek(0)
    return hasher.hexdigest()


class LegalEntityLicenseConstructionPerformanceEvidence(models.Model):
    """Append-only evidence files for a legal-entity performance snapshot."""

    performance = models.ForeignKey(
        LegalEntityLicenseConstructionPerformance,
        on_delete=models.CASCADE,
        related_name="evidences",
    )
    file = models.FileField(
        upload_to=_license_performance_evidence_upload_to,
        validators=[FileExtensionValidator(allowed_extensions=["pdf", "xlsx", "xls", "png", "jpg", "jpeg"])],
    )
    original_name = models.CharField(max_length=255)
    content_type = models.CharField(max_length=100, blank=True, default="")
    size_bytes = models.BigIntegerField()
    sha256 = models.CharField(max_length=64)
    uploaded_by = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.PROTECT,
        related_name="uploaded_legal_entity_license_performance_evidences",
    )
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        indexes = [models.Index(fields=["performance", "created_at"])]
        ordering = ["-created_at", "-id"]

    def clean(self):
        if self.pk:
            original = type(self).objects.filter(pk=self.pk).only("file").first()
            if original and original.file.name != self.file.name:
                raise ValidationError({"file": "이미 등록된 실적증명서 파일은 교체할 수 없습니다. 새 파일을 추가해 주세요."})

    def save(self, *args, **kwargs):
        self.clean()
        if not self.pk:
            if not self.file:
                raise ValidationError({"file": "실적증명서 파일을 선택해 주세요."})
            self.size_bytes = self.file.size
            self.sha256 = _file_sha256(self.file)
        super().save(*args, **kwargs)

    def __str__(self):
        return f"{self.original_name} ({self.sha256})"


class LegalEntityCreditRating(models.Model):
    """Dated legal-entity credit rating evidence for bid qualification."""

    legal_entity = models.ForeignKey(
        LegalEntity,
        on_delete=models.PROTECT,
        related_name="credit_ratings",
    )
    rating_agency = models.CharField(max_length=120)
    rating_grade = models.CharField(max_length=40)
    assessed_on = models.DateField(help_text="신용평가 기준일 또는 발급일")
    valid_until = models.DateField(null=True, blank=True)
    evidence_note = models.TextField(blank=True, default="")
    created_by = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="created_legal_entity_credit_ratings",
    )
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        constraints = [
            models.UniqueConstraint(
                fields=["legal_entity", "rating_agency", "assessed_on"],
                name="uniq_legal_entity_credit_rating_snapshot",
            ),
        ]
        indexes = [models.Index(fields=["legal_entity", "valid_until"])]
        ordering = ["-assessed_on", "rating_agency"]

    def clean(self):
        if self.valid_until and self.valid_until < self.assessed_on:
            raise ValidationError({"valid_until": "유효 종료일은 평가 기준일보다 빠를 수 없습니다."})

    def __str__(self):
        return f"{self.legal_entity.code} / {self.rating_agency} / {self.rating_grade}"


def _credit_rating_evidence_upload_to(instance, filename):
    safe_name = Path(filename).name
    return f"legal_entity_credit_rating/{instance.credit_rating_id}/{safe_name}"


class LegalEntityCreditRatingEvidence(models.Model):
    """Append-only source files for a legal-entity credit rating snapshot."""

    credit_rating = models.ForeignKey(
        LegalEntityCreditRating,
        on_delete=models.CASCADE,
        related_name="evidences",
    )
    file = models.FileField(
        upload_to=_credit_rating_evidence_upload_to,
        validators=[FileExtensionValidator(allowed_extensions=["pdf", "xlsx", "xls", "png", "jpg", "jpeg"])],
    )
    original_name = models.CharField(max_length=255)
    content_type = models.CharField(max_length=100, blank=True, default="")
    size_bytes = models.BigIntegerField()
    sha256 = models.CharField(max_length=64)
    uploaded_by = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.PROTECT,
        related_name="uploaded_legal_entity_credit_rating_evidences",
    )
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        indexes = [models.Index(fields=["credit_rating", "created_at"])]
        ordering = ["-created_at", "-id"]

    def clean(self):
        if self.pk:
            original = type(self).objects.filter(pk=self.pk).only("file").first()
            if original and original.file.name != self.file.name:
                raise ValidationError({"file": "이미 등록된 신용평가서 파일은 교체할 수 없습니다. 새 파일을 추가해 주세요."})

    def save(self, *args, **kwargs):
        self.clean()
        if not self.pk:
            if not self.file:
                raise ValidationError({"file": "신용평가서 파일을 선택해 주세요."})
            self.size_bytes = self.file.size
            self.sha256 = _file_sha256(self.file)
        super().save(*args, **kwargs)

    def __str__(self):
        return f"{self.original_name} ({self.sha256})"


class UserProfile(models.Model):
    user = models.OneToOneField(
        settings.AUTH_USER_MODEL, on_delete=models.CASCADE, related_name="profile"
    )
    role = models.CharField(max_length=20, choices=Role.choices, default=Role.FIELD)

    def __str__(self) -> str:
        return f"{self.user} ({self.role})"


class UserLegalEntityMembership(models.Model):
    user = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.CASCADE, related_name="legal_entity_memberships")
    legal_entity = models.ForeignKey(LegalEntity, on_delete=models.PROTECT, related_name="memberships")
    access_scope = models.CharField(max_length=16, choices=LegalEntityAccessScope.choices)
    is_active = models.BooleanField(default=True)
    effective_from = models.DateField(null=True, blank=True)
    effective_to = models.DateField(null=True, blank=True)
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        constraints = [
            models.UniqueConstraint(fields=["user", "legal_entity"], name="uniq_user_legal_entity_membership")
        ]
        indexes = [
            models.Index(fields=["user", "is_active"]),
            models.Index(fields=["legal_entity", "is_active"]),
        ]

    def clean(self):
        if self.effective_to and self.effective_from and self.effective_to < self.effective_from:
            raise ValidationError({"effective_to": "접근 종료일은 시작일보다 빠를 수 없습니다."})

    def __str__(self):
        return f"{self.user} -> {self.legal_entity.code} ({self.access_scope})"


class ProjectAssignment(models.Model):
    class AssignmentType(models.TextChoices):
        STANDARD = "STANDARD", "일반 배정"
        OPERATIONS_SUPPORT = "OPERATIONS_SUPPORT", "운영지원"

    user = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.CASCADE)
    project = models.ForeignKey("projects.Project", on_delete=models.CASCADE)
    assignment_type = models.CharField(
        max_length=24,
        choices=AssignmentType.choices,
        default=AssignmentType.STANDARD,
        help_text="타 법인 소속 본사 직원이 프로젝트를 지원하는 경우 운영지원으로 구분합니다.",
    )
    is_active = models.BooleanField(default=True)

    class Meta:
        constraints = [
            models.UniqueConstraint(
                fields=["user", "project"], name="uniq_project_assignment"
            )
        ]

    def __str__(self) -> str:
        return f"{self.user} -> {self.project} ({'active' if self.is_active else 'inactive'})"
