from django.db import migrations, models


class Migration(migrations.Migration):
    dependencies = [
        ("evidence", "0002_rename_evidence_obje_4a1c42_idx_evidence_ev_object__e7134e_idx"),
    ]

    operations = [
        migrations.AddField(
            model_name="evidence",
            name="status",
            field=models.CharField(
                max_length=20,
                choices=[
                    ("draft", "Draft"),
                    ("submitted", "Submitted"),
                    ("approved", "Approved"),
                ],
                default="submitted",
            ),
        ),
    ]
