from django.db import migrations, models


class Migration(migrations.Migration):
    dependencies = [
        ("projects", "0004_merge_0003_alter_project_status_0003_budgetitem"),
    ]

    operations = [
        migrations.CreateModel(
            name="WBSItem",
            fields=[
                ("id", models.BigAutoField(auto_created=True, primary_key=True, serialize=False, verbose_name="ID")),
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
                        on_delete=models.SET_NULL,
                        to="projects.wbsitem",
                    ),
                ),
                (
                    "project",
                    models.ForeignKey(on_delete=models.CASCADE, to="projects.project"),
                ),
            ],
            options={
                "ordering": ["sort_order", "id"],
            },
        ),
        migrations.AddIndex(
            model_name="wbsitem",
            index=models.Index(fields=["project", "sort_order"], name="projects_wb_project_8f0f1c_idx"),
        ),
    ]
