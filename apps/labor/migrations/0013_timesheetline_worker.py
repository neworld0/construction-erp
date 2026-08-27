from django.db import migrations, models
import django.db.models.deletion


class Migration(migrations.Migration):

    dependencies = [
        ("labor", "0012_laborexcelexportbatch"),
    ]

    operations = [
        migrations.AddField(
            model_name="timesheetline",
            name="worker",
            field=models.ForeignKey(
                blank=True,
                null=True,
                on_delete=django.db.models.deletion.PROTECT,
                related_name="timesheet_lines",
                to="labor.workermaster",
            ),
        ),
    ]
