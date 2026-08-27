from datetime import date

import pytest

from apps.ceo.services.dashboard import get_ceo_dashboard
from apps.core.rbac.models import LegalEntity
from apps.projects.models import Project


@pytest.mark.django_db
def test_ceo_dashboard_limits_projects_to_the_requested_legal_entity_scope():
    asan = LegalEntity.objects.get(code="ASAN")
    misan = LegalEntity.objects.get(code="MISAN")
    asan_project = Project.objects.create(
        code="ASAN-CEO-SCOPE", name="아산 CEO 집계 현장", legal_entity=asan
    )
    misan_project = Project.objects.create(
        code="MISAN-CEO-SCOPE", name="미산 CEO 집계 현장", legal_entity=misan
    )

    asan_projects = get_ceo_dashboard(
        date(2026, 8, 31), legal_entity_ids=[asan.id]
    )["projects"]
    misan_projects = get_ceo_dashboard(
        date(2026, 8, 31), legal_entity_ids=[misan.id]
    )["projects"]
    group_projects = get_ceo_dashboard(
        date(2026, 8, 31), legal_entity_ids=[asan.id, misan.id]
    )["projects"]

    assert [row["project_id"] for row in asan_projects] == [asan_project.id]
    assert [row["project_id"] for row in misan_projects] == [misan_project.id]
    assert {row["project_id"] for row in group_projects} == {
        asan_project.id,
        misan_project.id,
    }
