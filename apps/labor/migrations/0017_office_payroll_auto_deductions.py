from decimal import Decimal

from django.db import migrations, models


class Migration(migrations.Migration):
    dependencies = [("labor", "0016_office_payroll_foundation")]

    operations = [
        migrations.CreateModel(
            name="OfficePayrollDeductionPolicy",
            fields=[
                ("id", models.BigAutoField(auto_created=True, primary_key=True, serialize=False, verbose_name="ID")),
                ("year", models.IntegerField(unique=True)),
                ("national_pension_rate", models.DecimalField(decimal_places=5, default=Decimal("0.04500"), max_digits=7)),
                ("health_insurance_rate", models.DecimalField(decimal_places=5, default=Decimal("0.03595"), max_digits=7)),
                ("long_term_care_rate", models.DecimalField(decimal_places=5, default=Decimal("0.13140"), max_digits=7)),
                ("employment_insurance_rate", models.DecimalField(decimal_places=5, default=Decimal("0.00900"), max_digits=7)),
                ("income_tax_rate", models.DecimalField(decimal_places=5, default=Decimal("0.00000"), max_digits=7)),
                ("created_at", models.DateTimeField(auto_now_add=True)), ("updated_at", models.DateTimeField(auto_now=True)),
            ], options={"ordering": ["-year"]},
        ),
        *[
            migrations.AddField(model_name="officepayslip", name=name, field=models.BigIntegerField(default=0))
            for name in ("auto_income_tax", "auto_local_income_tax", "auto_national_pension", "auto_health_insurance", "auto_long_term_care", "auto_employment_insurance")
        ],
        migrations.AddField(model_name="officepayslip", name="auto_calculated_at", field=models.DateTimeField(blank=True, null=True)),
    ]
