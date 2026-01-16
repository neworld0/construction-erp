from django.conf import settings
from django.db import migrations, models
import django.db.models.deletion


class Migration(migrations.Migration):
    dependencies = [
        migrations.swappable_dependency(settings.AUTH_USER_MODEL),
        ("contracts", "0001_initial"),
        ("projects", "0001_initial"),
        ("schedule", "0002_daily_progress"),
    ]

    operations = [
        migrations.CreateModel(
            name="PlanChangeRequest",
            fields=[
                (
                    "id",
                    models.BigAutoField(
                        auto_created=True, primary_key=True, serialize=False, verbose_name="ID"
                    ),
                ),
                (
                    "change_type",
                    models.CharField(
                        choices=[
                            ("field_request", "Field Request"),
                            ("design_change", "Design Change"),
                            ("change_order", "Change Order"),
                            ("force_majeure", "Force Majeure"),
                        ],
                        max_length=30,
                    ),
                ),
                ("reason", models.TextField()),
                ("proposed_payload", models.JSONField()),
                (
                    "status",
                    models.CharField(
                        choices=[
                            ("draft", "Draft"),
                            ("submitted", "Submitted"),
                            ("approved", "Approved"),
                            ("rejected", "Rejected"),
                        ],
                        default="draft",
                        max_length=20,
                    ),
                ),
                ("requested_at", models.DateTimeField(blank=True, null=True)),
                ("approved_at", models.DateTimeField(blank=True, null=True)),
                (
                    "contract_change",
                    models.ForeignKey(
                        blank=True,
                        null=True,
                        on_delete=django.db.models.deletion.SET_NULL,
                        to="contracts.contractchange",
                    ),
                ),
                ("created_at", models.DateTimeField(auto_now_add=True)),
                ("updated_at", models.DateTimeField(auto_now=True)),
                (
                    "approved_by",
                    models.ForeignKey(
                        blank=True,
                        null=True,
                        on_delete=django.db.models.deletion.SET_NULL,
                        related_name="approved_plan_changes",
                        to=settings.AUTH_USER_MODEL,
                    ),
                ),
                (
                    "base_plan",
                    models.ForeignKey(on_delete=django.db.models.deletion.PROTECT, to="schedule.scheduleplan"),
                ),
                (
                    "project",
                    models.ForeignKey(on_delete=django.db.models.deletion.PROTECT, to="projects.project"),
                ),
                (
                    "requested_by",
                    models.ForeignKey(
                        blank=True,
                        null=True,
                        on_delete=django.db.models.deletion.SET_NULL,
                        related_name="requested_plan_changes",
                        to=settings.AUTH_USER_MODEL,
                    ),
                ),
            ],
        ),
    ]
