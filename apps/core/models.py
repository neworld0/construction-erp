from django.conf import settings
from django.db import models


class ApprovalStatus(models.TextChoices):
    DRAFT = "draft", "Draft"
    SUBMITTED = "submitted", "Submitted"
    APPROVED = "approved", "Approved"
    REJECTED = "rejected", "Rejected"


class ApprovalRequest(models.Model):
    object_type = models.CharField(max_length=50)
    object_id = models.PositiveIntegerField()
    status = models.CharField(
        max_length=20,
        choices=ApprovalStatus.choices,
        default=ApprovalStatus.DRAFT,
    )
    submitted_by = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="submitted_approvals",
    )
    submitted_at = models.DateTimeField(null=True, blank=True)
    approved_by = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="approved_approvals",
    )
    approved_at = models.DateTimeField(null=True, blank=True)
    comment = models.TextField(blank=True, default="")
    reject_reason = models.TextField(blank=True, default="")
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        indexes = [
            models.Index(fields=["object_type", "object_id"], name="core_approval_obj_idx"),
            models.Index(fields=["status"], name="core_approval_status_idx"),
        ]

    def __str__(self) -> str:
        return f"{self.object_type}#{self.object_id} {self.status}"


# Load RBAC models for migrations/admin without duplicating app labels.
from .rbac.models import ProjectAssignment, Role, UserProfile  # noqa: E402,F401
