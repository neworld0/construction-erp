from django.db import migrations, models
import django.db.models.deletion


class Migration(migrations.Migration):
    dependencies = [
        ("labor", "0013_timesheetline_worker"),
    ]

    operations = [
        migrations.AddField(
            model_name="laborratetable",
            name="worker",
            field=models.ForeignKey(
                blank=True,
                null=True,
                on_delete=django.db.models.deletion.SET_NULL,
                related_name="labor_rates",
                to="labor.workermaster",
            ),
        ),
        migrations.AddField(
            model_name="timesheetline",
            name="applied_rate",
            field=models.ForeignKey(
                blank=True,
                null=True,
                on_delete=django.db.models.deletion.SET_NULL,
                related_name="applied_timesheet_lines",
                to="labor.laborratetable",
            ),
        ),
        migrations.AddField(
            model_name="timesheetline",
            name="applied_rate_effective_from",
            field=models.DateField(blank=True, null=True),
        ),
        migrations.AddField(
            model_name="timesheetline",
            name="applied_rate_resolved_at",
            field=models.DateTimeField(blank=True, null=True),
        ),
        migrations.AddField(
            model_name="timesheetline",
            name="applied_rate_scope",
            field=models.CharField(blank=True, default="", max_length=24),
        ),
    ]
