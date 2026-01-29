from django.conf import settings
from django.db import migrations, models
import django.db.models.deletion


class Migration(migrations.Migration):
    dependencies = [
        ("contenttypes", "0002_remove_content_type_name"),
        ("closing", "0001_initial"),
    ]

    operations = [
        migrations.CreateModel(
            name="Adjustment",
            fields=[
                ("id", models.BigAutoField(auto_created=True, primary_key=True, serialize=False, verbose_name="ID")),
                ("target_type", models.CharField(choices=[("COST", "Cost"), ("LABOR", "Labor"), ("INVENTORY", "Inventory")], max_length=20)),
                ("target_object_id", models.PositiveIntegerField(blank=True, null=True)),
                ("period_year", models.IntegerField()),
                ("period_month", models.IntegerField()),
                ("amount_delta", models.BigIntegerField()),
                ("reason", models.TextField()),
                ("status", models.CharField(choices=[("DRAFT", "Draft"), ("SUBMITTED", "Submitted"), ("APPROVED", "Approved"), ("REJECTED", "Rejected")], default="DRAFT", max_length=16)),
                ("approved_at", models.DateTimeField(blank=True, null=True)),
                ("created_at", models.DateTimeField(auto_now_add=True)),
                ("updated_at", models.DateTimeField(auto_now=True)),
                ("approved_by", models.ForeignKey(blank=True, null=True, on_delete=django.db.models.deletion.SET_NULL, related_name="approved_adjustments", to=settings.AUTH_USER_MODEL)),
                ("cbs", models.ForeignKey(blank=True, null=True, on_delete=django.db.models.deletion.SET_NULL, related_name="adjustments", to="cost.costitem")),
                ("created_by", models.ForeignKey(blank=True, null=True, on_delete=django.db.models.deletion.SET_NULL, related_name="created_adjustments", to=settings.AUTH_USER_MODEL)),
                ("project", models.ForeignKey(on_delete=django.db.models.deletion.CASCADE, related_name="adjustments", to="projects.project")),
                ("target_content_type", models.ForeignKey(blank=True, null=True, on_delete=django.db.models.deletion.SET_NULL, to="contenttypes.contenttype")),
            ],
        ),
        migrations.AddIndex(
            model_name="adjustment",
            index=models.Index(fields=["project", "period_year", "period_month"], name="closing_adj_project_period_idx"),
        ),
        migrations.AddIndex(
            model_name="adjustment",
            index=models.Index(fields=["status", "target_type"], name="closing_adj_status_type_idx"),
        ),
    ]
