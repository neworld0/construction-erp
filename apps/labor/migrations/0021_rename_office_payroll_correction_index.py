from django.db import migrations


class Migration(migrations.Migration):
    dependencies = [("labor", "0020_officepayrollcorrection")]

    operations = [
        migrations.RenameIndex(
            model_name="officepayrollcorrection",
            new_name="labor_offic_run_id_19acbb_idx",
            old_name="labor_offi_run_id_b0f2ee_idx",
        ),
    ]
