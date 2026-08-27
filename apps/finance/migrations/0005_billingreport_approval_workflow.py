from django.conf import settings
from django.db import migrations, models
import django.db.models.deletion


class Migration(migrations.Migration):
    dependencies = [("finance", "0004_expenseexecution"), migrations.swappable_dependency(settings.AUTH_USER_MODEL)]
    operations = [
        migrations.AlterField(
            model_name="billingreport",
            name="status",
            field=models.CharField(choices=[("DRAFT", "Draft"), ("ENGINEER_INPUT_REQUIRED", "Engineer input required"), ("HQ_APPROVED", "HQ approved"), ("CEO_REVIEW", "CEO review required"), ("REJECTED", "CEO rejected"), ("LOCKED", "Locked")], default="DRAFT", max_length=32),
        ),
        migrations.AddField(model_name="billingreport", name="hq_reviewed_at", field=models.DateTimeField(blank=True, null=True)),
        migrations.AddField(model_name="billingreport", name="ceo_approved_at", field=models.DateTimeField(blank=True, null=True)),
        migrations.AddField(model_name="billingreport", name="ceo_rejected_at", field=models.DateTimeField(blank=True, null=True)),
        migrations.AddField(model_name="billingreport", name="reject_reason", field=models.TextField(blank=True, default="")),
        migrations.AddField(model_name="billingreport", name="locked_at", field=models.DateTimeField(blank=True, null=True)),
        migrations.AddField(model_name="billingreport", name="hq_reviewed_by", field=models.ForeignKey(blank=True, null=True, on_delete=django.db.models.deletion.SET_NULL, related_name="hq_reviewed_billing_reports", to=settings.AUTH_USER_MODEL)),
        migrations.AddField(model_name="billingreport", name="ceo_approved_by", field=models.ForeignKey(blank=True, null=True, on_delete=django.db.models.deletion.SET_NULL, related_name="ceo_approved_billing_reports", to=settings.AUTH_USER_MODEL)),
        migrations.AddField(model_name="billingreport", name="ceo_rejected_by", field=models.ForeignKey(blank=True, null=True, on_delete=django.db.models.deletion.SET_NULL, related_name="ceo_rejected_billing_reports", to=settings.AUTH_USER_MODEL)),
    ]
