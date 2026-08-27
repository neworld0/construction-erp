from django.conf import settings
from django.db import migrations, models
import django.db.models.deletion
import apps.labor.models


class Migration(migrations.Migration):
    dependencies = [("labor", "0014_laborratetable_worker_timesheetline_rate_snapshot")]

    operations = [
        migrations.CreateModel(
            name="LaborComplianceExport",
            fields=[
                ("id", models.BigAutoField(auto_created=True, primary_key=True, serialize=False, verbose_name="ID")),
                ("export_type", models.CharField(choices=[("WORK_CONFIRMATION", "근로내용확인신고"), ("DAILY_WAGE_STATEMENT", "일용노무비지급명세서")], max_length=32)),
                ("year_month", models.DateField(db_index=True)),
                ("generated_file", models.FileField(upload_to=apps.labor.models._labor_compliance_export_upload_to)),
                ("generated_filename", models.CharField(max_length=255)),
                ("source_summary", models.JSONField(blank=True, default=dict)),
                ("generated_at", models.DateTimeField(auto_now_add=True)),
                ("downloaded_at", models.DateTimeField(blank=True, null=True)),
                ("downloaded_by", models.ForeignKey(blank=True, null=True, on_delete=django.db.models.deletion.SET_NULL, related_name="labor_compliance_exports_downloaded", to=settings.AUTH_USER_MODEL)),
                ("generated_by", models.ForeignKey(blank=True, null=True, on_delete=django.db.models.deletion.SET_NULL, related_name="labor_compliance_exports_generated", to=settings.AUTH_USER_MODEL)),
                ("project", models.ForeignKey(on_delete=django.db.models.deletion.PROTECT, related_name="labor_compliance_exports", to="projects.project")),
            ],
            options={"ordering": ["-generated_at", "-id"]},
        ),
        migrations.AddIndex(
            model_name="laborcomplianceexport",
            index=models.Index(fields=["export_type", "year_month", "project"], name="labor_labor_export__510b35_idx"),
        ),
    ]
