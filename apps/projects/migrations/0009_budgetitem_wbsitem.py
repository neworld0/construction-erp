from django.db import migrations, models
import django.db.models.deletion


class Migration(migrations.Migration):
    dependencies = [
        ("projects", "0008_projectcontract"),
    ]

    operations = [
        migrations.CreateModel(
            name="BudgetItem",
            fields=[
                (
                    "id",
                    models.BigAutoField(
                        auto_created=True, primary_key=True, serialize=False, verbose_name="ID"
                    ),
                ),
                (
                    "category",
                    models.CharField(
                        choices=[
                            ("MATERIAL", "Material"),
                            ("SUBCON", "Subcon"),
                            ("EQUIP", "Equip"),
                            ("LABOR", "Labor"),
                            ("OVERHEAD", "Overhead"),
                            ("OTHER", "Other"),
                        ],
                        max_length=20,
                    ),
                ),
                ("name", models.CharField(max_length=120)),
                ("planned_amount", models.DecimalField(decimal_places=2, max_digits=14)),
                ("notes", models.TextField(blank=True)),
                ("created_at", models.DateTimeField(auto_now_add=True)),
                (
                    "cost_item",
                    models.ForeignKey(
                        blank=True,
                        null=True,
                        on_delete=django.db.models.deletion.SET_NULL,
                        to="cost.costitem",
                    ),
                ),
                (
                    "project",
                    models.ForeignKey(on_delete=django.db.models.deletion.CASCADE, to="projects.project"),
                ),
            ],
        ),
        migrations.CreateModel(
            name="WBSItem",
            fields=[
                (
                    "id",
                    models.BigAutoField(
                        auto_created=True, primary_key=True, serialize=False, verbose_name="ID"
                    ),
                ),
                ("name", models.CharField(max_length=255)),
                ("weight", models.DecimalField(decimal_places=2, default=0, max_digits=6)),
                ("sort_order", models.IntegerField(default=0)),
                ("plan_start_date", models.DateField(blank=True, null=True)),
                ("plan_end_date", models.DateField(blank=True, null=True)),
                (
                    "parent",
                    models.ForeignKey(
                        blank=True,
                        null=True,
                        on_delete=django.db.models.deletion.SET_NULL,
                        to="projects.wbsitem",
                    ),
                ),
                (
                    "project",
                    models.ForeignKey(on_delete=django.db.models.deletion.CASCADE, to="projects.project"),
                ),
            ],
            options={
                "ordering": ["sort_order", "id"],
            },
        ),
        migrations.AddIndex(
            model_name="budgetitem",
            index=models.Index(fields=["project", "category"], name="projects_bu_project_6f9e5b_idx"),
        ),
        migrations.AddIndex(
            model_name="wbsitem",
            index=models.Index(fields=["project", "sort_order"], name="projects_wb_project_8f0f1c_idx"),
        ),
    ]
