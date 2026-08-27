import apps.core.rbac.models
from django.db import migrations, models
import django.db.models.deletion


class Migration(migrations.Migration):
    dependencies = [("inventory", "0011_warehouse_legal_entity")]

    operations = [
        migrations.AlterField(
            model_name="warehouse",
            name="legal_entity",
            field=models.ForeignKey(
                default=apps.core.rbac.models.default_asan_legal_entity_id,
                on_delete=django.db.models.deletion.PROTECT,
                related_name="warehouses",
                to="core.legalentity",
            ),
        ),
    ]
