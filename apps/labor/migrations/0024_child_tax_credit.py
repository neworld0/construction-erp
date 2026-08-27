from django.db import migrations, models

class Migration(migrations.Migration):
    dependencies = [("labor", "0023_rename_income_tax_table_index")]
    operations = [
        migrations.AddField(model_name="officeemployeeprofile", name="tax_child_count_8_to_20", field=models.PositiveSmallIntegerField(default=0)),
        migrations.AddField(model_name="incometaxtableversion", name="child_credit_one", field=models.PositiveIntegerField(default=12500)),
        migrations.AddField(model_name="incometaxtableversion", name="child_credit_two", field=models.PositiveIntegerField(default=29160)),
        migrations.AddField(model_name="incometaxtableversion", name="child_credit_per_additional", field=models.PositiveIntegerField(default=25000)),
    ]
