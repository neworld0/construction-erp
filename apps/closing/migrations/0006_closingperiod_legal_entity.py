from django.db import migrations, models
import django.db.models.deletion


def attribute_existing_periods_to_asan(apps, schema_editor):
    LegalEntity = apps.get_model("core", "LegalEntity")
    ClosingPeriod = apps.get_model("closing", "ClosingPeriod")
    asan = LegalEntity.objects.get(code="ASAN")
    ClosingPeriod.objects.filter(legal_entity__isnull=True).update(legal_entity=asan)


class Migration(migrations.Migration):
    dependencies = [
        ("core", "0006_projectassignment_assignment_type"),
        ("closing", "0005_closingperiod_approval_policy"),
    ]

    operations = [
        migrations.AddField(model_name="closingperiod", name="legal_entity", field=models.ForeignKey(null=True, on_delete=django.db.models.deletion.PROTECT, related_name="closing_periods", to="core.legalentity")),
        migrations.RunPython(attribute_existing_periods_to_asan, migrations.RunPython.noop),
        migrations.AlterField(model_name="closingperiod", name="legal_entity", field=models.ForeignKey(on_delete=django.db.models.deletion.PROTECT, related_name="closing_periods", to="core.legalentity")),
        migrations.RemoveConstraint(model_name="closingperiod", name="uniq_closing_period_year_month"),
        migrations.AddConstraint(model_name="closingperiod", constraint=models.UniqueConstraint(fields=("legal_entity", "year", "month"), name="uniq_closing_period_entity_year_month")),
    ]
