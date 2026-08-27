import pytest
from django.contrib.auth import get_user_model
from django.test import Client

from apps.core.rbac.models import (
    LegalEntity,
    LegalEntityAccessScope,
    ProjectAssignment,
    Role,
    UserLegalEntityMembership,
    UserProfile,
)
from apps.projects.models import Project


@pytest.mark.django_db
def test_field_selected_entity_hides_and_denies_assigned_project_of_other_entity():
    asan = LegalEntity.objects.get(code="ASAN")
    misan = LegalEntity.objects.get(code="MISAN")
    user = get_user_model().objects.create_user(username="field-entity-scope", password="pass")
    UserProfile.objects.create(user=user, role=Role.FIELD)
    for entity in (asan, misan):
        UserLegalEntityMembership.objects.create(
            user=user, legal_entity=entity, access_scope=LegalEntityAccessScope.FIELD
        )
    asan_project = Project.objects.create(code="ASAN-FIELD-SCOPE", name="아산 현장", legal_entity=asan)
    misan_project = Project.objects.create(code="MISAN-FIELD-SCOPE", name="미산 현장", legal_entity=misan)
    ProjectAssignment.objects.create(user=user, project=asan_project, is_active=True)
    ProjectAssignment.objects.create(user=user, project=misan_project, is_active=True)

    client = Client()
    client.force_login(user)
    session = client.session
    session["current_legal_entity_id"] = misan.id
    session.save()

    response = client.get(f"/app/field/?tab=progress&project_id={asan_project.id}")
    content = response.content.decode("utf-8")

    assert response.status_code == 200
    assert "미산 현장" in content
    assert "아산 현장" not in content
