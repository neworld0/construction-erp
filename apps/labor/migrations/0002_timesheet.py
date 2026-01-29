from django.conf import settings
from django.db import migrations, models
import django.db.models.deletion


class Migration(migrations.Migration):

    dependencies = [
        ("projects", "0005_wbsitem"),
        ("labor", "0001_initial"),
        migrations.swappable_dependency(settings.AUTH_USER_MODEL),
    ]

    operations = [
        migrations.CreateModel(
            name="Timesheet",
            fields=[
                ("id", models.BigAutoField(auto_created=True, primary_key=True, serialize=False, verbose_name="ID")),
                ("sheet_no", models.CharField(db_index=True, max_length=20, unique=True)),
                ("work_date", models.DateField()),
                ("status", models.CharField(choices=[("DRAFT", "Draft"), ("SUBMITTED", "Submitted"), ("APPROVED", "Approved"), ("REJECTED", "Rejected")], default="DRAFT", max_length=12)),
                ("note", models.TextField(blank=True)),
                ("submitted_at", models.DateTimeField(blank=True, null=True)),
                ("approved_at", models.DateTimeField(blank=True, null=True)),
                ("rejected_at", models.DateTimeField(blank=True, null=True)),
                ("reject_reason", models.TextField(blank=True)),
                ("created_at", models.DateTimeField(auto_now_add=True)),
                ("updated_at", models.DateTimeField(auto_now=True)),
                ("approved_by", models.ForeignKey(blank=True, null=True, on_delete=django.db.models.deletion.SET_NULL, related_name="timesheets_approved", to=settings.AUTH_USER_MODEL)),
                ("created_by", models.ForeignKey(on_delete=django.db.models.deletion.CASCADE, related_name="timesheets_created", to=settings.AUTH_USER_MODEL)),
                ("project", models.ForeignKey(on_delete=django.db.models.deletion.CASCADE, related_name="timesheets", to="projects.project")),
                ("rejected_by", models.ForeignKey(blank=True, null=True, on_delete=django.db.models.deletion.SET_NULL, related_name="timesheets_rejected", to=settings.AUTH_USER_MODEL)),
            ],
            options={
                "ordering": ["-work_date", "-id"],
            },
        ),
        migrations.CreateModel(
            name="TimesheetLine",
            fields=[
                ("id", models.BigAutoField(auto_created=True, primary_key=True, serialize=False, verbose_name="ID")),
                ("headcount", models.DecimalField(decimal_places=2, max_digits=10)),
                ("hours", models.DecimalField(blank=True, decimal_places=2, max_digits=10, null=True)),
                ("rate_type", models.CharField(choices=[("DAY", "Per day"), ("HOUR", "Per hour")], default="DAY", max_length=10)),
                ("unit_rate", models.BigIntegerField()),
                ("amount", models.BigIntegerField()),
                ("memo", models.CharField(blank=True, max_length=255)),
                ("labor_role", models.ForeignKey(on_delete=django.db.models.deletion.PROTECT, related_name="timesheet_lines", to="labor.laborrole")),
                ("timesheet", models.ForeignKey(on_delete=django.db.models.deletion.CASCADE, related_name="lines", to="labor.timesheet")),
            ],
            options={
                "ordering": ["id"],
            },
        ),
        migrations.CreateModel(
            name="TimesheetNumberSequence",
            fields=[
                ("id", models.BigAutoField(auto_created=True, primary_key=True, serialize=False, verbose_name="ID")),
                ("key", models.CharField(max_length=20, unique=True)),
                ("last_number", models.IntegerField(default=0)),
            ],
            options={
                "ordering": ["key"],
            },
        ),
        migrations.AddIndex(
            model_name="timesheet",
            index=models.Index(fields=["project", "work_date"], name="labor_timesheet_project_c2df9b_idx"),
        ),
        migrations.AddIndex(
            model_name="timesheet",
            index=models.Index(fields=["status"], name="labor_timesheet_status_4fb338_idx"),
        ),
        migrations.AddIndex(
            model_name="timesheetline",
            index=models.Index(fields=["timesheet"], name="labor_timeshe_timeshe_44c41a_idx"),
        ),
        migrations.AddIndex(
            model_name="timesheetline",
            index=models.Index(fields=["labor_role"], name="labor_timeshe_labor_r_9d4f22_idx"),
        ),
    ]
