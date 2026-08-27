from django.db import migrations, models
import django.db.models.deletion


class Migration(migrations.Migration):
    dependencies = [("labor", "0017_office_payroll_auto_deductions")]

    operations = [
        migrations.AddField(
            model_name="payrollallocationbatch",
            name="office_payroll_run",
            field=models.OneToOneField(blank=True, null=True, on_delete=django.db.models.deletion.PROTECT, related_name="project_allocation_batch", to="labor.officepayrollrun"),
        ),
    ]
