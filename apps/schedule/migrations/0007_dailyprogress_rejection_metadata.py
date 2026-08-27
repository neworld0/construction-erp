from django.conf import settings
from django.db import migrations, models
import django.db.models.deletion


class Migration(migrations.Migration):

    dependencies = [
        ("schedule", "0006_progresscorrectionrequest_dailyprogress_voided"),
    ]

    operations = [
        migrations.AddField(
            model_name="dailyprogress",
            name="approved_at",
            field=models.DateTimeField(blank=True, null=True),
        ),
        migrations.AddField(
            model_name="dailyprogress",
            name="approved_by",
            field=models.ForeignKey(blank=True, null=True, on_delete=django.db.models.deletion.SET_NULL, related_name="approved_daily_progresses", to=settings.AUTH_USER_MODEL),
        ),
        migrations.AddField(
            model_name="dailyprogress",
            name="reject_reason",
            field=models.TextField(blank=True, default=""),
        ),
        migrations.AddField(
            model_name="dailyprogress",
            name="rejected_at",
            field=models.DateTimeField(blank=True, null=True),
        ),
        migrations.AddField(
            model_name="dailyprogress",
            name="rejected_by",
            field=models.ForeignKey(blank=True, null=True, on_delete=django.db.models.deletion.SET_NULL, related_name="rejected_daily_progresses", to=settings.AUTH_USER_MODEL),
        ),
        migrations.AlterField(
            model_name="dailyprogress",
            name="status",
            field=models.CharField(choices=[("draft", "Draft"), ("submitted", "Submitted"), ("approved", "Approved"), ("rejected", "Rejected"), ("voided", "Voided")], default="submitted", max_length=20),
        ),
    ]
