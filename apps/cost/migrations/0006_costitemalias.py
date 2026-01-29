from django.conf import settings
from django.db import migrations, models
import django.db.models.deletion
import django.db.models.constraints
import django.db.models.expressions


class Migration(migrations.Migration):
    dependencies = [
        ("cost", "0005_costitem_cbs_fields"),
    ]

    operations = [
        migrations.CreateModel(
            name="CostItemAlias",
            fields=[
                ("id", models.BigAutoField(auto_created=True, primary_key=True, serialize=False, verbose_name="ID")),
                ("alias", models.CharField(max_length=120)),
                ("is_primary", models.BooleanField(default=True)),
                ("note", models.TextField(blank=True, default="")),
                ("created_at", models.DateTimeField(auto_now_add=True)),
                ("updated_at", models.DateTimeField(auto_now=True)),
                (
                    "cost_item",
                    models.ForeignKey(on_delete=django.db.models.deletion.CASCADE, related_name="aliases", to="cost.costitem"),
                ),
                (
                    "created_by",
                    models.ForeignKey(
                        blank=True,
                        null=True,
                        on_delete=django.db.models.deletion.SET_NULL,
                        related_name="cost_item_aliases",
                        to=settings.AUTH_USER_MODEL,
                    ),
                ),
            ],
            options={
                "ordering": ["-updated_at"],
            },
        ),
        migrations.AddConstraint(
            model_name="costitemalias",
            constraint=models.UniqueConstraint(
                condition=models.Q(("is_primary", True)),
                fields=("cost_item",),
                name="uniq_costitem_primary_alias",
            ),
        ),
        migrations.AddConstraint(
            model_name="costitemalias",
            constraint=models.UniqueConstraint(
                fields=("cost_item", "alias"),
                name="uniq_costitem_alias",
            ),
        ),
    ]
