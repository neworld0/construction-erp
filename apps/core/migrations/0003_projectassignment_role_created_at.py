from django.db import migrations, models
import django.utils.timezone


class Migration(migrations.Migration):
    dependencies = [
        ("core", "0002_rbac_models"),
    ]

    operations = [
        migrations.AddField(
            model_name="projectassignment",
            name="role_in_project",
            field=models.CharField(
                blank=True,
                null=True,
                max_length=20,
                choices=[("field", "Field"), ("hq", "HQ")],
            ),
        ),
        migrations.AddField(
            model_name="projectassignment",
            name="created_at",
            field=models.DateTimeField(auto_now_add=True, default=django.utils.timezone.now),
            preserve_default=False,
        ),
    ]
