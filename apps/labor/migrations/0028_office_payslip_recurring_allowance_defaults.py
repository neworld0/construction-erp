from django.db import migrations, models


class Migration(migrations.Migration):
    dependencies = [("labor", "0027_alter_officepayrolldeductionpolicy_national_pension_rate")]

    operations = [
        migrations.AlterField(
            model_name="officepayslip",
            name="meal_allowance_pay",
            field=models.BigIntegerField(default=200000),
        ),
        migrations.AlterField(
            model_name="officepayslip",
            name="fuel_allowance_pay",
            field=models.BigIntegerField(default=100000),
        ),
    ]
