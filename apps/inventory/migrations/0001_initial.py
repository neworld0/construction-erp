from django.db import migrations, models
import django.db.models.deletion
import django.db.models.expressions
import django.db.models.functions
import django.db.models.query_utils


class Migration(migrations.Migration):
    initial = True

    dependencies = [
        ("projects", "0016_rename_projects_ap_package_3a20c6_idx_projects_ap_package_2176e5_idx"),
    ]

    operations = [
        migrations.CreateModel(
            name="Warehouse",
            fields=[
                ("id", models.BigAutoField(auto_created=True, primary_key=True, serialize=False, verbose_name="ID")),
                ("name", models.CharField(max_length=120)),
                ("code", models.CharField(max_length=50, unique=True)),
                (
                    "warehouse_type",
                    models.CharField(choices=[("hq", "HQ"), ("site", "SITE")], max_length=10),
                ),
                ("is_active", models.BooleanField(default=True)),
                ("created_at", models.DateTimeField(auto_now_add=True)),
                ("updated_at", models.DateTimeField(auto_now=True)),
                (
                    "project",
                    models.ForeignKey(
                        blank=True,
                        null=True,
                        on_delete=django.db.models.deletion.CASCADE,
                        related_name="warehouses",
                        to="projects.project",
                    ),
                ),
            ],
        ),
        migrations.CreateModel(
            name="Location",
            fields=[
                ("id", models.BigAutoField(auto_created=True, primary_key=True, serialize=False, verbose_name="ID")),
                ("name", models.CharField(max_length=120)),
                ("code", models.CharField(max_length=30)),
                ("is_default", models.BooleanField(default=False)),
                ("is_active", models.BooleanField(default=True)),
                ("created_at", models.DateTimeField(auto_now_add=True)),
                ("updated_at", models.DateTimeField(auto_now=True)),
                (
                    "warehouse",
                    models.ForeignKey(
                        on_delete=django.db.models.deletion.CASCADE,
                        related_name="locations",
                        to="inventory.warehouse",
                    ),
                ),
            ],
        ),
        migrations.AddIndex(
            model_name="warehouse",
            index=models.Index(fields=["warehouse_type", "project"], name="inventory_wa_warehou_1c7a1b_idx"),
        ),
        migrations.AddConstraint(
            model_name="warehouse",
            constraint=models.CheckConstraint(
                check=(
                    models.Q(("warehouse_type", "hq"), ("project__isnull", True))
                    | models.Q(("warehouse_type", "site"), ("project__isnull", False))
                ),
                name="chk_warehouse_type_project",
            ),
        ),
        migrations.AddConstraint(
            model_name="location",
            constraint=models.UniqueConstraint(
                fields=("warehouse", "code"), name="uq_location_warehouse_code"
            ),
        ),
        migrations.AddConstraint(
            model_name="location",
            constraint=models.UniqueConstraint(
                fields=("warehouse",),
                condition=models.Q(("is_default", True)),
                name="uq_location_default_per_warehouse",
            ),
        ),
        migrations.AddIndex(
            model_name="location",
            index=models.Index(fields=["warehouse", "is_active"], name="inventory_lo_warehou_987f80_idx"),
        ),
    ]
