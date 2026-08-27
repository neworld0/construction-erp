import pytest
from django.contrib.auth import get_user_model
from django.test import Client

from apps.core.rbac.models import LegalEntity, LegalEntityAccessScope, Role, UserLegalEntityMembership, UserProfile
from apps.inventory.models import IssueStatus, IssueToWork, Warehouse, WarehouseType
from apps.projects.models import Project


@pytest.fixture(autouse=True)
def _disable_two_factor_enforce(settings):
    settings.MIDDLEWARE = [
        middleware
        for middleware in settings.MIDDLEWARE
        if middleware != "apps.core.middleware.two_factor_enforce.TwoFactorEnforceMiddleware"
    ]


@pytest.mark.django_db
def test_hq_material_source_confirmation_is_separate_from_approved_costs():
    entity = LegalEntity.objects.get(code="ASAN")
    hq = get_user_model().objects.create_user(username="hq-material-source", password="pass")
    UserProfile.objects.create(user=hq, role=Role.HQ)
    UserLegalEntityMembership.objects.create(user=hq, legal_entity=entity, access_scope=LegalEntityAccessScope.ENTITY_HQ)
    project = Project.objects.create(code="HQ-MATERIAL-SOURCE", name="자재 원본확인", legal_entity=entity)
    warehouse = Warehouse.objects.create(code="HQ-MATERIAL-SITE", name="자재 현장창고", legal_entity=entity, warehouse_type=WarehouseType.SITE, project=project)
    IssueToWork.objects.create(issue_no="ISSUE-MATERIAL-001", project=project, warehouse=warehouse, issue_date="2026-08-31", status=IssueStatus.APPROVED, created_by=hq)
    client = Client()
    client.force_login(hq)
    session = client.session
    session["current_legal_entity_id"] = entity.id
    session.save()

    response = client.get(f"/app/hq/inbox/?scope=approved&kind=material&project_id={project.id}&as_of_date=2026-08-31")

    assert response.status_code == 200
    assert "자재투입 · ISSUE-MATERIAL-001" in response.content.decode("utf-8")
