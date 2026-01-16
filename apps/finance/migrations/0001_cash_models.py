from django.conf import settings
from django.db import migrations, models
import django.db.models.deletion


class Migration(migrations.Migration):
    initial = True

    dependencies = [
        ("contracts", "0002_contractsnapshot"),
        migrations.swappable_dependency(settings.AUTH_USER_MODEL),
        ("projects", "0001_initial"),
    ]

    operations = [
        migrations.CreateModel(
            name="CashAccount",
            fields=[
                (
                    "id",
                    models.BigAutoField(
                        auto_created=True, primary_key=True, serialize=False, verbose_name="ID"
                    ),
                ),
                ("name", models.CharField(max_length=255)),
                ("bank_name", models.CharField(blank=True, default="", max_length=255)),
                ("masked_account_no", models.CharField(blank=True, default="", max_length=100)),
                ("is_active", models.BooleanField(default=True)),
            ],
            options={},
        ),
        migrations.CreateModel(
            name="CashEvent",
            fields=[
                (
                    "id",
                    models.BigAutoField(
                        auto_created=True, primary_key=True, serialize=False, verbose_name="ID"
                    ),
                ),
                (
                    "event_type",
                    models.CharField(
                        choices=[("in", "In"), ("out", "Out")], max_length=10
                    ),
                ),
                (
                    "status",
                    models.CharField(
                        choices=[("planned", "Planned"), ("confirmed", "Confirmed")],
                        max_length=20,
                    ),
                ),
                ("amount", models.DecimalField(decimal_places=2, max_digits=16)),
                ("event_date", models.DateField()),
                ("description", models.TextField()),
                ("created_at", models.DateTimeField(auto_now_add=True)),
                (
                    "account",
                    models.ForeignKey(
                        blank=True,
                        null=True,
                        on_delete=django.db.models.deletion.SET_NULL,
                        to="finance.cashaccount",
                    ),
                ),
                (
                    "contract_snapshot",
                    models.ForeignKey(
                        blank=True,
                        null=True,
                        on_delete=django.db.models.deletion.SET_NULL,
                        related_name="cash_events",
                        to="contracts.contractsnapshot",
                    ),
                ),
                (
                    "created_by",
                    models.ForeignKey(
                        on_delete=django.db.models.deletion.PROTECT,
                        to=settings.AUTH_USER_MODEL,
                    ),
                ),
                (
                    "project",
                    models.ForeignKey(
                        on_delete=django.db.models.deletion.PROTECT, to="projects.project"
                    ),
                ),
            ],
            options={},
        ),
        migrations.AddIndex(
            model_name="cashevent",
            index=models.Index(fields=["project", "event_date"], name="cash_event_project_date_idx"),
        ),
        migrations.AddIndex(
            model_name="cashevent",
            index=models.Index(fields=["status", "event_date"], name="cash_event_status_date_idx"),
        ),
    ]
