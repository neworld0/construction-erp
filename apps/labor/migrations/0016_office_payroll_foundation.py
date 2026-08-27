from django.conf import settings
from django.db import migrations, models
import django.db.models.deletion


class Migration(migrations.Migration):
    dependencies = [("labor", "0015_laborcomplianceexport")]

    operations = [
        migrations.CreateModel(
            name="OfficeEmployeeProfile",
            fields=[
                ("id", models.BigAutoField(auto_created=True, primary_key=True, serialize=False, verbose_name="ID")),
                ("employee_no", models.CharField(max_length=40, unique=True)),
                ("department", models.CharField(blank=True, default="", max_length=100)),
                ("active", models.BooleanField(default=True)),
                ("created_at", models.DateTimeField(auto_now_add=True)),
                ("updated_at", models.DateTimeField(auto_now=True)),
                ("user", models.OneToOneField(on_delete=django.db.models.deletion.PROTECT, related_name="office_employee_profile", to=settings.AUTH_USER_MODEL)),
            ],
            options={"ordering": ["employee_no"]},
        ),
        migrations.CreateModel(
            name="OfficePayrollRun",
            fields=[
                ("id", models.BigAutoField(auto_created=True, primary_key=True, serialize=False, verbose_name="ID")),
                ("period_year", models.IntegerField()), ("period_month", models.IntegerField()),
                ("status", models.CharField(choices=[("DRAFT", "임시저장"), ("SUBMITTED", "검토 대기"), ("APPROVED", "확정"), ("PAID", "지급 완료"), ("REJECTED", "반려")], default="DRAFT", max_length=12)),
                ("note", models.TextField(blank=True, default="")), ("submitted_at", models.DateTimeField(blank=True, null=True)),
                ("approved_at", models.DateTimeField(blank=True, null=True)), ("paid_at", models.DateTimeField(blank=True, null=True)),
                ("created_at", models.DateTimeField(auto_now_add=True)), ("updated_at", models.DateTimeField(auto_now=True)),
                ("approved_by", models.ForeignKey(blank=True, null=True, on_delete=django.db.models.deletion.SET_NULL, related_name="office_payroll_runs_approved", to=settings.AUTH_USER_MODEL)),
                ("created_by", models.ForeignKey(on_delete=django.db.models.deletion.PROTECT, related_name="office_payroll_runs_created", to=settings.AUTH_USER_MODEL)),
            ], options={"ordering": ["-period_year", "-period_month", "-id"]},
        ),
        migrations.CreateModel(
            name="OfficePayslip",
            fields=[
                ("id", models.BigAutoField(auto_created=True, primary_key=True, serialize=False, verbose_name="ID")),
                ("base_pay", models.BigIntegerField(default=0)), ("allowance_pay", models.BigIntegerField(default=0)), ("overtime_pay", models.BigIntegerField(default=0)), ("bonus_pay", models.BigIntegerField(default=0)),
                ("income_tax", models.BigIntegerField(default=0)), ("local_income_tax", models.BigIntegerField(default=0)), ("national_pension", models.BigIntegerField(default=0)), ("health_insurance", models.BigIntegerField(default=0)), ("long_term_care", models.BigIntegerField(default=0)), ("employment_insurance", models.BigIntegerField(default=0)), ("other_deduction", models.BigIntegerField(default=0)),
                ("gross_pay", models.BigIntegerField(default=0)), ("total_deduction", models.BigIntegerField(default=0)), ("net_pay", models.BigIntegerField(default=0)), ("issued_at", models.DateTimeField(blank=True, null=True)), ("created_at", models.DateTimeField(auto_now_add=True)), ("updated_at", models.DateTimeField(auto_now=True)),
                ("employee", models.ForeignKey(on_delete=django.db.models.deletion.PROTECT, related_name="payslips", to="labor.officeemployeeprofile")), ("run", models.ForeignKey(on_delete=django.db.models.deletion.CASCADE, related_name="slips", to="labor.officepayrollrun")),
            ], options={"ordering": ["employee__employee_no"]},
        ),
        migrations.AddConstraint(model_name="officepayrollrun", constraint=models.UniqueConstraint(fields=("period_year", "period_month"), name="uniq_office_payroll_run_period")),
        migrations.AddConstraint(model_name="officepayslip", constraint=models.UniqueConstraint(fields=("run", "employee"), name="uniq_office_payslip_run_employee")),
    ]
