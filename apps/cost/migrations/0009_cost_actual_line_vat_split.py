from django.db import migrations, models
from django.db.models import F


def preserve_legacy_cost_lines(apps, schema_editor):
    CostActualLine = apps.get_model("cost", "CostActualLine")
    CostActualLine.objects.update(
        vat_treatment="LEGACY_UNCLASSIFIED",
        supply_amount=F("amount"),
        vat_amount=0,
        accounting_cost_amount=F("amount"),
    )


class Migration(migrations.Migration):
    dependencies = [("cost", "0008_tax_invoice_revenue_trigger")]

    operations = [
        migrations.AddField(
            model_name="costactualline",
            name="accounting_cost_amount",
            field=models.DecimalField(decimal_places=2, default=0, max_digits=16),
        ),
        migrations.AddField(
            model_name="costactualline",
            name="supply_amount",
            field=models.DecimalField(decimal_places=2, default=0, max_digits=16),
        ),
        migrations.AddField(
            model_name="costactualline",
            name="vat_amount",
            field=models.DecimalField(decimal_places=2, default=0, max_digits=16),
        ),
        migrations.AddField(
            model_name="costactualline",
            name="vat_treatment",
            field=models.CharField(
                choices=[
                    ("DEDUCTIBLE", "과세 · 매입세액 공제"),
                    ("EXEMPT", "면세 · VAT 없음"),
                    ("NON_DEDUCTIBLE", "불공제 · VAT 포함 원가"),
                    ("LEGACY_UNCLASSIFIED", "기존자료 · VAT 구분 필요"),
                ],
                default="DEDUCTIBLE",
                max_length=24,
            ),
        ),
        migrations.RunPython(preserve_legacy_cost_lines, migrations.RunPython.noop),
    ]
