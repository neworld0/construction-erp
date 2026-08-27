from django.conf import settings
from django.db import migrations, models
import django.db.models.deletion


class Migration(migrations.Migration):
    dependencies = [("labor", "0019_officeemployeenumbersequence"), migrations.swappable_dependency(settings.AUTH_USER_MODEL)]

    operations = [
        migrations.CreateModel(
            name="OfficePayrollCorrection",
            fields=[
                ("id", models.BigAutoField(auto_created=True, primary_key=True, serialize=False, verbose_name="ID")),
                ("status", models.CharField(choices=[("DRAFT", "임시저장"), ("SUBMITTED", "승인 대기"), ("APPROVED", "승인 완료"), ("REJECTED", "반려"), ("APPLIED", "적용 완료")], default="DRAFT", max_length=12)),
                ("reason", models.TextField(blank=True, default="")),
                ("rejection_reason", models.TextField(blank=True, default="")),
                ("original_snapshot", models.JSONField(default=list)),
                ("proposed_snapshot", models.JSONField(default=list)),
                ("submitted_at", models.DateTimeField(blank=True, null=True)),
                ("approved_at", models.DateTimeField(blank=True, null=True)),
                ("applied_at", models.DateTimeField(blank=True, null=True)),
                ("created_at", models.DateTimeField(auto_now_add=True)),
                ("updated_at", models.DateTimeField(auto_now=True)),
                ("applied_by", models.ForeignKey(blank=True, null=True, on_delete=django.db.models.deletion.SET_NULL, related_name="office_payroll_corrections_applied", to=settings.AUTH_USER_MODEL)),
                ("approved_by", models.ForeignKey(blank=True, null=True, on_delete=django.db.models.deletion.SET_NULL, related_name="office_payroll_corrections_approved", to=settings.AUTH_USER_MODEL)),
                ("requested_by", models.ForeignKey(on_delete=django.db.models.deletion.PROTECT, related_name="office_payroll_corrections_requested", to=settings.AUTH_USER_MODEL)),
                ("run", models.ForeignKey(on_delete=django.db.models.deletion.PROTECT, related_name="corrections", to="labor.officepayrollrun")),
            ],
            options={"ordering": ["-id"]},
        ),
        migrations.AddIndex(model_name="officepayrollcorrection", index=models.Index(fields=["run", "status"], name="labor_offi_run_id_b0f2ee_idx")),
    ]
