from django.conf import settings
from django.db import models

from apps.projects.models import Project


class FieldReportStatus(models.TextChoices):
    DRAFT = "DRAFT", "Draft"
    SUBMITTED = "SUBMITTED", "Submitted"
    APPROVED = "APPROVED", "Approved"
    REJECTED = "REJECTED", "Rejected"


class FieldReport(models.Model):
    project = models.ForeignKey(Project, on_delete=models.CASCADE)
    report_date = models.DateField()
    title = models.CharField(max_length=200)
    content = models.TextField(blank=True)
    status = models.CharField(
        max_length=20, choices=FieldReportStatus.choices, default=FieldReportStatus.DRAFT
    )
    created_by = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.PROTECT)
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)
    submitted_at = models.DateTimeField(null=True, blank=True)
    approved_at = models.DateTimeField(null=True, blank=True)

    class Meta:
        ordering = ["-updated_at"]

    def __str__(self) -> str:
        return f"{self.project} - {self.title}"


class FieldReportFile(models.Model):
    report = models.ForeignKey(
        FieldReport, related_name="files", on_delete=models.CASCADE
    )
    file = models.FileField(upload_to="reports/")
    original_name = models.CharField(max_length=255, blank=True)
    uploaded_by = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.PROTECT)
    uploaded_at = models.DateTimeField(auto_now_add=True)

    def save(self, *args, **kwargs):
        if self.file and not self.original_name:
            self.original_name = self.file.name
        super().save(*args, **kwargs)
