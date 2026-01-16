from django.conf import settings
from django.db import migrations, models
import django.db.models.deletion


class Migration(migrations.Migration):
    initial = True

    dependencies = [
        ("projects", "0001_initial"),
        migrations.swappable_dependency(settings.AUTH_USER_MODEL),
    ]

    operations = [
        migrations.CreateModel(
            name="AuditLog",
            fields=[
                (
                    "id",
                    models.BigAutoField(
                        auto_created=True, primary_key=True, serialize=False, verbose_name="ID"
                    ),
                ),
                ("action", models.CharField(max_length=80)),
                ("object_type", models.CharField(max_length=50)),
                ("object_id", models.PositiveIntegerField()),
                ("request_id", models.UUIDField(blank=True, null=True)),
                ("ip", models.GenericIPAddressField(blank=True, null=True)),
                ("user_agent", models.CharField(blank=True, default="", max_length=255)),
                ("before_json", models.JSONField(blank=True, null=True)),
                ("after_json", models.JSONField(blank=True, null=True)),
                ("meta_json", models.JSONField(blank=True, default=dict, null=True)),
                ("created_at", models.DateTimeField(auto_now_add=True)),
                (
                    "actor",
                    models.ForeignKey(
                        blank=True,
                        null=True,
                        on_delete=django.db.models.deletion.SET_NULL,
                        related_name="audit_logs",
                        to=settings.AUTH_USER_MODEL,
                    ),
                ),
                (
                    "project",
                    models.ForeignKey(
                        blank=True,
                        null=True,
                        on_delete=django.db.models.deletion.SET_NULL,
                        related_name="audit_logs",
                        to="projects.project",
                    ),
                ),
            ],
            options={
                "indexes": [
                    models.Index(fields=["object_type", "object_id"], name="audit_obj_idx"),
                    models.Index(fields=["project", "created_at"], name="audit_project_idx"),
                    models.Index(fields=["action", "created_at"], name="audit_action_idx"),
                ],
            },
        ),
    ]
