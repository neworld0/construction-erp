from django.conf import settings
from django.db import models


class RiskSeverity(models.TextChoices):
    LOW = "low", "Low"
    MEDIUM = "medium", "Medium"
    HIGH = "high", "High"
    CRITICAL = "critical", "Critical"


class RiskRule(models.Model):
    key = models.CharField(max_length=100, unique=True)
    name = models.CharField(max_length=255)
    description = models.TextField()
    severity = models.CharField(max_length=20, choices=RiskSeverity.choices)
    threshold_json = models.JSONField(default=dict)
    is_active = models.BooleanField(default=True)
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    def __str__(self) -> str:
        return f"{self.key} ({self.severity})"


class RiskEvent(models.Model):
    event_type = models.CharField(max_length=50)
    object_type = models.CharField(max_length=50)
    object_id = models.PositiveIntegerField()
    actor = models.ForeignKey(
        settings.AUTH_USER_MODEL, on_delete=models.SET_NULL, null=True, blank=True
    )
    payload = models.JSONField(default=dict)
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        indexes = [
            models.Index(fields=["event_type"]),
            models.Index(fields=["object_type", "object_id"]),
        ]

    def __str__(self) -> str:
        return f"{self.event_type} {self.object_type}#{self.object_id}"


class RiskFindingStatus(models.TextChoices):
    OPEN = "open", "Open"
    ACK = "ack", "Acknowledged"
    CLOSED = "closed", "Closed"


class RiskFinding(models.Model):
    rule = models.ForeignKey(RiskRule, on_delete=models.PROTECT)
    event = models.ForeignKey(
        RiskEvent, on_delete=models.SET_NULL, null=True, blank=True
    )
    project = models.ForeignKey(
        "projects.Project", on_delete=models.SET_NULL, null=True, blank=True
    )
    object_type = models.CharField(max_length=50)
    object_id = models.PositiveIntegerField()
    score = models.DecimalField(max_digits=8, decimal_places=3)
    severity = models.CharField(max_length=20, choices=RiskSeverity.choices)
    title = models.CharField(max_length=255)
    details = models.TextField()
    status = models.CharField(
        max_length=20,
        choices=RiskFindingStatus.choices,
        default=RiskFindingStatus.OPEN,
    )
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)
    acknowledged_by = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="acknowledged_risk_findings",
    )
    acknowledged_at = models.DateTimeField(null=True, blank=True)

    def __str__(self) -> str:
        return f"{self.title} ({self.severity})"
