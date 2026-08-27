import pytest
from django.contrib.auth import get_user_model
from django.test import Client
from django.utils import timezone

from apps.closing.models import ClosingPeriod
from apps.core.models import ApprovalRequest, ApprovalStatus
from apps.core.rbac.models import LegalEntity, LegalEntityAccessScope, Role, UserLegalEntityMembership, UserProfile


@pytest.fixture(autouse=True)
def _disable_two_factor_enforce(settings):
    settings.MIDDLEWARE = [
        middleware
        for middleware in settings.MIDDLEWARE
        if middleware != "apps.core.middleware.two_factor_enforce.TwoFactorEnforceMiddleware"
    ]


@pytest.mark.django_db
def test_hq_approved_inbox_handles_closing_records_when_opening_source_confirmation():
    entity = LegalEntity.objects.get(code="ASAN")
    hq = get_user_model().objects.create_user(username="hq-inbox-closing", password="pass")
    UserProfile.objects.create(user=hq, role=Role.HQ)
    UserLegalEntityMembership.objects.create(
        user=hq, legal_entity=entity, access_scope=LegalEntityAccessScope.ENTITY_HQ
    )
    period = ClosingPeriod.objects.create(legal_entity=entity, year=2026, month=8)
    ApprovalRequest.objects.create(
        object_type="CLOSING_PERIOD", object_id=period.id, status=ApprovalStatus.APPROVED,
        submitted_by=hq, approved_by=hq, approved_at=timezone.now(),
    )
    client = Client()
    client.force_login(hq)
    session = client.session
    session["current_legal_entity_id"] = entity.id
    session.save()

    response = client.get("/app/hq/inbox/?scope=approved&kind=progress")

    assert response.status_code == 200
