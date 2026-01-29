from django.db import migrations, models
import django.db.models.deletion


class Migration(migrations.Migration):
    dependencies = [
        ("master", "0003_master_templates"),
        ("projects", "0011_project_wbs_fields"),
    ]

    operations = [
        migrations.AddField(
            model_name="project",
            name="budget_template",
            field=models.ForeignKey(
                blank=True,
                limit_choices_to={"category": "BUDGET"},
                null=True,
                on_delete=django.db.models.deletion.SET_NULL,
                related_name="projects_budget",
                to="master.mastertemplate",
            ),
        ),
        migrations.AddField(
            model_name="project",
            name="wbs_template",
            field=models.ForeignKey(
                blank=True,
                limit_choices_to={"category": "WBS"},
                null=True,
                on_delete=django.db.models.deletion.SET_NULL,
                related_name="projects_wbs",
                to="master.mastertemplate",
            ),
        ),
    ]
