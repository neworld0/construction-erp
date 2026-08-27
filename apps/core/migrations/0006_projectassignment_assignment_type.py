from django.db import migrations, models


class Migration(migrations.Migration):
    dependencies = [("core", "0005_organizationgroup_legalentity_legalentitylicense_and_membership")]

    operations = [
        migrations.AddField(
            model_name="projectassignment",
            name="assignment_type",
            field=models.CharField(
                choices=[("STANDARD", "일반 배정"), ("OPERATIONS_SUPPORT", "운영지원")],
                default="STANDARD",
                help_text="타 법인 소속 본사 직원이 프로젝트를 지원하는 경우 운영지원으로 구분합니다.",
                max_length=24,
            ),
        ),
    ]
