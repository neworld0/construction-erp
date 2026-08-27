import pytest
from django.contrib.auth import get_user_model
from django.test import RequestFactory
from django.test import Client

from apps.core.rbac.models import (
    LegalEntity,
    LegalEntityAccessScope,
    LegalEntityLicense,
    OrganizationGroup,
    Role,
    UserLegalEntityMembership,
    UserProfile,
)
from apps.core.rbac.permissions import (
    can_access_legal_entity,
    get_current_legal_entity,
    get_user_legal_entities,
)


@pytest.fixture(autouse=True)
def _disable_two_factor_enforce(settings):
    settings.MIDDLEWARE = [
        middleware
        for middleware in settings.MIDDLEWARE
        if middleware != "apps.core.middleware.two_factor_enforce.TwoFactorEnforceMiddleware"
    ]


@pytest.mark.django_db
def test_asan_group_master_and_confirmed_licenses_are_seeded():
    group = OrganizationGroup.objects.get(code="ASAN-GROUP")
    assert group.name == "아산 그룹"
    assert set(group.legal_entities.values_list("code", flat=True)) == {"ASAN", "MISAN"}
    assert LegalEntityLicense.objects.filter(legal_entity__code="ASAN", is_active=True).count() == 2
    assert LegalEntityLicense.objects.filter(legal_entity__code="MISAN", is_active=True).count() == 2


@pytest.mark.django_db
def test_entity_membership_is_explicit_and_does_not_follow_role_automatically():
    user = get_user_model().objects.create_user(username="entity-foundation-field", password="pass")
    UserProfile.objects.create(user=user, role=Role.FIELD)
    asan = LegalEntity.objects.get(code="ASAN")
    misan = LegalEntity.objects.get(code="MISAN")
    UserLegalEntityMembership.objects.create(
        user=user,
        legal_entity=asan,
        access_scope=LegalEntityAccessScope.FIELD,
    )

    assert list(get_user_legal_entities(user)) == [asan]
    assert can_access_legal_entity(user, asan)
    assert not can_access_legal_entity(user, misan)


@pytest.mark.django_db
def test_current_entity_uses_only_an_active_membership():
    user = get_user_model().objects.create_user(username="entity-foundation-hq", password="pass")
    UserProfile.objects.create(user=user, role=Role.HQ)
    asan = LegalEntity.objects.get(code="ASAN")
    misan = LegalEntity.objects.get(code="MISAN")
    UserLegalEntityMembership.objects.create(user=user, legal_entity=asan, access_scope=LegalEntityAccessScope.ENTITY_HQ)
    UserLegalEntityMembership.objects.create(user=user, legal_entity=misan, access_scope=LegalEntityAccessScope.ENTITY_HQ, is_active=False)
    request = RequestFactory().get("/app/hq/")
    request.user = user
    request.session = {"current_legal_entity_id": misan.id}

    assert get_current_legal_entity(request) == asan


@pytest.mark.django_db
def test_entity_switch_accepts_only_an_explicit_membership():
    user = get_user_model().objects.create_user(username="entity-switch-hq", password="pass")
    UserProfile.objects.create(user=user, role=Role.HQ)
    asan = LegalEntity.objects.get(code="ASAN")
    misan = LegalEntity.objects.get(code="MISAN")
    UserLegalEntityMembership.objects.create(
        user=user,
        legal_entity=asan,
        access_scope=LegalEntityAccessScope.ENTITY_HQ,
    )
    client = Client()
    client.force_login(user)

    response = client.post(
        "/app/legal-entity/switch/",
        {"legal_entity_id": asan.id, "next": "/app/hq/finance/billings/"},
    )
    assert response.status_code == 302
    assert response.url == "/app/hq/finance/billings/"
    assert client.session["current_legal_entity_id"] == asan.id

    response = client.post("/app/legal-entity/switch/", {"legal_entity_id": misan.id})
    assert response.status_code == 403
