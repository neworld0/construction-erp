from django.db import migrations, models


class Migration(migrations.Migration):
    dependencies = [("labor", "0018_payrollallocationbatch_office_payroll_run")]
    operations = [
        migrations.CreateModel(
            name="OfficeEmployeeNumberSequence",
            fields=[
                ("id", models.BigAutoField(auto_created=True, primary_key=True, serialize=False, verbose_name="ID")),
                ("year", models.IntegerField(unique=True)),
                ("last_number", models.PositiveIntegerField(default=0)),
            ],
        ),
    ]
