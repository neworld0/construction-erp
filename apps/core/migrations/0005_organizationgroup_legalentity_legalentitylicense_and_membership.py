from datetime import date

from django.conf import settings
from django.db import migrations, models
import django.db.models.deletion


def seed_asan_group_and_existing_memberships(apps, schema_editor):
    OrganizationGroup = apps.get_model("core", "OrganizationGroup")
    LegalEntity = apps.get_model("core", "LegalEntity")
    LegalEntityLicense = apps.get_model("core", "LegalEntityLicense")
    UserLegalEntityMembership = apps.get_model("core", "UserLegalEntityMembership")
    UserProfile = apps.get_model("core", "UserProfile")

    group, _ = OrganizationGroup.objects.get_or_create(
        code="ASAN-GROUP",
        defaults={"name": "아산 그룹", "is_active": True},
    )
    asan, _ = LegalEntity.objects.get_or_create(
        code="ASAN",
        defaults={
            "group": group,
            "name": "아산",
            "legal_name": "주식회사 아산",
            "currency_code": "KRW",
            "is_active": True,
        },
    )
    misan, _ = LegalEntity.objects.get_or_create(
        code="MISAN",
        defaults={
            "group": group,
            "name": "미산",
            "legal_name": "주식회사 미산",
            "currency_code": "KRW",
            "is_active": True,
        },
    )

    licenses = (
        (asan, "조경공사업", "10-5037", date(2009, 3, 26), "경기도지사"),
        (asan, "토목공사업", "10-5243", date(2009, 3, 26), "경기도지사"),
        (misan, "조경식재공사업", "남양주 제02-18-06호", date(2002, 8, 31), "경기도 남양주시장"),
        (misan, "조경시설물설치공사업", "남양주 제02-19-04호", date(2002, 8, 31), "경기도 남양주시장"),
    )
    for entity, license_type, registration_number, registered_on, registered_by in licenses:
        LegalEntityLicense.objects.update_or_create(
            legal_entity=entity,
            license_type=license_type,
            registration_number=registration_number,
            defaults={
                "registered_on": registered_on,
                "registered_by": registered_by,
                "is_active": True,
                "evidence_note": "HQ 확인 등록 정보",
            },
        )

    # Existing operational data was confirmed as ASAN.  Existing CEO users are
    # additionally seeded for MISAN read context; no HQ/FIELD user receives
    # cross-entity authority implicitly.
    scope_by_role = {"field": "FIELD", "hq": "ENTITY_HQ", "ceo": "CEO_VIEW"}
    for profile in UserProfile.objects.select_related("user").all():
        scope = scope_by_role.get(profile.role)
        if not scope:
            continue
        entities = (asan, misan) if profile.role == "ceo" else (asan,)
        for entity in entities:
            UserLegalEntityMembership.objects.get_or_create(
                user=profile.user,
                legal_entity=entity,
                defaults={"access_scope": scope, "is_active": True},
            )


def noop_reverse_seed(apps, schema_editor):
    # Preserve seeded legal entity, licence and membership records as audit
    # master data.  Schema rollback must not silently erase business evidence.
    pass


class Migration(migrations.Migration):
    dependencies = [
        ("core", "0004_remove_projectassignment_created_at_and_more"),
        migrations.swappable_dependency(settings.AUTH_USER_MODEL),
    ]

    operations = [
        migrations.CreateModel(
            name="OrganizationGroup",
            fields=[
                ("id", models.BigAutoField(auto_created=True, primary_key=True, serialize=False, verbose_name="ID")),
                ("code", models.CharField(max_length=40, unique=True)),
                ("name", models.CharField(max_length=120)),
                ("is_active", models.BooleanField(default=True)),
                ("created_at", models.DateTimeField(auto_now_add=True)),
                ("updated_at", models.DateTimeField(auto_now=True)),
            ],
            options={"ordering": ["code"]},
        ),
        migrations.CreateModel(
            name="LegalEntity",
            fields=[
                ("id", models.BigAutoField(auto_created=True, primary_key=True, serialize=False, verbose_name="ID")),
                ("code", models.CharField(max_length=20, unique=True)),
                ("name", models.CharField(max_length=120)),
                ("legal_name", models.CharField(max_length=120)),
                ("business_registration_number", models.CharField(blank=True, default="", max_length=30)),
                ("corporate_registration_number", models.CharField(blank=True, default="", max_length=30)),
                ("currency_code", models.CharField(default="KRW", max_length=3)),
                ("is_active", models.BooleanField(default=True)),
                ("created_at", models.DateTimeField(auto_now_add=True)),
                ("updated_at", models.DateTimeField(auto_now=True)),
                ("group", models.ForeignKey(on_delete=django.db.models.deletion.PROTECT, related_name="legal_entities", to="core.organizationgroup")),
            ],
            options={"ordering": ["code"]},
        ),
        migrations.CreateModel(
            name="LegalEntityLicense",
            fields=[
                ("id", models.BigAutoField(auto_created=True, primary_key=True, serialize=False, verbose_name="ID")),
                ("license_type", models.CharField(max_length=120)),
                ("registration_number", models.CharField(max_length=80)),
                ("registered_on", models.DateField()),
                ("registered_by", models.CharField(max_length=120)),
                ("valid_from", models.DateField(blank=True, null=True)),
                ("valid_to", models.DateField(blank=True, null=True)),
                ("is_active", models.BooleanField(default=True)),
                ("evidence_note", models.TextField(blank=True, default="")),
                ("created_at", models.DateTimeField(auto_now_add=True)),
                ("updated_at", models.DateTimeField(auto_now=True)),
                ("legal_entity", models.ForeignKey(on_delete=django.db.models.deletion.PROTECT, related_name="licenses", to="core.legalentity")),
            ],
            options={
                "ordering": ["legal_entity__code", "license_type"],
                "constraints": [models.UniqueConstraint(fields=("legal_entity", "license_type", "registration_number"), name="uniq_legal_entity_license_registration")],
            },
        ),
        migrations.CreateModel(
            name="UserLegalEntityMembership",
            fields=[
                ("id", models.BigAutoField(auto_created=True, primary_key=True, serialize=False, verbose_name="ID")),
                ("access_scope", models.CharField(choices=[("FIELD", "현장"), ("ENTITY_HQ", "법인 HQ"), ("GROUP_HQ", "그룹 HQ"), ("CEO_VIEW", "CEO 조회")], max_length=16)),
                ("is_active", models.BooleanField(default=True)),
                ("effective_from", models.DateField(blank=True, null=True)),
                ("effective_to", models.DateField(blank=True, null=True)),
                ("created_at", models.DateTimeField(auto_now_add=True)),
                ("updated_at", models.DateTimeField(auto_now=True)),
                ("legal_entity", models.ForeignKey(on_delete=django.db.models.deletion.PROTECT, related_name="memberships", to="core.legalentity")),
                ("user", models.ForeignKey(on_delete=django.db.models.deletion.CASCADE, related_name="legal_entity_memberships", to=settings.AUTH_USER_MODEL)),
            ],
            options={
                "indexes": [models.Index(fields=["user", "is_active"], name="core_userle_user_id_18c874_idx"), models.Index(fields=["legal_entity", "is_active"], name="core_userle_legal_e_95dcf1_idx")],
                "constraints": [models.UniqueConstraint(fields=("user", "legal_entity"), name="uniq_user_legal_entity_membership")],
            },
        ),
        migrations.RunPython(seed_asan_group_and_existing_memberships, noop_reverse_seed),
    ]
