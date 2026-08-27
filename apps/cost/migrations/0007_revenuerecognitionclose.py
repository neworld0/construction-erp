from django.conf import settings
from django.db import migrations, models
import django.db.models.deletion


class Migration(migrations.Migration):
    dependencies = [
        ("cost", "0006_costitemalias"),
        migrations.swappable_dependency(settings.AUTH_USER_MODEL),
    ]

    operations = [
        migrations.CreateModel(
            name="RevenueRecognitionClose",
            fields=[
                ("id", models.BigAutoField(auto_created=True, primary_key=True, serialize=False, verbose_name="ID")),
                ("recognition_date", models.DateField()),
                ("period_year", models.IntegerField()),
                ("period_month", models.IntegerField()),
                ("trigger_type", models.CharField(choices=[("MONTHLY_CLOSE", "Monthly close"), ("PROGRESS_BILLING_CLOSE", "Progress billing close")], max_length=32)),
                ("approved_progress_percent", models.DecimalField(decimal_places=3, max_digits=6)),
                ("contract_amount_snapshot", models.DecimalField(decimal_places=2, max_digits=16)),
                ("cumulative_earned_revenue", models.DecimalField(decimal_places=2, max_digits=16)),
                ("previously_recognized_revenue", models.DecimalField(decimal_places=2, default=0, max_digits=16)),
                ("recognized_revenue_amount", models.DecimalField(decimal_places=2, default=0, max_digits=16)),
                ("cumulative_cost_snapshot", models.DecimalField(decimal_places=2, default=0, max_digits=16)),
                ("previously_recognized_cost", models.DecimalField(decimal_places=2, default=0, max_digits=16)),
                ("recognized_cost_amount", models.DecimalField(decimal_places=2, default=0, max_digits=16)),
                ("status", models.CharField(default="RECOGNIZED", max_length=20)),
                ("memo", models.TextField(blank=True, default="")),
                ("created_at", models.DateTimeField(auto_now_add=True)),
                ("created_by", models.ForeignKey(null=True, on_delete=django.db.models.deletion.SET_NULL, related_name="revenue_recognition_closes", to=settings.AUTH_USER_MODEL)),
                ("project", models.ForeignKey(on_delete=django.db.models.deletion.PROTECT, to="projects.project")),
                ("revenue_recognition", models.OneToOneField(on_delete=django.db.models.deletion.PROTECT, related_name="close_snapshot", to="cost.revenuerecognition")),
            ],
            options={"ordering": ["-recognition_date", "-id"]},
        ),
        migrations.AddConstraint(
            model_name="revenuerecognitionclose",
            constraint=models.UniqueConstraint(fields=("project", "period_year", "period_month", "trigger_type"), name="uniq_revenue_recognition_close_period"),
        ),
    ]
