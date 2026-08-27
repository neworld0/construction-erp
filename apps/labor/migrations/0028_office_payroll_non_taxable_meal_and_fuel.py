from django.db import migrations, models


class Migration(migrations.Migration):
    dependencies = [("labor", "0027_alter_officepayrolldeductionpolicy_national_pension_rate")]

    operations = [
        migrations.AddField(
            model_name="officepayrolldeductionpolicy",
            name="meal_allowance_default",
            field=models.BigIntegerField(default=200000),
        ),
        migrations.AddField(
            model_name="officepayrolldeductionpolicy",
            name="fuel_allowance_default",
            field=models.BigIntegerField(default=100000),
        ),
    ]
