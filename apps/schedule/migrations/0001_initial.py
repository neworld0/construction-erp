from django.conf import settings
from django.db import migrations, models
import django.db.models.deletion
import django.db.models.expressions


class Migration(migrations.Migration):
    initial = True

    dependencies = [
        migrations.swappable_dependency(settings.AUTH_USER_MODEL),
        ("projects", "0001_initial"),
    ]

    operations = [
        migrations.CreateModel(
            name="SchedulePlan",
            fields=[
                (
                    "id",
                    models.BigAutoField(
                        auto_created=True, primary_key=True, serialize=False, verbose_name="ID"
                    ),
                ),
                ("version_no", models.IntegerField(default=1)),
                ("name", models.CharField(default="Baseline", max_length=255)),
                ("is_active", models.BooleanField(default=True)),
                ("created_at", models.DateTimeField(auto_now_add=True)),
                ("updated_at", models.DateTimeField(auto_now=True)),
                (
                    "created_by",
                    models.ForeignKey(
                        blank=True,
                        null=True,
                        on_delete=django.db.models.deletion.SET_NULL,
                        related_name="created_schedule_plans",
                        to=settings.AUTH_USER_MODEL,
                    ),
                ),
                (
                    "project",
                    models.ForeignKey(on_delete=django.db.models.deletion.PROTECT, to="projects.project"),
                ),
            ],
            options={},
        ),
        migrations.CreateModel(
            name="ScheduleTask",
            fields=[
                (
                    "id",
                    models.BigAutoField(
                        auto_created=True, primary_key=True, serialize=False, verbose_name="ID"
                    ),
                ),
                ("name", models.CharField(max_length=255)),
                ("start_date", models.DateField(blank=True, null=True)),
                ("end_date", models.DateField(blank=True, null=True)),
                ("weight_percent", models.DecimalField(decimal_places=3, default=0, max_digits=6)),
                ("sort_order", models.IntegerField(default=0)),
                ("is_active", models.BooleanField(default=True)),
                (
                    "plan",
                    models.ForeignKey(
                        on_delete=django.db.models.deletion.CASCADE,
                        related_name="tasks",
                        to="schedule.scheduleplan",
                    ),
                ),
            ],
        ),
        migrations.AddConstraint(
            model_name="scheduleplan",
            constraint=models.UniqueConstraint(
                fields=("project", "version_no"), name="uniq_schedule_plan_version"
            ),
        ),
        migrations.AddConstraint(
            model_name="scheduleplan",
            constraint=models.UniqueConstraint(
                condition=models.Q(("is_active", True)),
                fields=("project",),
                name="uniq_schedule_plan_active",
            ),
        ),
    ]
