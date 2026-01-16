from django.db import migrations, models
import django.db.models.deletion


class Migration(migrations.Migration):
    dependencies = [
        ("contracts", "0002_contractsnapshot"),
        ("cost", "0003_revenue_recognition"),
    ]

    operations = [
        migrations.AlterField(
            model_name="revenuerecognition",
            name="contract_snapshot",
            field=models.ForeignKey(
                blank=True,
                null=True,
                on_delete=django.db.models.deletion.SET_NULL,
                related_name="revenue_recognitions",
                to="contracts.contractsnapshot",
            ),
        ),
    ]
