from django.db import migrations, models


class Migration(migrations.Migration):
    dependencies = [
        ("schedule", "0003_plan_change_request"),
    ]

    operations = [
        migrations.AddField(
            model_name="dailyprogress",
            name="status",
            field=models.CharField(
                max_length=20,
                choices=[
                    ("draft", "Draft"),
                    ("submitted", "Submitted"),
                    ("approved", "Approved"),
                ],
                default="submitted",
            ),
        ),
    ]
