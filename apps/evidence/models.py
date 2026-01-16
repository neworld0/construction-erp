import hashlib

from django.conf import settings
from django.core.exceptions import ValidationError
from django.db import models


class EvidenceStatus(models.TextChoices):
    DRAFT = "draft", "Draft"
    SUBMITTED = "submitted", "Submitted"
    APPROVED = "approved", "Approved"


class Evidence(models.Model):
    title = models.CharField(max_length=255)
    description = models.TextField(blank=True, default="")
    object_type = models.CharField(max_length=50)
    object_id = models.PositiveIntegerField()
    status = models.CharField(
        max_length=20,
        choices=EvidenceStatus.choices,
        default=EvidenceStatus.SUBMITTED,
    )
    created_by = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.PROTECT)
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        indexes = [
            models.Index(fields=["object_type", "object_id"]),
        ]

    def __str__(self) -> str:
        return f"{self.object_type}#{self.object_id} {self.title}"


def _file_sha256(file_obj):
    hasher = hashlib.sha256()
    for chunk in file_obj.chunks():
        hasher.update(chunk)
    return hasher.hexdigest()


class EvidenceFile(models.Model):
    evidence = models.ForeignKey(Evidence, related_name="files", on_delete=models.CASCADE)
    file = models.FileField(upload_to="evidence/")
    original_name = models.CharField(max_length=255)
    content_type = models.CharField(max_length=100)
    size_bytes = models.BigIntegerField()
    sha256 = models.CharField(max_length=64)
    created_by = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.PROTECT)
    created_at = models.DateTimeField(auto_now_add=True)

    def clean(self):
        if self.pk:
            original = EvidenceFile.objects.filter(pk=self.pk).first()
            if original and original.file.name != self.file.name:
                raise ValidationError({"file": "File replacement is not allowed."})

    def save(self, *args, **kwargs):
        self.clean()
        if not self.pk:
            if not self.file:
                raise ValidationError({"file": "File is required."})
            self.size_bytes = self.file.size
            self.sha256 = _file_sha256(self.file)
        super().save(*args, **kwargs)

    def __str__(self) -> str:
        return f"{self.original_name} ({self.sha256})"


class EvidencePolicy(models.Model):
    object_type = models.CharField(max_length=50)
    when_status = models.CharField(max_length=20)
    is_required = models.BooleanField(default=False)
    min_files = models.IntegerField(default=1)
    allowed_types = models.JSONField(blank=True, default=list)
    note = models.TextField(blank=True, default="")

    def __str__(self) -> str:
        return f"{self.object_type} {self.when_status}"
