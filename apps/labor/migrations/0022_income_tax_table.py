from django.conf import settings
from django.db import migrations, models
import django.db.models.deletion

class Migration(migrations.Migration):
    dependencies = [("labor", "0021_rename_office_payroll_correction_index"), migrations.swappable_dependency(settings.AUTH_USER_MODEL)]
    operations = [
        migrations.AddField(model_name="officeemployeeprofile", name="tax_dependent_count", field=models.PositiveSmallIntegerField(default=1)),
        migrations.AddField(model_name="officeemployeeprofile", name="tax_withholding_ratio", field=models.PositiveSmallIntegerField(default=100, help_text="근로소득 간이세액표 원천징수 선택비율(80/100/120)")),
        migrations.CreateModel(name="IncomeTaxTableVersion", fields=[("id", models.BigAutoField(auto_created=True, primary_key=True, serialize=False, verbose_name="ID")), ("effective_from", models.DateField(unique=True)), ("source_name", models.CharField(max_length=255)), ("is_active", models.BooleanField(default=False)), ("created_at", models.DateTimeField(auto_now_add=True)), ("created_by", models.ForeignKey(blank=True, null=True, on_delete=django.db.models.deletion.SET_NULL, related_name="income_tax_table_versions_created", to=settings.AUTH_USER_MODEL))], options={"ordering": ["-effective_from"]}),
        migrations.CreateModel(name="IncomeTaxTableRow", fields=[("id", models.BigAutoField(auto_created=True, primary_key=True, serialize=False, verbose_name="ID")), ("monthly_pay_from", models.PositiveIntegerField()), ("monthly_pay_to", models.PositiveIntegerField()), ("dependent_count", models.PositiveSmallIntegerField()), ("income_tax", models.PositiveIntegerField(default=0)), ("version", models.ForeignKey(on_delete=django.db.models.deletion.CASCADE, related_name="rows", to="labor.incometaxtableversion"))]),
        migrations.AddConstraint(model_name="incometax tablerow".replace(" ", ""), constraint=models.UniqueConstraint(fields=("version", "monthly_pay_from", "dependent_count"), name="uniq_income_tax_table_row")),
        migrations.AddIndex(model_name="incometaxtablerow", index=models.Index(fields=["version", "dependent_count", "monthly_pay_from"], name="labor_incom_version_9bea0d_idx")),
    ]
