from decimal import Decimal

from django.db import migrations, models


def set_2026_national_pension_rate(apps, schema_editor):
    policy_model = apps.get_model("labor", "OfficePayrollDeductionPolicy")
    policy_model.objects.filter(year=2026).update(national_pension_rate=Decimal("0.04750"))


class Migration(migrations.Migration):
    dependencies = [("labor", "0026_standardize_office_payslip_payment_items")]

    operations = [
        migrations.AlterField(
            model_name="officepayrolldeductionpolicy",
            name="national_pension_rate",
            field=models.DecimalField(decimal_places=5, default=Decimal("0.04750"), max_digits=7),
        ),
        migrations.RunPython(set_2026_national_pension_rate, migrations.RunPython.noop),
    ]
