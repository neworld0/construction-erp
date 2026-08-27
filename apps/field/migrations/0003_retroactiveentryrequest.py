from django.conf import settings
from django.db import migrations, models
import django.db.models.deletion
from django.db.models import Q


class Migration(migrations.Migration):
    dependencies = [
        ("field", "0002_remove_dailyreport_unique"),
    ]

    operations = [
        migrations.CreateModel(
            name="RetroactiveEntryRequest",
            fields=[
                ("id", models.BigAutoField(auto_created=True, primary_key=True, serialize=False, verbose_name="ID")),
                ("request_type", models.CharField(choices=[("PROGRESS", "진행률")], default="PROGRESS", max_length=20)),
                ("target_date", models.DateField()),
                ("reason", models.TextField()),
                ("status", models.CharField(choices=[("PENDING", "승인 대기"), ("APPROVED", "승인됨"), ("REJECTED", "반려됨"), ("USED", "사용 완료")], default="PENDING", max_length=20)),
                ("requested_at", models.DateTimeField(auto_now_add=True)),
                ("reviewed_at", models.DateTimeField(blank=True, null=True)),
                ("review_comment", models.TextField(blank=True, default="")),
                ("used_at", models.DateTimeField(blank=True, null=True)),
                ("created_at", models.DateTimeField(auto_now_add=True)),
                ("updated_at", models.DateTimeField(auto_now=True)),
                ("project", models.ForeignKey(on_delete=django.db.models.deletion.PROTECT, related_name="retroactive_entry_requests", to="projects.project")),
                ("requested_by", models.ForeignKey(on_delete=django.db.models.deletion.PROTECT, related_name="retroactive_entry_requests", to=settings.AUTH_USER_MODEL)),
                ("reviewed_by", models.ForeignKey(blank=True, null=True, on_delete=django.db.models.deletion.PROTECT, related_name="retroactive_entry_requests_reviewed", to=settings.AUTH_USER_MODEL)),
            ],
            options={"ordering": ["-requested_at", "-id"]},
        ),
        migrations.AddIndex(
            model_name="retroactiveentryrequest",
            index=models.Index(fields=["status", "request_type"], name="field_retro_status_d6348b_idx"),
        ),
        migrations.AddIndex(
            model_name="retroactiveentryrequest",
            index=models.Index(fields=["requested_by", "project", "target_date"], name="field_retro_request_12a46c_idx"),
        ),
        migrations.AddConstraint(
            model_name="retroactiveentryrequest",
            constraint=models.UniqueConstraint(condition=Q(("status__in", ["PENDING", "APPROVED"])), fields=("requested_by", "project", "target_date", "request_type"), name="uq_active_retro_request_scope"),
        ),
    ]
