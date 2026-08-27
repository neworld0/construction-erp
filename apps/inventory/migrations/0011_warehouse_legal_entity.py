from django.db import migrations, models
import django.db.models.deletion


def attribute_existing_warehouses_to_asan(apps, schema_editor):
    LegalEntity = apps.get_model("core", "LegalEntity")
    Warehouse = apps.get_model("inventory", "Warehouse")
    asan = LegalEntity.objects.get(code="ASAN")
    Warehouse.objects.filter(legal_entity__isnull=True).update(legal_entity=asan)


class Migration(migrations.Migration):

    dependencies = [
        ("core", "0005_organizationgroup_legalentity_legalentitylicense_and_membership"),
        ("inventory", "0010_alter_issuetowork_status"),
    ]

    operations = [
        migrations.AddField(
            model_name="warehouse",
            name="legal_entity",
            field=models.ForeignKey(
                null=True,
                on_delete=django.db.models.deletion.PROTECT,
                related_name="warehouses",
                to="core.legalentity",
            ),
        ),
        migrations.RunPython(attribute_existing_warehouses_to_asan, migrations.RunPython.noop),
        migrations.AlterField(
            model_name="warehouse",
            name="legal_entity",
            field=models.ForeignKey(
                on_delete=django.db.models.deletion.PROTECT,
                related_name="warehouses",
                to="core.legalentity",
            ),
        ),
    ]
