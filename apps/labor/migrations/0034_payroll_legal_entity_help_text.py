from django.db import migrations, models
import django.db.models.deletion


class Migration(migrations.Migration):
    dependencies = [("labor", "0033_legal_entity_payroll_ownership")]

    operations = [
        migrations.AlterField(
            model_name="officeemployeeprofile",
            name="employment_legal_entity",
            field=models.ForeignKey(
                help_text="근로계약·급여·원천세·4대보험을 부담하는 고용 법인입니다.",
                on_delete=django.db.models.deletion.PROTECT,
                related_name="office_employees",
                to="core.legalentity",
            ),
        ),
        migrations.AlterField(
            model_name="officepayrollrun",
            name="legal_entity",
            field=models.ForeignKey(
                help_text="본사 직원 급여를 지급하는 고용 법인입니다.",
                on_delete=django.db.models.deletion.PROTECT,
                related_name="office_payroll_runs",
                to="core.legalentity",
            ),
        ),
        migrations.AlterField(
            model_name="payrollallocationbatch",
            name="legal_entity",
            field=models.ForeignKey(
                help_text="이 급여 원가를 부담하는 고용 법인입니다.",
                on_delete=django.db.models.deletion.PROTECT,
                related_name="payroll_allocation_batches",
                to="core.legalentity",
            ),
        ),
    ]
