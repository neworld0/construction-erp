from django.conf import settings
from django.db import migrations, models
import django.db.models.deletion


class Migration(migrations.Migration):
    dependencies = [("labor", "0030_office_employee_birth_date_national_pension")]

    operations = [
        migrations.AddField(
            model_name="officepayrollrun",
            name="voided_at",
            field=models.DateTimeField(blank=True, null=True),
        ),
        migrations.AddField(
            model_name="officepayrollrun",
            name="voided_by",
            field=models.ForeignKey(
                blank=True,
                null=True,
                on_delete=django.db.models.deletion.SET_NULL,
                related_name="office_payroll_runs_voided",
                to=settings.AUTH_USER_MODEL,
            ),
        ),
        migrations.RemoveConstraint(
            model_name="officepayrollrun",
            name="uniq_office_payroll_run_period",
        ),
        migrations.AddConstraint(
            model_name="officepayrollrun",
            constraint=models.UniqueConstraint(
                condition=~models.Q(("status", "VOID")),
                fields=("period_year", "period_month"),
                name="uniq_active_office_payroll_run_period",
            ),
        ),
    ]
