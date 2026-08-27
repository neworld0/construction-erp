import pytest
from django.contrib.auth import get_user_model
from django.contrib.messages.storage.fallback import FallbackStorage
from django.contrib.sessions.middleware import SessionMiddleware
from django.test import RequestFactory

from apps.core.rbac.models import Role, UserProfile
from apps.cost.models import CostItem
from apps.cost.seed_civil_road_cbs import CIVIL_ROAD_CBS_SPECS, seed_civil_road_cbs
from apps.master.web_views import ceo_cbs_list_view
from apps.projects.forms import BudgetItemForm


@pytest.fixture
def ceo_user(db):
    user = get_user_model().objects.create_user(username="ceo-cbs", password="pass")
    UserProfile.objects.create(user=user, role=Role.CEO)
    return user


@pytest.mark.django_db
def test_cost_item_korean_display_helpers_do_not_return_mojibake():
    seed_civil_road_cbs()
    codes = [
        "CIVIL-EARTHWORK",
        "CIVIL-ASCON-PAVING",
        "CIVIL-EXPENSE",
        "CIVIL-LABOR",
        "CIVIL-MATERIAL",
    ]
    items = {item.code: item for item in CostItem.objects.filter(code__in=codes)}

    assert items["CIVIL-EARTHWORK"].get_work_type_display_ko() == "07 - 토공"
    assert items["CIVIL-ASCON-PAVING"].get_work_type_display_ko() == "08 - 포장"
    assert items["CIVIL-EXPENSE"].get_cost_type_display_ko() == "E - 경비"
    assert items["CIVIL-LABOR"].get_cost_type_display_ko() == "L - 노무비"
    assert items["CIVIL-MATERIAL"].get_category_label_ko() == "재료비"

    for item in items.values():
        assert "???" not in item.get_category_label_ko()
        assert "???" not in item.get_cost_type_display_ko()
        assert "???" not in item.get_work_type_display_ko()
        assert "�" not in item.get_category_label_ko()
        assert "�" not in item.get_cost_type_display_ko()
        assert "�" not in item.get_work_type_display_ko()


@pytest.mark.django_db
def test_civil_seed_creates_canonical_code_when_legacy_item_has_same_name():
    CostItem.objects.create(
        code="LEGACY-EQUIPMENT",
        name="장비비",
        category="equip",
        is_active=True,
    )

    seed_civil_road_cbs()

    expected_codes = {spec["code"] for spec in CIVIL_ROAD_CBS_SPECS}
    seeded_codes = set(
        CostItem.objects.filter(code__in=expected_codes, is_active=True).values_list("code", flat=True)
    )
    assert seeded_codes == expected_codes
    assert CostItem.objects.filter(code="LEGACY-EQUIPMENT").exists()


def _build_request(user):
    request = RequestFactory().get("/app/ceo/cbs/")
    SessionMiddleware(lambda req: None).process_request(request)
    request.session.save()
    setattr(request, "_messages", FallbackStorage(request))
    request.user = user
    return request


@pytest.mark.django_db
def test_ceo_cbs_list_renders_korean_labels(ceo_user):
    seed_civil_road_cbs()
    response = ceo_cbs_list_view(_build_request(ceo_user))

    assert response.status_code == 200
    content = response.content.decode("utf-8")
    assert "토공" in content
    assert "포장" in content
    assert "경비" in content
    assert "노무비" in content
    assert "재료비" in content
    assert "활성" in content
    assert "???" not in content
    assert "�" not in content


def test_project_budget_form_still_uses_korean_budget_category_labels():
    form = BudgetItemForm()
    labels = [label for _value, label in form.fields["category"].choices]

    assert "재료비" in labels
    assert "하도급" in labels
    assert "노무비" in labels
    assert "경비" in labels
    assert "Material" not in labels
    assert "Labor" not in labels
