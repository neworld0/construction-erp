from django.conf import settings
from django.db import migrations, models
import django.db.models.deletion


class Migration(migrations.Migration):
    dependencies = [
        ("master", "0002_cbschangerequest"),
        migrations.swappable_dependency(settings.AUTH_USER_MODEL),
        ("cost", "0004_contractsnapshot_fk"),
    ]

    operations = [
        migrations.CreateModel(
            name="MasterTemplate",
            fields=[
                ("id", models.BigAutoField(auto_created=True, primary_key=True, serialize=False, verbose_name="ID")),
                ("name", models.CharField(max_length=120)),
                ("category", models.CharField(choices=[("WBS", "WBS"), ("BUDGET", "BUDGET")], max_length=16)),
                ("domain", models.CharField(choices=[("LANDSCAPE", "LANDSCAPE"), ("CIVIL", "CIVIL"), ("BUILDING", "BUILDING")], max_length=16)),
                ("version", models.IntegerField()),
                ("is_active", models.BooleanField(default=True)),
                ("note", models.TextField(blank=True, default="")),
                ("created_at", models.DateTimeField(auto_now_add=True)),
                ("updated_at", models.DateTimeField(auto_now=True)),
                ("created_by", models.ForeignKey(blank=True, null=True, on_delete=django.db.models.deletion.SET_NULL, related_name="created_master_templates", to=settings.AUTH_USER_MODEL)),
            ],
            options={
                "indexes": [models.Index(fields=["category", "domain", "is_active"], name="master_mas_category_17b73b_idx")],
            },
        ),
        migrations.CreateModel(
            name="MasterWBSTemplateItem",
            fields=[
                ("id", models.BigAutoField(auto_created=True, primary_key=True, serialize=False, verbose_name="ID")),
                ("order", models.IntegerField(default=0)),
                ("task_name", models.CharField(max_length=255)),
                ("weight", models.DecimalField(decimal_places=2, default=0, max_digits=5)),
                ("default_offset_start_days", models.IntegerField(blank=True, null=True)),
                ("default_duration_days", models.IntegerField(blank=True, null=True)),
                ("template", models.ForeignKey(on_delete=django.db.models.deletion.CASCADE, related_name="wbs_items", to="master.mastertemplate")),
            ],
            options={
                "ordering": ["order", "id"],
                "indexes": [models.Index(fields=["template", "order"], name="master_mas_template_9a8c33_idx")],
            },
        ),
        migrations.CreateModel(
            name="MasterBudgetTemplateItem",
            fields=[
                ("id", models.BigAutoField(auto_created=True, primary_key=True, serialize=False, verbose_name="ID")),
                ("order", models.IntegerField(default=0)),
                ("cost_item_code_snapshot", models.CharField(blank=True, default="", max_length=64)),
                ("label", models.CharField(max_length=128)),
                ("is_labor", models.BooleanField(default=False)),
                ("default_amount", models.BigIntegerField(blank=True, null=True)),
                ("cost_item", models.ForeignKey(blank=True, null=True, on_delete=django.db.models.deletion.SET_NULL, related_name="master_budget_items", to="cost.costitem")),
                ("template", models.ForeignKey(on_delete=django.db.models.deletion.CASCADE, related_name="budget_items", to="master.mastertemplate")),
            ],
            options={
                "ordering": ["order", "id"],
                "indexes": [models.Index(fields=["template", "order"], name="master_mas_template_8dc4c0_idx")],
            },
        ),
        migrations.AddConstraint(
            model_name="mastertemplate",
            constraint=models.UniqueConstraint(fields=("category", "domain", "version"), name="uniq_master_template_category_domain_version"),
        ),
    ]
