from django.db import migrations, models
import django.db.models.deletion


def attribute_existing_projects_to_asan(apps, schema_editor):
    LegalEntity = apps.get_model("core", "LegalEntity")
    Project = apps.get_model("projects", "Project")
    asan = LegalEntity.objects.get(code="ASAN")
    Project.objects.filter(legal_entity__isnull=True).update(legal_entity=asan)


class Migration(migrations.Migration):

    dependencies = [
        ("core", "0005_organizationgroup_legalentity_legalentitylicense_and_membership"),
        ("projects", "0019_project_requires_ceo_billing_approval"),
    ]

    operations = [
        migrations.AddField(
            model_name="project",
            name="legal_entity",
            field=models.ForeignKey(
                null=True,
                on_delete=django.db.models.deletion.PROTECT,
                related_name="projects",
                to="core.legalentity",
            ),
        ),
        migrations.RunPython(attribute_existing_projects_to_asan, migrations.RunPython.noop),
        migrations.AlterField(
            model_name="project",
            name="legal_entity",
            field=models.ForeignKey(
                on_delete=django.db.models.deletion.PROTECT,
                related_name="projects",
                to="core.legalentity",
            ),
        ),
        migrations.CreateModel(
            name="ProjectCodeSequence",
            fields=[
                ("id", models.BigAutoField(auto_created=True, primary_key=True, serialize=False, verbose_name="ID")),
                ("project_type", models.CharField(choices=[("landscape", "Landscape"), ("civil", "Civil"), ("arch", "Arch")], max_length=20)),
                ("year", models.PositiveSmallIntegerField()),
                ("last_number", models.PositiveIntegerField(default=0)),
                ("legal_entity", models.ForeignKey(on_delete=django.db.models.deletion.PROTECT, related_name="project_code_sequences", to="core.legalentity")),
            ],
            options={
                "constraints": [
                    models.UniqueConstraint(fields=("legal_entity", "project_type", "year"), name="uniq_project_code_sequence_entity_type_year"),
                ],
            },
        ),
    ]
