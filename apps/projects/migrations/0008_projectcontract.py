from django.db import migrations, models
import django.db.models.deletion


class Migration(migrations.Migration):
    dependencies = [
        ("projects", "0007_remove_projectcontract_project_remove_wbsitem_parent_and_more"),
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
                ("contract_amount", models.DecimalField(decimal_places=2, max_digits=16, default=0)),
                ("contract_start_date", models.DateField(blank=True, null=True)),
                ("contract_end_date", models.DateField(blank=True, null=True)),
                ("contract_file", models.FileField(blank=True, upload_to="project_contracts/")),
                ("memo", models.TextField(blank=True, default="")),
                ("start_date", models.DateField(blank=True, null=True)),
                ("end_date", models.DateField(blank=True, null=True)),
                ("signed_date", models.DateField(blank=True, null=True)),
                ("currency", models.CharField(default="KRW", max_length=3)),
                (
                    "status",
                    models.CharField(
                        choices=[
                            ("draft", "DRAFT"),
                            ("submitted", "SUBMITTED"),
                            ("approved", "APPROVED"),
                        ],
                        default="draft",
                        max_length=16,
                    ),
                ),
                ("created_at", models.DateTimeField(auto_now_add=True)),
                ("updated_at", models.DateTimeField(auto_now=True)),
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
