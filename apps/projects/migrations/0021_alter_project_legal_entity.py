import apps.core.rbac.models
from django.db import migrations, models
import django.db.models.deletion


class Migration(migrations.Migration):
    dependencies = [("projects", "0020_project_legal_entity_and_code_sequence")]

    operations = [
        migrations.AlterField(
            model_name="project",
            name="legal_entity",
            field=models.ForeignKey(
                default=apps.core.rbac.models.default_asan_legal_entity_id,
                on_delete=django.db.models.deletion.PROTECT,
                related_name="projects",
                to="core.legalentity",
            ),
        ),
    ]
