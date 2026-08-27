from django.conf import settings
from django.db import migrations, models
import django.db.models.deletion


class Migration(migrations.Migration):
    dependencies = [("finance", "0002_advancepayment_progressbilling"), migrations.swappable_dependency(settings.AUTH_USER_MODEL)]
    operations = [
        migrations.CreateModel(name="BillingReport", fields=[
            ("id", models.BigAutoField(auto_created=True, primary_key=True, serialize=False, verbose_name="ID")),
            ("report_type", models.CharField(choices=[("PROGRESS", "Progress billing"), ("COMPLETION", "Completion billing")], max_length=16)),
            ("billing_round", models.PositiveIntegerField(default=1)), ("billing_date", models.DateField()),
            ("approved_progress_percent", models.DecimalField(decimal_places=3, max_digits=6)), ("contract_amount_snapshot", models.DecimalField(decimal_places=2, max_digits=16)),
            ("previous_billing_amount", models.DecimalField(decimal_places=2, default=0, max_digits=16)), ("current_gross_billing_amount", models.DecimalField(decimal_places=2, max_digits=16)),
            ("cumulative_billing_amount", models.DecimalField(decimal_places=2, max_digits=16)), ("remaining_billing_amount", models.DecimalField(decimal_places=2, max_digits=16)),
            ("advance_received_amount", models.DecimalField(decimal_places=2, default=0, max_digits=16)), ("previous_advance_deduction", models.DecimalField(decimal_places=2, default=0, max_digits=16)),
            ("current_advance_deduction", models.DecimalField(decimal_places=2, default=0, max_digits=16)), ("remaining_advance_balance", models.DecimalField(decimal_places=2, default=0, max_digits=16)),
            ("net_claim_amount", models.DecimalField(decimal_places=2, max_digits=16)), ("status", models.CharField(choices=[("DRAFT", "Draft"), ("ENGINEER_INPUT_REQUIRED", "Engineer input required"), ("HQ_APPROVED", "HQ approved"), ("LOCKED", "Locked")], default="DRAFT", max_length=32)),
            ("engineer_notes", models.JSONField(blank=True, default=dict)), ("attachment_checklist", models.JSONField(blank=True, default=dict)),
            ("generated_at", models.DateTimeField(auto_now_add=True)), ("updated_at", models.DateTimeField(auto_now=True)),
            ("generated_by", models.ForeignKey(on_delete=django.db.models.deletion.PROTECT, related_name="generated_billing_reports", to=settings.AUTH_USER_MODEL)),
            ("project", models.ForeignKey(on_delete=django.db.models.deletion.PROTECT, related_name="billing_reports", to="projects.project")),
        ], options={"ordering": ["-billing_date", "-id"]}),
        migrations.AddConstraint(model_name="billingreport", constraint=models.UniqueConstraint(fields=("project", "report_type", "billing_round"), name="uniq_billing_report_round")),
    ]
