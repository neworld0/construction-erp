from django.conf import settings
from django.db import models


class Role(models.TextChoices):
    CEO = "ceo", "CEO"
    HQ = "hq", "HQ"
    FIELD = "field", "Field"


class UserProfile(models.Model):
    user = models.OneToOneField(
        settings.AUTH_USER_MODEL, on_delete=models.CASCADE, related_name="profile"
    )
    role = models.CharField(max_length=20, choices=Role.choices, default=Role.FIELD)

    def __str__(self) -> str:
        return f"{self.user} ({self.role})"


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
