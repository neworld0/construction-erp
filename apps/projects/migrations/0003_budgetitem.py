from django.db import migrations, models


class Migration(migrations.Migration):
    dependencies = [
        ("cost", "0004_contractsnapshot_fk"),
        ("projects", "0002_projectcontract"),
    ]

    operations = [
        migrations.CreateModel(
            name="BudgetItem",
            fields=[
                ("id", models.BigAutoField(auto_created=True, primary_key=True, serialize=False, verbose_name="ID")),
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
                        on_delete=models.SET_NULL,
                        to="cost.costitem",
                    ),
                ),
                (
                    "project",
                    models.ForeignKey(on_delete=models.CASCADE, to="projects.project"),
                ),
            ],
        ),
        migrations.AddIndex(
            model_name="budgetitem",
            index=models.Index(fields=["project", "category"], name="projects_bu_project_6f9e5b_idx"),
        ),
    ]
