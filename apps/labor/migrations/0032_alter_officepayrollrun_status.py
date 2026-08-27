from django.db import migrations, models


class Migration(migrations.Migration):
    dependencies = [("labor", "0031_office_payroll_run_void")]

    operations = [
        migrations.AlterField(
            model_name="officepayrollrun",
            name="status",
            field=models.CharField(
                choices=[
                    ("DRAFT", "임시저장"),
                    ("SUBMITTED", "검토 대기"),
                    ("APPROVED", "확정"),
                    ("PAID", "지급 완료"),
                    ("REJECTED", "반려"),
                    ("VOID", "폐기"),
                ],
                default="DRAFT",
                max_length=12,
            ),
        ),
    ]
