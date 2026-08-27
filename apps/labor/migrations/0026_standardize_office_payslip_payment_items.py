from django.db import migrations, models


class Migration(migrations.Migration):
    """Preserve existing generic allowances as site allowances before adding new items."""

    dependencies = [("labor", "0025_payslip_income_tax_snapshot")]

    operations = [
        migrations.RenameField(
            model_name="officepayslip",
            old_name="allowance_pay",
            new_name="site_allowance_pay",
        ),
        migrations.AddField(
            model_name="officepayslip",
            name="meal_allowance_pay",
            field=models.BigIntegerField(default=0),
        ),
        migrations.AddField(
            model_name="officepayslip",
            name="fuel_allowance_pay",
            field=models.BigIntegerField(default=0),
        ),
    ]
