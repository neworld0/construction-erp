from datetime import date

import pytest
from django.contrib.auth import get_user_model

from apps.closing.models import ClosingStatus
from apps.closing.services import close_month, is_month_closed
from apps.core.rbac.models import LegalEntity, LegalEntityAccessScope, UserLegalEntityMembership


@pytest.mark.django_db
def test_closing_one_entity_does_not_close_the_other_entity_month():
    actor = get_user_model().objects.create_user(username="entity-close-hq")
    asan = LegalEntity.objects.get(code="ASAN")
    misan = LegalEntity.objects.get(code="MISAN")
    UserLegalEntityMembership.objects.create(
        user=actor,
        legal_entity=asan,
        access_scope=LegalEntityAccessScope.ENTITY_HQ,
    )

    period = close_month(2026, 10, actor, legal_entity=asan)

    assert period.status == ClosingStatus.CLOSED
    assert is_month_closed(date(2026, 10, 15), legal_entity=asan)
    assert not is_month_closed(date(2026, 10, 15), legal_entity=misan)
