from django.conf import settings
from django.db import migrations, models
import django.db.models.deletion


class Migration(migrations.Migration):

    dependencies = [
        ("finance", "0005_billingreport_approval_workflow"),
        migrations.swappable_dependency(settings.AUTH_USER_MODEL),
    ]

    operations = [
        migrations.AddField(
            model_name="billingreport",
            name="owner_confirmation_status",
            field=models.CharField(
                choices=[("PENDING", "발주처 확정 통보 대기"), ("CONFIRMED", "발주처 확정 통보 수령")],
                default="PENDING",
                max_length=16,
            ),
        ),
        migrations.AddField(model_name="billingreport", name="owner_confirmation_date", field=models.DateField(blank=True, null=True)),
        migrations.AddField(model_name="billingreport", name="owner_confirmation_reference", field=models.CharField(blank=True, default="", max_length=120)),
        migrations.AddField(model_name="billingreport", name="owner_confirmation_note", field=models.TextField(blank=True, default="")),
        migrations.AddField(model_name="billingreport", name="owner_confirmed_at", field=models.DateTimeField(blank=True, null=True)),
        migrations.AddField(
            model_name="billingreport",
            name="owner_confirmed_by",
            field=models.ForeignKey(blank=True, null=True, on_delete=django.db.models.deletion.SET_NULL, related_name="owner_confirmed_billing_reports", to=settings.AUTH_USER_MODEL),
        ),
        migrations.CreateModel(
            name="TaxInvoice",
            fields=[
                ("id", models.BigAutoField(auto_created=True, primary_key=True, serialize=False, verbose_name="ID")),
                ("invoice_number", models.CharField(max_length=120, unique=True)),
                ("supply_date", models.DateField()),
                ("supply_amount", models.DecimalField(decimal_places=2, max_digits=16)),
                ("tax_amount", models.DecimalField(decimal_places=2, max_digits=16)),
                ("status", models.CharField(choices=[("ISSUED", "발행"), ("CANCELLED", "취소")], default="ISSUED", max_length=16)),
                ("issued_at", models.DateTimeField(auto_now_add=True)),
                ("memo", models.TextField(blank=True, default="")),
                ("billing_report", models.OneToOneField(on_delete=django.db.models.deletion.PROTECT, related_name="tax_invoice", to="finance.billingreport")),
                ("issued_by", models.ForeignKey(on_delete=django.db.models.deletion.PROTECT, related_name="issued_tax_invoices", to=settings.AUTH_USER_MODEL)),
            ],
            options={"ordering": ["-supply_date", "-id"]},
        ),
    ]
