from django.db import migrations, models


class Migration(migrations.Migration):
    dependencies = [("labor", "0029_merge_office_payroll_recurring_allowances")]

    operations = [
        migrations.AddField(
            model_name="officeemployeeprofile",
            name="birth_date_encrypted",
            field=models.CharField(blank=True, default="", max_length=255),
        ),
        migrations.AddField(
            model_name="officeemployeeprofile",
            name="birth_date_masked",
            field=models.CharField(blank=True, default="", max_length=16),
        ),
        migrations.AddField(
            model_name="officepayslip",
            name="auto_national_pension_eligible",
            field=models.BooleanField(default=True),
        ),
    ]
