from django.conf import settings
from django.db import migrations, models
import django.db.models.deletion


class Migration(migrations.Migration):
    dependencies = [
        ("inventory", "0001_initial"),
        migrations.swappable_dependency(settings.AUTH_USER_MODEL),
    ]

    operations = [
        migrations.CreateModel(
            name="ItemCategory",
            fields=[
                ("id", models.BigAutoField(auto_created=True, primary_key=True, serialize=False, verbose_name="ID")),
                ("name", models.CharField(max_length=80, unique=True)),
                ("code", models.CharField(blank=True, default="", max_length=10)),
                ("sort_order", models.IntegerField(default=0)),
                ("is_active", models.BooleanField(default=True)),
                ("created_at", models.DateTimeField(auto_now_add=True)),
                ("updated_at", models.DateTimeField(auto_now=True)),
                (
                    "parent",
                    models.ForeignKey(
                        blank=True,
                        null=True,
                        on_delete=django.db.models.deletion.SET_NULL,
                        related_name="children",
                        to="inventory.itemcategory",
                    ),
                ),
            ],
        ),
        migrations.CreateModel(
            name="ItemCodeSequence",
            fields=[
                ("id", models.BigAutoField(auto_created=True, primary_key=True, serialize=False, verbose_name="ID")),
                ("key", models.CharField(max_length=20, unique=True)),
                ("last_number", models.IntegerField(default=0)),
                ("updated_at", models.DateTimeField(auto_now=True)),
            ],
        ),
        migrations.CreateModel(
            name="UoM",
            fields=[
                ("id", models.BigAutoField(auto_created=True, primary_key=True, serialize=False, verbose_name="ID")),
                ("code", models.CharField(max_length=10, unique=True)),
                ("name", models.CharField(max_length=60)),
                ("is_active", models.BooleanField(default=True)),
                ("created_at", models.DateTimeField(auto_now_add=True)),
                ("updated_at", models.DateTimeField(auto_now=True)),
            ],
        ),
        migrations.CreateModel(
            name="ItemMaster",
            fields=[
                ("id", models.BigAutoField(auto_created=True, primary_key=True, serialize=False, verbose_name="ID")),
                ("code", models.CharField(db_index=True, max_length=30, unique=True)),
                ("name", models.CharField(db_index=True, max_length=120)),
                ("spec", models.TextField(blank=True, default="")),
                ("description", models.TextField(blank=True, default="")),
                ("is_active", models.BooleanField(default=True)),
                ("barcode", models.CharField(blank=True, db_index=True, default="", max_length=60)),
                ("created_at", models.DateTimeField(auto_now_add=True)),
                ("updated_at", models.DateTimeField(auto_now=True)),
                (
                    "category",
                    models.ForeignKey(
                        blank=True,
                        null=True,
                        on_delete=django.db.models.deletion.SET_NULL,
                        related_name="items",
                        to="inventory.itemcategory",
                    ),
                ),
                (
                    "created_by",
                    models.ForeignKey(
                        blank=True,
                        null=True,
                        on_delete=django.db.models.deletion.SET_NULL,
                        related_name="created_item_masters",
                        to=settings.AUTH_USER_MODEL,
                    ),
                ),
                (
                    "uom",
                    models.ForeignKey(
                        on_delete=django.db.models.deletion.PROTECT,
                        related_name="items",
                        to="inventory.uom",
                    ),
                ),
                (
                    "updated_by",
                    models.ForeignKey(
                        blank=True,
                        null=True,
                        on_delete=django.db.models.deletion.SET_NULL,
                        related_name="updated_item_masters",
                        to=settings.AUTH_USER_MODEL,
                    ),
                ),
            ],
        ),
        migrations.AddIndex(
            model_name="uom",
            index=models.Index(fields=["code", "is_active"], name="inventory_uo_code_0a9a7a_idx"),
        ),
        migrations.AddIndex(
            model_name="itemcategory",
            index=models.Index(fields=["name", "is_active"], name="inventory_it_name_e090e7_idx"),
        ),
        migrations.AddIndex(
            model_name="itemcategory",
            index=models.Index(fields=["code"], name="inventory_it_code_3ef282_idx"),
        ),
        migrations.AddIndex(
            model_name="itemmaster",
            index=models.Index(fields=["code", "is_active"], name="inventory_it_code_5c1b75_idx"),
        ),
        migrations.AddIndex(
            model_name="itemmaster",
            index=models.Index(fields=["name"], name="inventory_it_name_9a9db0_idx"),
        ),
        migrations.AddIndex(
            model_name="itemmaster",
            index=models.Index(fields=["barcode"], name="inventory_it_barco_5c0c42_idx"),
        ),
    ]
