import pytest
from django.contrib.auth import get_user_model
from django.core.exceptions import ValidationError
from django.db import transaction
from django.test import Client

from apps.core.rbac.models import LegalEntity, LegalEntityAccessScope, Role, UserLegalEntityMembership, UserProfile
from apps.core.rbac.permissions import can_view_project
from apps.inventory.models import Warehouse, WarehouseType
from apps.projects.hq_views import _generate_project_code
from apps.projects.models import Project, ProjectType


@pytest.fixture(autouse=True)
def _disable_two_factor_enforce(settings):
    settings.MIDDLEWARE = [
        middleware
        for middleware in settings.MIDDLEWARE
        if middleware != "apps.core.middleware.two_factor_enforce.TwoFactorEnforceMiddleware"
    ]


@pytest.mark.django_db
def test_project_access_requires_an_explicit_legal_entity_membership():
    asan = LegalEntity.objects.get(code="ASAN")
    misan = LegalEntity.objects.get(code="MISAN")
    asan_project = Project.objects.create(code="ASAN-CIV-SCOPE", name="아산 현장", legal_entity=asan)
    misan_project = Project.objects.create(code="MISAN-LAND-SCOPE", name="미산 현장", legal_entity=misan)
    user = get_user_model().objects.create_user(username="entity-hq-scope", password="pass")
    UserProfile.objects.create(user=user, role=Role.HQ)
    UserLegalEntityMembership.objects.create(
        user=user, legal_entity=asan, access_scope=LegalEntityAccessScope.ENTITY_HQ
    )

    assert can_view_project(user, asan_project.id)
    assert not can_view_project(user, misan_project.id)


@pytest.mark.django_db
def test_project_list_uses_the_selected_operating_entity():
    asan = LegalEntity.objects.get(code="ASAN")
    misan = LegalEntity.objects.get(code="MISAN")
    Project.objects.create(code="ASAN-CIV-LIST", name="아산 전용 목록 현장", legal_entity=asan)
    Project.objects.create(code="MISAN-LAND-LIST", name="미산 전용 목록 현장", legal_entity=misan)
    user = get_user_model().objects.create_user(username="entity-group-hq-list", password="pass")
    UserProfile.objects.create(user=user, role=Role.HQ)
    for legal_entity in (asan, misan):
        UserLegalEntityMembership.objects.create(
            user=user,
            legal_entity=legal_entity,
            access_scope=LegalEntityAccessScope.GROUP_HQ,
        )
    client = Client()
    client.force_login(user)
    session = client.session
    session["current_legal_entity_id"] = misan.id
    session.save()

    response = client.get("/app/hq/projects/")

    assert response.status_code == 200
    content = response.content.decode("utf-8")
    assert "미산 전용 목록 현장" in content
    assert "아산 전용 목록 현장" not in content


@pytest.mark.django_db
def test_new_project_codes_are_unique_per_entity_type_and_year():
    asan = LegalEntity.objects.get(code="ASAN")
    with transaction.atomic():
        first = _generate_project_code(asan, ProjectType.CIVIL)
        second = _generate_project_code(asan, ProjectType.CIVIL)

    assert first.endswith("-001")
    assert second.endswith("-002")
    assert first.startswith("ASAN-CIV-")


@pytest.mark.django_db
def test_site_warehouse_cannot_belong_to_another_entity_than_its_project():
    asan = LegalEntity.objects.get(code="ASAN")
    misan = LegalEntity.objects.get(code="MISAN")
    project = Project.objects.create(code="ASAN-CIV-WH", name="아산 창고 현장", legal_entity=asan)
    warehouse = Warehouse(
        code="MISAN-SITE-INVALID",
        name="잘못된 현장 창고",
        warehouse_type=WarehouseType.SITE,
        project=project,
        legal_entity=misan,
    )

    with pytest.raises(ValidationError):
        warehouse.clean()
