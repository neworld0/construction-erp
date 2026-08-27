from django.conf import settings
from django.core.exceptions import ValidationError
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
    user = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.CASCADE)
    project = models.ForeignKey("projects.Project", on_delete=models.CASCADE)
    is_active = models.BooleanField(default=True)

    class Meta:
        constraints = [
            models.UniqueConstraint(
                fields=["user", "project"], name="uniq_project_assignment"
            )
        ]

    def __str__(self) -> str:
        return f"{self.user} -> {self.project} ({'active' if self.is_active else 'inactive'})"
