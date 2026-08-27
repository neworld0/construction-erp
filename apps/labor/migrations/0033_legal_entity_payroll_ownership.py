from django.db import migrations, models
import django.db.models.deletion


def attribute_existing_office_payroll_to_asan(apps, schema_editor):
    LegalEntity = apps.get_model("core", "LegalEntity")
    OfficeEmployeeProfile = apps.get_model("labor", "OfficeEmployeeProfile")
    OfficePayrollRun = apps.get_model("labor", "OfficePayrollRun")
    PayrollAllocationBatch = apps.get_model("labor", "PayrollAllocationBatch")
    asan = LegalEntity.objects.get(code="ASAN")
    OfficeEmployeeProfile.objects.filter(employment_legal_entity__isnull=True).update(employment_legal_entity=asan)
    OfficePayrollRun.objects.filter(legal_entity__isnull=True).update(legal_entity=asan)
    PayrollAllocationBatch.objects.filter(legal_entity__isnull=True).update(legal_entity=asan)


class Migration(migrations.Migration):
    dependencies = [
        ("core", "0006_projectassignment_assignment_type"),
        ("labor", "0032_alter_officepayrollrun_status"),
    ]

    operations = [
        migrations.AddField(
            model_name="officeemployeeprofile",
            name="employment_legal_entity",
            field=models.ForeignKey(null=True, on_delete=django.db.models.deletion.PROTECT, related_name="office_employees", to="core.legalentity"),
        ),
        migrations.AddField(
            model_name="officepayrollrun",
            name="legal_entity",
            field=models.ForeignKey(null=True, on_delete=django.db.models.deletion.PROTECT, related_name="office_payroll_runs", to="core.legalentity"),
        ),
        migrations.AddField(
            model_name="payrollallocationbatch",
            name="legal_entity",
            field=models.ForeignKey(null=True, on_delete=django.db.models.deletion.PROTECT, related_name="payroll_allocation_batches", to="core.legalentity"),
        ),
        migrations.RunPython(attribute_existing_office_payroll_to_asan, migrations.RunPython.noop),
        migrations.AlterField(
            model_name="officeemployeeprofile",
            name="employment_legal_entity",
            field=models.ForeignKey(on_delete=django.db.models.deletion.PROTECT, related_name="office_employees", to="core.legalentity"),
        ),
        migrations.AlterField(
            model_name="officepayrollrun",
            name="legal_entity",
            field=models.ForeignKey(on_delete=django.db.models.deletion.PROTECT, related_name="office_payroll_runs", to="core.legalentity"),
        ),
        migrations.AlterField(
            model_name="payrollallocationbatch",
            name="legal_entity",
            field=models.ForeignKey(on_delete=django.db.models.deletion.PROTECT, related_name="payroll_allocation_batches", to="core.legalentity"),
        ),
        migrations.RemoveConstraint(model_name="officepayrollrun", name="uniq_active_office_payroll_run_period"),
        migrations.AddConstraint(
            model_name="officepayrollrun",
            constraint=models.UniqueConstraint(
                condition=models.Q(("status", "VOID"), _negated=True),
                fields=("legal_entity", "period_year", "period_month"),
                name="uniq_active_office_payroll_run_entity_period",
            ),
        ),
        migrations.RemoveConstraint(model_name="payrollallocationbatch", name="uniq_payroll_batch_period"),
        migrations.AddConstraint(
            model_name="payrollallocationbatch",
            constraint=models.UniqueConstraint(fields=("legal_entity", "period_year", "period_month"), name="uniq_payroll_batch_entity_period"),
        ),
    ]
