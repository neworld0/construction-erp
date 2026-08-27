from django.conf import settings
from django.db import migrations, models
import django.db.models.deletion


class Migration(migrations.Migration):
    dependencies = [("projects", "0017_remove_budgetitem_uq_budgetitem_project_costitem"), migrations.swappable_dependency(settings.AUTH_USER_MODEL)]
    operations = [migrations.CreateModel(name="ProjectOperationalTestDateWindow", fields=[
        ("id", models.BigAutoField(auto_created=True, primary_key=True, serialize=False, verbose_name="ID")),
        ("start_date", models.DateField()), ("end_date", models.DateField()), ("expires_on", models.DateField()),
        ("reason", models.TextField()), ("is_enabled", models.BooleanField(default=True)),
        ("created_at", models.DateTimeField(auto_now_add=True)), ("updated_at", models.DateTimeField(auto_now=True)),
        ("configured_by", models.ForeignKey(on_delete=django.db.models.deletion.PROTECT, related_name="configured_operational_test_date_windows", to=settings.AUTH_USER_MODEL)),
        ("project", models.OneToOneField(on_delete=django.db.models.deletion.CASCADE, related_name="operational_test_date_window", to="projects.project")),
    ])]
