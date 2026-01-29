from django.db import migrations, models
import django.db.models.deletion


class Migration(migrations.Migration):
    dependencies = [
        ("projects", "0009_budgetitem_wbsitem"),
    ]

    operations = [
        migrations.RenameField(
            model_name="budgetitem",
            old_name="notes",
            new_name="note",
        ),
        migrations.AlterField(
            model_name="budgetitem",
            name="planned_amount",
            field=models.BigIntegerField(default=0),
        ),
        migrations.AlterField(
            model_name="budgetitem",
            name="cost_item",
            field=models.ForeignKey(
                on_delete=django.db.models.deletion.PROTECT,
                related_name="budget_items",
                to="cost.costitem",
            ),
        ),
        migrations.AlterField(
            model_name="budgetitem",
            name="project",
            field=models.ForeignKey(
                on_delete=django.db.models.deletion.CASCADE,
                related_name="budget_items",
                to="projects.project",
            ),
        ),
        migrations.AlterField(
            model_name="budgetitem",
            name="category",
            field=models.CharField(
                choices=[
                    ("MATERIAL", "Material"),
                    ("SUBCON", "Subcon"),
                    ("EQUIP", "Equip"),
                    ("LABOR", "Labor"),
                    ("OVERHEAD", "Overhead"),
                    ("OTHER", "Other"),
                ],
                default="OTHER",
                max_length=20,
            ),
        ),
        migrations.AlterField(
            model_name="budgetitem",
            name="name",
            field=models.CharField(blank=True, default="", max_length=120),
        ),
        migrations.AddField(
            model_name="budgetitem",
            name="status",
            field=models.CharField(
                choices=[("draft", "DRAFT"), ("submitted", "SUBMITTED"), ("approved", "APPROVED")],
                default="draft",
                max_length=16,
            ),
        ),
        migrations.AddField(
            model_name="budgetitem",
            name="updated_at",
            field=models.DateTimeField(auto_now=True),
        ),
        migrations.RemoveIndex(
            model_name="budgetitem",
            name="projects_bu_project_6f9e5b_idx",
        ),
        migrations.AddIndex(
            model_name="budgetitem",
            index=models.Index(fields=["project", "cost_item"], name="projects_bu_project_cost_item_idx"),
        ),
        migrations.AddConstraint(
            model_name="budgetitem",
            constraint=models.UniqueConstraint(
                fields=("project", "cost_item"),
                name="uq_budgetitem_project_costitem",
            ),
        ),
    ]
