from django.db import migrations


class Migration(migrations.Migration):
    dependencies = [
        ("field", "0001_initial"),
    ]

    operations = [
        migrations.RemoveConstraint(
            model_name="dailyreport",
            name="uniq_daily_report_reporter_date",
        ),
    ]
