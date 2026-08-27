from django.db import migrations, models
import django.db.models.deletion


class Migration(migrations.Migration):
    dependencies = [
        ("core", "0005_organizationgroup_legalentity_legalentitylicense_and_membership"),
        ("finance", "0007_alter_cashevent_status"),
    ]

    operations = [
        migrations.AddField(
            model_name="cashaccount",
            name="legal_entity",
            field=models.ForeignKey(
                help_text="은행 계좌와 현금 계정의 법적 소유 법인입니다.",
                on_delete=django.db.models.deletion.PROTECT,
                related_name="cash_accounts",
                to="core.legalentity",
            ),
        ),
    ]
