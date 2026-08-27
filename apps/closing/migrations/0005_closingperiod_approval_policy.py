from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ("closing", "0004_projectclose"),
    ]

    operations = [
        migrations.AddField(
            model_name="closingperiod",
            name="approval_policy",
            field=models.CharField(
                choices=[
                    ("HQ_SINGLE", "HQ 단독 확정"),
                    ("HQ_DUAL", "HQ 2단계 통제"),
                    ("CEO", "CEO 예외 승인"),
                ],
                default="CEO",
                help_text="월 마감 확정 절차입니다. 기존 마감은 CEO 승인 방식으로 보존됩니다.",
                max_length=16,
            ),
        ),
        migrations.AlterField(
            model_name="closingperiod",
            name="approval_policy",
            field=models.CharField(
                choices=[
                    ("HQ_SINGLE", "HQ 단독 확정"),
                    ("HQ_DUAL", "HQ 2단계 통제"),
                    ("CEO", "CEO 예외 승인"),
                ],
                default="HQ_SINGLE",
                help_text="월 마감 확정 절차입니다. 기존 마감은 CEO 승인 방식으로 보존됩니다.",
                max_length=16,
            ),
        ),
    ]
