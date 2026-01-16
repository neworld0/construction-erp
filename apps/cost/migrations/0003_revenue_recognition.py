from django.db import migrations, models
import django.db.models.deletion


class Migration(migrations.Migration):
    dependencies = [
        ("cost", "0002_costactual_and_lines"),
        ("projects", "0001_initial"),
    ]

    operations = [
        migrations.CreateModel(
            name="RevenueRecognition",
            fields=[
                (
                    "id",
                    models.BigAutoField(
                        auto_created=True, primary_key=True, serialize=False, verbose_name="ID"
                    ),
                ),
                ("contract_snapshot", models.PositiveIntegerField(blank=True, null=True)),
                ("as_of_date", models.DateField()),
                ("progress_percent", models.DecimalField(decimal_places=3, max_digits=6)),
                ("recognized_revenue", models.DecimalField(decimal_places=2, max_digits=16)),
                ("delta_revenue", models.DecimalField(decimal_places=2, default=0, max_digits=16)),
                ("created_at", models.DateTimeField(auto_now_add=True)),
                (
                    "project",
                    models.ForeignKey(on_delete=django.db.models.deletion.PROTECT, to="projects.project"),
                ),
            ],
            options={
                "ordering": ["-as_of_date"],
            },
        ),
        migrations.AddConstraint(
            model_name="revenuerecognition",
            constraint=models.UniqueConstraint(
                fields=("project", "contract_snapshot", "as_of_date"),
                name="uniq_revenue_recognition_asof",
            ),
        ),
    ]
