from django.db import migrations, models


class Migration(migrations.Migration):
    dependencies = [("projects", "0018_projectoperationaltestdatewindow")]
    operations = [
        migrations.AddField(
            model_name="project",
            name="requires_ceo_billing_approval",
            field=models.BooleanField(
                default=False,
                help_text="일반 기성 보고서도 CEO 결재를 필수로 합니다. 준공 보고서는 항상 CEO 결재 대상입니다.",
            ),
        ),
    ]
