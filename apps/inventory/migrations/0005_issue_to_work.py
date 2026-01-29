from django.conf import settings
from django.db import migrations, models
import django.db.models.deletion


class Migration(migrations.Migration):
    dependencies = [
        ("inventory", "0004_transfer"),
        ("cost", "0006_costitemalias"),
        ("projects", "0016_rename_projects_ap_package_3a20c6_idx_projects_ap_package_2176e5_idx"),
        migrations.swappable_dependency(settings.AUTH_USER_MODEL),
    ]

    operations = [
        migrations.AddField(
            model_name="itemmaster",
            name="standard_cost",
            field=models.BigIntegerField(blank=True, null=True),
        ),
        migrations.AddField(
            model_name="itemmaster",
            name="cost_updated_at",
            field=models.DateTimeField(blank=True, null=True),
        ),
        migrations.CreateModel(
            name="IssueNumberSequence",
            fields=[
                ("id", models.BigAutoField(auto_created=True, primary_key=True, serialize=False, verbose_name="ID")),
                ("key", models.CharField(max_length=20, unique=True)),
                ("last_number", models.IntegerField(default=0)),
                ("updated_at", models.DateTimeField(auto_now=True)),
            ],
        ),
        migrations.CreateModel(
            name="IssueToWork",
            fields=[
                ("id", models.BigAutoField(auto_created=True, primary_key=True, serialize=False, verbose_name="ID")),
                ("issue_no", models.CharField(db_index=True, max_length=30, unique=True)),
                ("issue_date", models.DateField()),
                ("status", models.CharField(choices=[("DRAFT", "DRAFT"), ("SUBMITTED", "SUBMITTED"), ("APPROVED", "APPROVED"), ("REJECTED", "REJECTED")], default="DRAFT", max_length=16)),
                ("note", models.TextField(blank=True, default="")),
                ("submitted_at", models.DateTimeField(blank=True, null=True)),
                ("approved_at", models.DateTimeField(blank=True, null=True)),
                ("created_at", models.DateTimeField(auto_now_add=True)),
                ("updated_at", models.DateTimeField(auto_now=True)),
                ("approved_by", models.ForeignKey(blank=True, null=True, on_delete=django.db.models.deletion.SET_NULL, related_name="approved_issue_to_work", to=settings.AUTH_USER_MODEL)),
                ("created_by", models.ForeignKey(on_delete=django.db.models.deletion.PROTECT, related_name="created_issue_to_work", to=settings.AUTH_USER_MODEL)),
                ("location", models.ForeignKey(blank=True, null=True, on_delete=django.db.models.deletion.PROTECT, related_name="issue_to_work", to="inventory.location")),
                ("project", models.ForeignKey(on_delete=django.db.models.deletion.PROTECT, to="projects.project")),
                ("warehouse", models.ForeignKey(on_delete=django.db.models.deletion.PROTECT, related_name="issue_to_work", to="inventory.warehouse")),
            ],
            options={
                "indexes": [
                    models.Index(fields=["project", "issue_date"], name="inventory_i_project_8f7e2c_idx"),
                    models.Index(fields=["status", "issue_date"], name="inventory_i_status_8dfd9d_idx"),
                ],
            },
        ),
        migrations.CreateModel(
            name="IssueToWorkLine",
            fields=[
                ("id", models.BigAutoField(auto_created=True, primary_key=True, serialize=False, verbose_name="ID")),
                ("qty", models.DecimalField(decimal_places=3, max_digits=18)),
                ("unit_cost", models.BigIntegerField(blank=True, null=True)),
                ("amount", models.BigIntegerField(blank=True, null=True)),
                ("memo", models.CharField(blank=True, default="", max_length=255)),
                ("cbs", models.ForeignKey(on_delete=django.db.models.deletion.PROTECT, related_name="issue_to_work_lines", to="cost.costitem")),
                ("issue", models.ForeignKey(on_delete=django.db.models.deletion.CASCADE, related_name="lines", to="inventory.issuetowork")),
                ("item", models.ForeignKey(on_delete=django.db.models.deletion.PROTECT, related_name="issue_to_work_lines", to="inventory.itemmaster")),
                ("uom", models.ForeignKey(on_delete=django.db.models.deletion.PROTECT, to="inventory.uom")),
            ],
            options={
                "indexes": [
                    models.Index(fields=["issue", "item"], name="inventory_i_issue_4a4fe1_idx"),
                ],
                "constraints": [
                    models.UniqueConstraint(fields=["issue", "item"], name="uq_issue_line_item"),
                ],
            },
        ),
    ]
