from django.db import migrations, models
import django.db.models.deletion


class Migration(migrations.Migration):
    dependencies = [
        ("contracts", "0001_initial"),
        ("projects", "0001_initial"),
    ]

    operations = [
        migrations.CreateModel(
            name="ContractSnapshot",
            fields=[
                (
                    "id",
                    models.BigAutoField(
                        auto_created=True, primary_key=True, serialize=False, verbose_name="ID"
                    ),
                ),
                ("version_no", models.IntegerField(default=1)),
                ("base_contract_amount", models.DecimalField(decimal_places=2, max_digits=16)),
                ("start_date", models.DateField(blank=True, null=True)),
                ("end_date", models.DateField(blank=True, null=True)),
                ("is_active", models.BooleanField(default=True)),
                ("created_at", models.DateTimeField(auto_now_add=True)),
                (
                    "project",
                    models.ForeignKey(on_delete=django.db.models.deletion.PROTECT, to="projects.project"),
                ),
                (
                    "source_change",
                    models.ForeignKey(
                        blank=True,
                        null=True,
                        on_delete=django.db.models.deletion.SET_NULL,
                        related_name="snapshots",
                        to="contracts.contractchange",
                    ),
                ),
            ],
            options={},
        ),
        migrations.AddConstraint(
            model_name="contractsnapshot",
            constraint=models.UniqueConstraint(
                fields=("project", "version_no"), name="uniq_contract_snapshot_version"
            ),
        ),
        migrations.AddIndex(
            model_name="contractsnapshot",
            index=models.Index(fields=["project", "is_active"], name="contract_snapshot_active_idx"),
        ),
    ]
