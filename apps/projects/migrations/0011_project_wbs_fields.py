from django.db import migrations, models


class Migration(migrations.Migration):
    dependencies = [
        ("projects", "0010_update_budgetitem_fields"),
    ]

    operations = [
        migrations.AddField(
            model_name="project",
            name="site_address",
            field=models.CharField(blank=True, default="", max_length=255),
        ),
        migrations.AddField(
            model_name="project",
            name="project_type",
            field=models.CharField(
                choices=[
                    ("landscape", "Landscape"),
                    ("civil", "Civil"),
                    ("arch", "Arch"),
                ],
                default="landscape",
                max_length=20,
            ),
        ),
        migrations.AddField(
            model_name="wbsitem",
            name="baseline_version",
            field=models.IntegerField(default=1),
        ),
        migrations.AddField(
            model_name="wbsitem",
            name="is_baseline",
            field=models.BooleanField(default=True),
        ),
    ]
