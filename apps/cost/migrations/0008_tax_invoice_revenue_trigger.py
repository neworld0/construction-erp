from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [("cost", "0007_revenuerecognitionclose")]

    operations = [
        migrations.AlterField(
            model_name="revenuerecognitionclose",
            name="trigger_type",
            field=models.CharField(
                choices=[
                    ("MONTHLY_CLOSE", "Monthly close"),
                    ("PROGRESS_BILLING_CLOSE", "Progress billing close"),
                    ("TAX_INVOICE", "Tax invoice issued"),
                ],
                max_length=32,
            ),
        ),
    ]
