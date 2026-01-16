from django.db import migrations, models


class Migration(migrations.Migration):
    initial = True

    dependencies = []

    operations = [
        migrations.CreateModel(
            name="CostItem",
            fields=[
                (
                    "id",
                    models.BigAutoField(
                        auto_created=True, primary_key=True, serialize=False, verbose_name="ID"
                    ),
                ),
                ("code", models.CharField(max_length=50, unique=True)),
                ("name", models.CharField(max_length=255)),
                (
                    "category",
                    models.CharField(
                        choices=[
                            ("labor", "Labor"),
                            ("material", "Material"),
                            ("equip", "Equip"),
                            ("subcon", "Subcon"),
                            ("other", "Other"),
                        ],
                        max_length=20,
                    ),
                ),
                ("unit", models.CharField(blank=True, default="", max_length=30)),
                ("is_direct", models.BooleanField(default=True)),
                ("is_active", models.BooleanField(default=True)),
                ("sort_order", models.IntegerField(default=0)),
                ("created_at", models.DateTimeField(auto_now_add=True)),
                ("updated_at", models.DateTimeField(auto_now=True)),
            ],
            options={
                "ordering": ["sort_order", "-created_at"],
            },
        ),
    ]
