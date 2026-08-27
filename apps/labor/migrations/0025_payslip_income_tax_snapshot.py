from django.db import migrations, models
import django.db.models.deletion


class Migration(migrations.Migration):
    dependencies = [("labor", "0024_child_tax_credit")]

    operations = [
        migrations.AddField(
            model_name="officepayslip",
            name="auto_child_tax_credit",
            field=models.BigIntegerField(default=0),
        ),
        migrations.AddField(
            model_name="officepayslip",
            name="auto_income_tax_table_version",
            field=models.ForeignKey(blank=True, null=True, on_delete=django.db.models.deletion.SET_NULL, related_name="calculated_payslips", to="labor.incometaxtableversion"),
        ),
        migrations.AddField(
            model_name="officepayslip",
            name="auto_tax_child_count_8_to_20",
            field=models.PositiveSmallIntegerField(default=0),
        ),
        migrations.AddField(
            model_name="officepayslip",
            name="auto_tax_dependent_count",
            field=models.PositiveSmallIntegerField(default=1),
        ),
        migrations.AddField(
            model_name="officepayslip",
            name="auto_tax_withholding_ratio",
            field=models.PositiveSmallIntegerField(default=100),
        ),
    ]
