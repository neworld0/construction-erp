from datetime import date

import pytest
from django.contrib.auth import get_user_model
from django.core.exceptions import PermissionDenied

from apps.closing.guards import guard_write
from apps.closing.services import close_month
from apps.evidence.attachment_policy import can_edit_attachments
from apps.projects.models import Project


@pytest.mark.django_db
def test_close_blocks_write():
    user = get_user_model().objects.create_user(username="d3e4_hq")
    project = Project.objects.create(code="D3E4-P1", name="D3E4 Project")
    close_month(2026, 2, actor=user, note="test close")

    with pytest.raises(PermissionDenied):
        guard_write(
            project=project,
            target_date=date(2026, 2, 15),
            message_context="test write",
        )


def test_reject_allows_attachment_edit():
    assert can_edit_attachments(status="rejected", is_closed_locked=False) is True


def test_submitted_blocks_attachment_edit():
    assert can_edit_attachments(status="submitted", is_closed_locked=False) is False
