from django.db import migrations, models
import django.db.models.deletion


class Migration(migrations.Migration):
    dependencies = [
        ("projects", "0001_initial"),
    ]

    operations = [
        migrations.CreateModel(
            name="ProjectContract",
            fields=[
                (
                    "id",
                    models.BigAutoField(
                        auto_created=True, primary_key=True, serialize=False, verbose_name="ID"
                    ),
                ),
                ("contract_amount", models.DecimalField(decimal_places=2, max_digits=16)),
                ("contract_start_date", models.DateField(blank=True, null=True)),
                ("contract_end_date", models.DateField(blank=True, null=True)),
                ("contract_file", models.FileField(blank=True, upload_to="project_contracts/")),
                ("memo", models.TextField(blank=True, default="")),
                (
                    "project",
                    models.OneToOneField(
                        on_delete=django.db.models.deletion.CASCADE,
                        related_name="contract",
                        to="projects.project",
                    ),
                ),
            ],
        ),
    ]
