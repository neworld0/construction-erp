from django.conf import settings
from django.db import migrations, models
import django.db.models.deletion


class Migration(migrations.Migration):
    dependencies = [
        ("projects", "0014_rename_projects_bu_project_cost_item_idx_projects_bu_project_83b1ff_idx_and_more"),
        migrations.swappable_dependency(settings.AUTH_USER_MODEL),
    ]

    operations = [
        migrations.CreateModel(
            name="ApprovalPackage",
            fields=[
                ("id", models.BigAutoField(auto_created=True, primary_key=True, serialize=False, verbose_name="ID")),
                ("title", models.CharField(max_length=200)),
                ("reason", models.TextField(blank=True, default="")),
                (
                    "status",
                    models.CharField(
                        choices=[
                            ("draft", "DRAFT"),
                            ("submitted", "SUBMITTED"),
                            ("approved", "APPROVED"),
                            ("rejected", "REJECTED"),
                            ("canceled", "CANCELED"),
                        ],
                        default="draft",
                        max_length=16,
                    ),
                ),
                ("created_at", models.DateTimeField(auto_now_add=True)),
                ("updated_at", models.DateTimeField(auto_now=True)),
                ("submitted_at", models.DateTimeField(blank=True, null=True)),
                ("decided_at", models.DateTimeField(blank=True, null=True)),
                ("decision_note", models.TextField(blank=True, default="")),
                (
                    "created_by",
                    models.ForeignKey(
                        on_delete=django.db.models.deletion.PROTECT,
                        related_name="approval_packages_created",
                        to=settings.AUTH_USER_MODEL,
                    ),
                ),
                (
                    "decided_by",
                    models.ForeignKey(
                        blank=True,
                        null=True,
                        on_delete=django.db.models.deletion.SET_NULL,
                        related_name="approval_packages_decided",
                        to=settings.AUTH_USER_MODEL,
                    ),
                ),
                (
                    "project",
                    models.ForeignKey(on_delete=django.db.models.deletion.CASCADE, to="projects.project"),
                ),
            ],
            options={
                "ordering": ["-created_at"],
            },
        ),
        migrations.CreateModel(
            name="ApprovalPackageItem",
            fields=[
                ("id", models.BigAutoField(auto_created=True, primary_key=True, serialize=False, verbose_name="ID")),
                (
                    "item_type",
                    models.CharField(
                        choices=[
                            ("change_order", "CHANGE_ORDER"),
                            ("wbs_change", "WBS_CHANGE"),
                            ("budget_change", "BUDGET_CHANGE"),
                            ("contract_change", "CONTRACT_CHANGE"),
                        ],
                        max_length=32,
                    ),
                ),
                ("object_id", models.IntegerField()),
                ("status_snapshot", models.CharField(blank=True, default="", max_length=32)),
                ("created_at", models.DateTimeField(auto_now_add=True)),
                (
                    "package",
                    models.ForeignKey(
                        on_delete=django.db.models.deletion.CASCADE,
                        related_name="items",
                        to="projects.approvalpackage",
                    ),
                ),
            ],
            options={
                "indexes": [
                    models.Index(fields=["package", "item_type"], name="projects_ap_package_3a20c6_idx"),
                ],
                "constraints": [
                    models.UniqueConstraint(fields=("package", "item_type", "object_id"), name="uq_approval_package_item"),
                ],
            },
        ),
    ]

