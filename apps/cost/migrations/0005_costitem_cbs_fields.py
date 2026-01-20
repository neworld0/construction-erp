from django.db import migrations, models


class Migration(migrations.Migration):
    dependencies = [
        ("cost", "0004_contractsnapshot_fk"),
    ]

    operations = [
        migrations.AddField(
            model_name="costitem",
            name="cost_type",
            field=models.CharField(blank=True, default="", max_length=1),
        ),
        migrations.AddField(
            model_name="costitem",
            name="work_type",
            field=models.CharField(blank=True, default="", max_length=2),
        ),
    ]
