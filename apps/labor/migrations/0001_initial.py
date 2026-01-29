from django.conf import settings
from django.db import migrations, models
import django.db.models.deletion


class Migration(migrations.Migration):

    initial = True

    dependencies = [
        ("cost", "0006_costitemalias"),
        ("projects", "0016_rename_projects_ap_package_3a20c6_idx_projects_ap_package_2176e5_idx"),
        migrations.swappable_dependency(settings.AUTH_USER_MODEL),
    ]

    operations = [
        migrations.CreateModel(
            name="LaborRole",
            fields=[
                ("id", models.BigAutoField(auto_created=True, primary_key=True, serialize=False, verbose_name="ID")),
                ("code", models.CharField(db_index=True, max_length=30, unique=True)),
                ("name", models.CharField(db_index=True, max_length=120)),
                ("role_group", models.CharField(blank=True, choices=[("FOREMAN", "Foreman"), ("SKILLED", "Skilled"), ("UNSKILLED", "Unskilled"), ("OPERATOR", "Operator"), ("ENGINEER", "Engineer"), ("ADMIN", "Admin")], default="", max_length=20)),
                ("is_active", models.BooleanField(default=True)),
                ("sort_order", models.IntegerField(default=0)),
                ("created_at", models.DateTimeField(auto_now_add=True)),
                ("updated_at", models.DateTimeField(auto_now=True)),
                ("default_cbs", models.ForeignKey(blank=True, null=True, on_delete=django.db.models.deletion.SET_NULL, related_name="labor_roles", to="cost.costitem")),
            ],
            options={
                "ordering": ["sort_order", "code"],
            },
        ),
        migrations.CreateModel(
            name="LaborRateTable",
            fields=[
                ("id", models.BigAutoField(auto_created=True, primary_key=True, serialize=False, verbose_name="ID")),
                ("rate_type", models.CharField(choices=[("DAY", "Per day"), ("HOUR", "Per hour")], default="DAY", max_length=10)),
                ("unit_rate", models.BigIntegerField()),
                ("currency", models.CharField(default="KRW", max_length=3)),
                ("effective_from", models.DateField()),
                ("effective_to", models.DateField(blank=True, null=True)),
                ("scope_type", models.CharField(choices=[("GLOBAL", "Global"), ("PROJECT", "Project")], default="GLOBAL", max_length=10)),
                ("is_active", models.BooleanField(default=True)),
                ("note", models.CharField(blank=True, max_length=255)),
                ("created_at", models.DateTimeField(auto_now_add=True)),
                ("updated_at", models.DateTimeField(auto_now=True)),
                ("created_by", models.ForeignKey(blank=True, null=True, on_delete=django.db.models.deletion.SET_NULL, related_name="labor_rates_created", to=settings.AUTH_USER_MODEL)),
                ("labor_role", models.ForeignKey(on_delete=django.db.models.deletion.CASCADE, related_name="rates", to="labor.laborrole")),
                ("project", models.ForeignKey(blank=True, null=True, on_delete=django.db.models.deletion.CASCADE, related_name="labor_rates", to="projects.project")),
            ],
            options={
                "ordering": ["-effective_from", "labor_role_id"],
            },
        ),
        migrations.AddIndex(
            model_name="laborrole",
            index=models.Index(fields=["code"], name="labor_laborrole_code_0f66db_idx"),
        ),
        migrations.AddIndex(
            model_name="laborrole",
            index=models.Index(fields=["name"], name="labor_laborrole_name_0f2a86_idx"),
        ),
        migrations.AddIndex(
            model_name="laborrole",
            index=models.Index(fields=["is_active"], name="labor_laborrole_is_acti_2c20f3_idx"),
        ),
        migrations.AddIndex(
            model_name="laborratetable",
            index=models.Index(fields=["labor_role", "scope_type", "project", "effective_from", "effective_to", "is_active"], name="labor_laborrate_labor_r_b44f8f_idx"),
        ),
    ]
