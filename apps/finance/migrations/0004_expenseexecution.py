from django.conf import settings
from django.db import migrations, models
import django.db.models.deletion


class Migration(migrations.Migration):
    dependencies = [
        ("finance", "0003_billingreport"),
        migrations.swappable_dependency(settings.AUTH_USER_MODEL),
    ]

    operations = [
        migrations.CreateModel(
            name="ExpenseExecution",
            fields=[
                ("id", models.BigAutoField(auto_created=True, primary_key=True, serialize=False, verbose_name="ID")),
                ("amount_snapshot", models.DecimalField(decimal_places=2, max_digits=16)),
                ("status", models.CharField(choices=[("READY", "CEO 승인 완료"), ("SCHEDULED", "지급 예정"), ("PAID", "지급 완료"), ("CANCELLED", "집행 취소")], db_index=True, default="READY", max_length=16)),
                ("ceo_approved_at", models.DateTimeField(blank=True, null=True)),
                ("scheduled_date", models.DateField(blank=True, null=True)),
                ("paid_date", models.DateField(blank=True, null=True)),
                ("payment_reference", models.CharField(blank=True, default="", max_length=120)),
                ("memo", models.TextField(blank=True, default="")),
                ("created_at", models.DateTimeField(auto_now_add=True)),
                ("updated_at", models.DateTimeField(auto_now=True)),
                ("cash_event", models.OneToOneField(blank=True, null=True, on_delete=django.db.models.deletion.PROTECT, related_name="expense_execution", to="finance.cashevent")),
                ("ceo_approved_by", models.ForeignKey(blank=True, null=True, on_delete=django.db.models.deletion.SET_NULL, related_name="ceo_approved_expense_executions", to=settings.AUTH_USER_MODEL)),
                ("cost_actual", models.OneToOneField(on_delete=django.db.models.deletion.PROTECT, related_name="expense_execution", to="cost.costactual")),
                ("paid_by", models.ForeignKey(blank=True, null=True, on_delete=django.db.models.deletion.SET_NULL, related_name="paid_expense_executions", to=settings.AUTH_USER_MODEL)),
                ("scheduled_by", models.ForeignKey(blank=True, null=True, on_delete=django.db.models.deletion.SET_NULL, related_name="scheduled_expense_executions", to=settings.AUTH_USER_MODEL)),
            ],
            options={"ordering": ["-created_at", "-id"]},
        ),
    ]
