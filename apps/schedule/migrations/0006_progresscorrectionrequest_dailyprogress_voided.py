from django.conf import settings
from django.db import migrations, models
from django.db.models import Q
import django.db.models.deletion


class Migration(migrations.Migration):
    dependencies = [
        ("schedule", "0005_alter_dailyprogress_note"),
        migrations.swappable_dependency(settings.AUTH_USER_MODEL),
    ]

    operations = [
        migrations.AlterField(
            model_name="dailyprogress",
            name="status",
            field=models.CharField(
                choices=[
                    ("draft", "Draft"), ("submitted", "Submitted"),
                    ("approved", "Approved"), ("voided", "Voided"),
                ],
                default="submitted", max_length=20,
            ),
        ),
        migrations.CreateModel(
            name="ProgressCorrectionRequest",
            fields=[
                ("id", models.BigAutoField(auto_created=True, primary_key=True, serialize=False, verbose_name="ID")),
                ("correction_type", models.CharField(choices=[("CORRECT", "Correct"), ("CANCEL", "Cancel")], max_length=10)),
                ("proposed_progress_percent", models.DecimalField(blank=True, decimal_places=3, max_digits=6, null=True)),
                ("proposed_note", models.TextField(blank=True, default="")),
                ("reason", models.TextField()),
                ("original_report_date", models.DateField()),
                ("original_progress_percent", models.DecimalField(decimal_places=3, max_digits=6)),
                ("original_note", models.TextField(blank=True, default="")),
                ("status", models.CharField(choices=[("HQ_REVIEW", "HQ Review"), ("CEO_REVIEW", "CEO Review"), ("APPROVED", "Approved"), ("REJECTED", "Rejected")], default="HQ_REVIEW", max_length=16)),
                ("hq_review_comment", models.TextField(blank=True, default="")),
                ("hq_reviewed_at", models.DateTimeField(blank=True, null=True)),
                ("approved_at", models.DateTimeField(blank=True, null=True)),
                ("rejection_reason", models.TextField(blank=True, default="")),
                ("created_at", models.DateTimeField(auto_now_add=True)),
                ("updated_at", models.DateTimeField(auto_now=True)),
                ("approved_by", models.ForeignKey(blank=True, null=True, on_delete=django.db.models.deletion.PROTECT, related_name="approved_progress_corrections", to=settings.AUTH_USER_MODEL)),
                ("hq_reviewed_by", models.ForeignKey(blank=True, null=True, on_delete=django.db.models.deletion.PROTECT, related_name="hq_reviewed_progress_corrections", to=settings.AUTH_USER_MODEL)),
                ("original_progress", models.ForeignKey(on_delete=django.db.models.deletion.PROTECT, related_name="correction_requests", to="schedule.dailyprogress")),
                ("project", models.ForeignKey(on_delete=django.db.models.deletion.PROTECT, to="projects.project")),
                ("requested_by", models.ForeignKey(on_delete=django.db.models.deletion.PROTECT, related_name="requested_progress_corrections", to=settings.AUTH_USER_MODEL)),
            ],
        ),
        migrations.AddIndex(model_name="progresscorrectionrequest", index=models.Index(fields=["status", "project"], name="schedule_pr_status_e21fd8_idx")),
        migrations.AddIndex(model_name="progresscorrectionrequest", index=models.Index(fields=["original_progress", "status"], name="schedule_pr_origina_e88dad_idx")),
        migrations.AddConstraint(model_name="progresscorrectionrequest", constraint=models.UniqueConstraint(condition=Q(("status__in", ["HQ_REVIEW", "CEO_REVIEW"])), fields=("original_progress",), name="uq_active_progress_correction")),
    ]
