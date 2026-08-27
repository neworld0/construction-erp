from django.conf import settings
from django.db import migrations, models
import django.db.models.deletion


class Migration(migrations.Migration):
    dependencies = [("finance", "0001_cash_models"), migrations.swappable_dependency(settings.AUTH_USER_MODEL)]
    operations = [
        migrations.CreateModel(name="AdvancePayment", fields=[
            ("id", models.BigAutoField(auto_created=True, primary_key=True, serialize=False, verbose_name="ID")),
            ("contract_amount_snapshot", models.DecimalField(decimal_places=2, max_digits=16)),
            ("advance_rate_percent", models.DecimalField(decimal_places=3, max_digits=6)),
            ("advance_amount", models.DecimalField(decimal_places=2, max_digits=16)),
            ("received_amount", models.DecimalField(decimal_places=2, max_digits=16)),
            ("received_date", models.DateField()), ("memo", models.TextField(blank=True, default="")),
            ("created_at", models.DateTimeField(auto_now_add=True)),
            ("cash_event", models.OneToOneField(blank=True, null=True, on_delete=django.db.models.deletion.PROTECT, related_name="advance_payment", to="finance.cashevent")),
            ("created_by", models.ForeignKey(on_delete=django.db.models.deletion.PROTECT, related_name="created_advance_payments", to=settings.AUTH_USER_MODEL)),
            ("project", models.OneToOneField(on_delete=django.db.models.deletion.PROTECT, related_name="advance_payment", to="projects.project")),
        ]),
        migrations.AddConstraint(model_name="advancepayment", constraint=models.CheckConstraint(condition=models.Q(("advance_rate_percent__gte", 0), ("advance_rate_percent__lte", 100)), name="advance_payment_rate_range")),
        migrations.CreateModel(name="ProgressBilling", fields=[
            ("id", models.BigAutoField(auto_created=True, primary_key=True, serialize=False, verbose_name="ID")),
            ("billing_date", models.DateField()), ("contract_amount_snapshot", models.DecimalField(decimal_places=2, max_digits=16)),
            ("approved_progress_percent", models.DecimalField(decimal_places=3, max_digits=6)), ("cumulative_earned_amount", models.DecimalField(decimal_places=2, max_digits=16)),
            ("previously_billed_amount", models.DecimalField(decimal_places=2, default=0, max_digits=16)), ("gross_claim_amount", models.DecimalField(decimal_places=2, max_digits=16)),
            ("cumulative_advance_deduction", models.DecimalField(decimal_places=2, default=0, max_digits=16)), ("advance_deduction_amount", models.DecimalField(decimal_places=2, default=0, max_digits=16)),
            ("net_claim_amount", models.DecimalField(decimal_places=2, max_digits=16)), ("advance_balance_after", models.DecimalField(decimal_places=2, default=0, max_digits=16)),
            ("status", models.CharField(choices=[("ISSUED", "Issued"), ("COLLECTED", "Collected")], default="ISSUED", max_length=16)),
            ("memo", models.TextField(blank=True, default="")), ("issued_at", models.DateTimeField(auto_now_add=True)), ("collected_at", models.DateTimeField(blank=True, null=True)),
            ("cash_event", models.OneToOneField(blank=True, null=True, on_delete=django.db.models.deletion.PROTECT, related_name="progress_billing", to="finance.cashevent")),
            ("collected_by", models.ForeignKey(blank=True, null=True, on_delete=django.db.models.deletion.SET_NULL, related_name="collected_progress_billings", to=settings.AUTH_USER_MODEL)),
            ("issued_by", models.ForeignKey(on_delete=django.db.models.deletion.PROTECT, related_name="issued_progress_billings", to=settings.AUTH_USER_MODEL)),
            ("project", models.ForeignKey(on_delete=django.db.models.deletion.PROTECT, related_name="progress_billings", to="projects.project")),
        ], options={"ordering": ["-billing_date", "-id"]}),
        migrations.AddConstraint(model_name="progressbilling", constraint=models.UniqueConstraint(fields=("project", "billing_date"), name="uniq_progress_billing_date")),
    ]
