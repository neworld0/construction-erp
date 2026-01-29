from django.conf import settings
from django.db import migrations, models
import django.db.models.deletion


class Migration(migrations.Migration):
    dependencies = [
        ("inventory", "0003_inventoryledger_stock_and_more"),
        migrations.swappable_dependency(settings.AUTH_USER_MODEL),
        ("projects", "0005_wbsitem"),
    ]

    operations = [
        migrations.CreateModel(
            name="TransferNumberSequence",
            fields=[
                ("id", models.BigAutoField(auto_created=True, primary_key=True, serialize=False, verbose_name="ID")),
                ("key", models.CharField(max_length=20, unique=True)),
                ("last_number", models.IntegerField(default=0)),
                ("updated_at", models.DateTimeField(auto_now=True)),
            ],
        ),
        migrations.CreateModel(
            name="Transfer",
            fields=[
                ("id", models.BigAutoField(auto_created=True, primary_key=True, serialize=False, verbose_name="ID")),
                ("transfer_no", models.CharField(db_index=True, max_length=30, unique=True)),
                ("direction", models.CharField(choices=[("HQ_TO_SITE", "HQ_TO_SITE"), ("SITE_TO_HQ", "SITE_TO_HQ")], max_length=20)),
                ("tx_date", models.DateField()),
                ("status", models.CharField(choices=[("DRAFT", "DRAFT"), ("SUBMITTED", "SUBMITTED"), ("ISSUED", "ISSUED"), ("RECEIVED", "RECEIVED"), ("CANCELLED", "CANCELLED")], default="DRAFT", max_length=16)),
                ("note", models.TextField(blank=True, default="")),
                ("submitted_at", models.DateTimeField(blank=True, null=True)),
                ("issued_at", models.DateTimeField(blank=True, null=True)),
                ("received_at", models.DateTimeField(blank=True, null=True)),
                ("cancelled_at", models.DateTimeField(blank=True, null=True)),
                ("created_at", models.DateTimeField(auto_now_add=True)),
                ("updated_at", models.DateTimeField(auto_now=True)),
                ("created_by", models.ForeignKey(on_delete=django.db.models.deletion.PROTECT, related_name="created_transfers", to=settings.AUTH_USER_MODEL)),
                ("from_location", models.ForeignKey(blank=True, null=True, on_delete=django.db.models.deletion.PROTECT, related_name="transfer_out", to="inventory.location")),
                ("from_warehouse", models.ForeignKey(on_delete=django.db.models.deletion.PROTECT, related_name="transfer_out", to="inventory.warehouse")),
                ("project", models.ForeignKey(blank=True, null=True, on_delete=django.db.models.deletion.SET_NULL, related_name="transfers", to="projects.project")),
                ("to_location", models.ForeignKey(blank=True, null=True, on_delete=django.db.models.deletion.PROTECT, related_name="transfer_in", to="inventory.location")),
                ("to_warehouse", models.ForeignKey(on_delete=django.db.models.deletion.PROTECT, related_name="transfer_in", to="inventory.warehouse")),
            ],
            options={
                "indexes": [
                    models.Index(fields=["project", "status"], name="inventory_t_project_3a1cfb_idx"),
                    models.Index(fields=["tx_date", "status"], name="inventory_t_tx_date_3e50aa_idx"),
                ],
            },
        ),
        migrations.CreateModel(
            name="TransferLine",
            fields=[
                ("id", models.BigAutoField(auto_created=True, primary_key=True, serialize=False, verbose_name="ID")),
                ("qty", models.DecimalField(decimal_places=3, max_digits=18)),
                ("note", models.CharField(blank=True, default="", max_length=255)),
                ("item", models.ForeignKey(on_delete=django.db.models.deletion.PROTECT, related_name="transfer_lines", to="inventory.itemmaster")),
                ("transfer", models.ForeignKey(on_delete=django.db.models.deletion.CASCADE, related_name="lines", to="inventory.transfer")),
                ("uom", models.ForeignKey(on_delete=django.db.models.deletion.PROTECT, to="inventory.uom")),
            ],
            options={
                "indexes": [
                    models.Index(fields=["transfer", "item"], name="inventory_t_transfer_21960b_idx"),
                ],
                "constraints": [
                    models.UniqueConstraint(fields=["transfer", "item"], name="uq_transfer_line_item"),
                ],
            },
        ),
    ]
