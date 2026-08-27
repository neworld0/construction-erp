from django.db import migrations


class Migration(migrations.Migration):
    dependencies = [("labor", "0022_income_tax_table")]
    operations = [
        migrations.RenameIndex(
            model_name="incometaxtablerow",
            old_name="labor_incom_version_9bea0d_idx",
            new_name="labor_incom_version_9f99af_idx",
        ),
    ]
