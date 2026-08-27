from datetime import date
from decimal import Decimal

import pytest
from django.contrib.auth import get_user_model
from django.contrib.messages.storage.fallback import FallbackStorage
from django.core.management import call_command
from django.core.exceptions import ValidationError
from django.test import Client, RequestFactory

from apps.core.rbac.models import LegalEntity, LegalEntityAccessScope, ProjectAssignment, Role, UserLegalEntityMembership, UserProfile
from apps.core.models import ApprovalRequest, ApprovalStatus
from apps.core.services.approvals import approve_request
from apps.cost.models import CostItem
from apps.projects.models import BudgetItem, Project

from .models import IssueStatus, IssueToWork, ItemMaster, Location, ProjectMaterialRequest, Stock, Transfer, TransferDirection, TransferStatus, UoM, Warehouse, WarehouseType
from .services import create_issue_to_work, create_transfer, issue_transfer, receive_transfer, submit_issue_to_work, submit_transfer
from .web_views import hq_project_material_request_review


@pytest.fixture
def field_issue_setup():
    user = get_user_model().objects.create_user(username="field-inventory", password="pass")
    UserProfile.objects.create(user=user, role=Role.FIELD)
    project = Project.objects.create(code="INV-FIELD-1", name="현장 자재 투입 공사")
    UserLegalEntityMembership.objects.create(
        user=user,
        legal_entity=LegalEntity.objects.get(code="ASAN"),
        access_scope=LegalEntityAccessScope.FIELD,
    )
    ProjectAssignment.objects.create(user=user, project=project, is_active=True)
    warehouse = Warehouse.objects.create(
        name="현장 창고", code="INV-SITE-1", warehouse_type=WarehouseType.SITE, project=project
    )
    location = Location.objects.create(warehouse=warehouse, name="기본", code="MAIN", is_default=True)
    uom = UoM.objects.create(code="EA-INV", name="EA")
    item = ItemMaster.objects.create(code="MAT-INV-1", name="아스콘", uom=uom, standard_cost=1200)
    Stock.objects.create(warehouse=warehouse, location=location, item=item, qty_on_hand=Decimal("10"))
    cbs = CostItem.objects.create(code="CBS-INV-1", name="포장공", category="material", is_active=True)
    BudgetItem.objects.create(project=project, cost_item=cbs, category="MATERIAL", planned_amount=100000)
    return user, project, warehouse, item, cbs


@pytest.mark.django_db
def test_field_issue_uses_site_transfer_price_and_server_calculated_amount(field_issue_setup):
    user, project, _warehouse, item, cbs = field_issue_setup

    issue = create_issue_to_work(
        actor=user,
        project=project,
        issue_date=date(2026, 8, 18),
        lines_payload=[{"item_id": item.id, "cbs_id": cbs.id, "qty": "2.5", "unit_cost": "1,234"}],
    )

    line = issue.lines.get()
    assert line.unit_cost == 1200
    assert line.amount == 3000
    submit_issue_to_work(issue, actor=user)
    issue.refresh_from_db()
    assert issue.status == IssueStatus.SUBMITTED
    assert ApprovalRequest.objects.filter(
        object_type="COST_ACTUAL", status=ApprovalStatus.SUBMITTED, submitted_by=user
    ).count() == 1


@pytest.mark.django_db
def test_field_issue_rejects_item_or_cbs_outside_selected_project(field_issue_setup):
    user, project, _warehouse, item, _cbs = field_issue_setup
    other_cbs = CostItem.objects.create(code="CBS-INV-OTHER", name="다른 CBS", category="material", is_active=True)

    with pytest.raises(ValidationError, match="해당 프로젝트 예산"):
        create_issue_to_work(
            actor=user,
            project=project,
            issue_date=date(2026, 8, 18),
            lines_payload=[{"item_id": item.id, "cbs_id": other_cbs.id, "qty": "1", "unit_cost": "100"}],
        )


@pytest.mark.django_db
def test_field_project_options_return_only_assigned_project_item_and_cbs(field_issue_setup):
    user, project, _warehouse, item, cbs = field_issue_setup
    client = Client()
    client.force_login(user)

    item_response = client.get("/app/field/inventory/issues/options/", {"project_id": project.id, "type": "item", "q": "아스"})
    cbs_response = client.get("/app/field/inventory/issues/options/", {"project_id": project.id, "type": "cbs", "q": "포장"})

    assert item_response.status_code == 200
    assert item_response.json() == [{
        "id": item.id,
        "label": "MAT-INV-1 - 아스콘",
        "standard_cost": 1200,
        "issue_unit_cost": 1200,
        "recommended_cbs": {"id": cbs.id, "label": "CBS-INV-1 - 포장공"},
    }]
    assert cbs_response.status_code == 200
    assert cbs_response.json() == [{"id": cbs.id, "label": "CBS-INV-1 - 포장공"}]


@pytest.mark.django_db
def test_item_name_search_recommends_only_selected_project_cbs(field_issue_setup):
    user, project, warehouse, _item, _cbs = field_issue_setup
    uom = UoM.objects.get(code="EA-INV")
    asphalt = ItemMaster.objects.create(code="CIV-MAT-ASPHALT", name="아스콘", uom=uom, standard_cost=150000)
    Stock.objects.create(
        warehouse=warehouse,
        location=warehouse.locations.get(is_default=True),
        item=asphalt,
        qty_on_hand=Decimal("1"),
    )
    recommended = CostItem.objects.create(
        code="CIVIL-ASCON-PAVING", name="아스콘 포장", category="material", is_active=True
    )
    BudgetItem.objects.create(project=project, cost_item=recommended, category="MATERIAL", planned_amount=1)
    client = Client()
    client.force_login(user)

    response = client.get(
        "/app/field/inventory/issues/options/",
        {"project_id": project.id, "type": "item", "q": "아스콘"},
    )

    result = next(row for row in response.json() if row["id"] == asphalt.id)
    assert result["recommended_cbs"] == {
        "id": recommended.id,
        "label": "CIVIL-ASCON-PAVING - 아스콘 포장",
    }


@pytest.mark.django_db
def test_field_issue_accepts_exact_project_item_and_cbs_text_when_pick_is_missed(field_issue_setup):
    user, project, _warehouse, item, cbs = field_issue_setup
    client = Client()
    client.force_login(user)

    response = client.post(
        "/app/field/inventory/issues/",
        {
            "project_id": project.id,
            "issue_date": "2026-08-18",
            "action": "draft",
            "lines-0-item_query": item.code,
            "lines-0-cbs_query": cbs.code,
            "lines-0-qty": "1",
            "lines-0-unit_cost": "1200",
        },
    )

    assert response.status_code == 302
    assert IssueToWork.objects.filter(project=project).count() == 1


@pytest.mark.django_db
def test_field_can_open_and_submit_saved_draft_issue(field_issue_setup):
    user, project, _warehouse, item, cbs = field_issue_setup
    issue = create_issue_to_work(
        actor=user, project=project, issue_date=date(2026, 8, 18),
        lines_payload=[{"item_id": item.id, "cbs_id": cbs.id, "qty": "1", "unit_cost": "1200"}],
    )
    client = Client()
    client.force_login(user)

    detail = client.get(f"/app/field/inventory/issues/{issue.id}/")
    submit = client.post(f"/app/field/inventory/issues/{issue.id}/", {"action": "submit"})

    assert detail.status_code == 200
    assert "제출" in detail.content.decode("utf-8")
    assert submit.status_code == 302
    issue.refresh_from_db()
    assert issue.status == IssueStatus.SUBMITTED


@pytest.mark.django_db
def test_cost_approval_updates_linked_inventory_issue_status(field_issue_setup):
    user, project, _warehouse, item, cbs = field_issue_setup
    hq = get_user_model().objects.create_user(username="inventory-status-hq", password="pass")
    UserProfile.objects.create(user=hq, role=Role.HQ)
    issue = create_issue_to_work(
        actor=user,
        project=project,
        issue_date=date(2026, 8, 18),
        lines_payload=[{"item_id": item.id, "cbs_id": cbs.id, "qty": "1", "unit_cost": "999999"}],
    )
    submit_issue_to_work(issue, actor=user)
    issue.refresh_from_db()
    assert issue.cost_actual_id is not None

    approval = ApprovalRequest.objects.get(object_type="COST_ACTUAL", object_id=issue.cost_actual_id)
    approve_request(approval.id, hq)

    issue.refresh_from_db()
    assert issue.status == IssueStatus.APPROVED
    assert issue.approved_by_id == hq.id


@pytest.mark.django_db
def test_field_can_view_stock_for_assigned_site_warehouse_only(field_issue_setup):
    user, _project, warehouse, item, _cbs = field_issue_setup
    client = Client()
    client.force_login(user)

    response = client.get(f"/app/field/inventory/warehouses/{warehouse.id}/stock/")

    assert response.status_code == 200
    assert item.name in response.content.decode("utf-8")


@pytest.mark.django_db
def test_field_can_view_hq_stock_read_only(field_issue_setup):
    user, _project, _site_warehouse, item, _cbs = field_issue_setup
    central = Warehouse.objects.create(name="본사 중앙창고", code="HQ-VIEW-1", warehouse_type=WarehouseType.HQ)
    location = Location.objects.create(warehouse=central, name="기본", code="MAIN", is_default=True)
    Stock.objects.create(warehouse=central, location=location, item=item, qty_on_hand=Decimal("7"))
    client = Client()
    client.force_login(user)

    response = client.get(f"/app/field/inventory/warehouses/{central.id}/stock/")

    assert response.status_code == 200
    content = response.content.decode("utf-8")
    assert "본사 중앙창고 가용재고" in content
    assert "반송 요청" not in content


@pytest.mark.django_db
def test_field_can_request_site_to_hq_return_transfer_from_site_stock(field_issue_setup):
    user, project, warehouse, item, _cbs = field_issue_setup
    central = Warehouse.objects.create(name="반송 중앙창고", code="HQ-RETURN-1", warehouse_type=WarehouseType.HQ)
    Location.objects.create(warehouse=central, name="기본", code="MAIN", is_default=True)
    client = Client()
    client.force_login(user)

    response = client.post(
        f"/app/field/inventory/warehouses/{warehouse.id}/stock/",
        {"item_id": item.id, "to_warehouse_id": central.id, "qty": "2", "note": "잔여 자재 반송"},
    )

    assert response.status_code == 302
    transfer = Transfer.objects.get(project=project, direction=TransferDirection.SITE_TO_HQ)
    assert transfer.status == TransferStatus.DRAFT
    assert transfer.created_by == user


@pytest.mark.django_db
def test_hq_transfer_issues_and_receives_stock_with_nullable_location_safe_lock(field_issue_setup):
    _field, project, site_warehouse, item, _cbs = field_issue_setup
    hq = get_user_model().objects.create_user(username="transfer-hq", password="pass")
    UserProfile.objects.create(user=hq, role=Role.HQ)
    central = Warehouse.objects.create(name="중앙창고", code="HQ-TRANSFER-1", warehouse_type=WarehouseType.HQ)
    central_location = Location.objects.create(warehouse=central, name="기본", code="MAIN", is_default=True)
    Stock.objects.create(warehouse=central, location=central_location, item=item, qty_on_hand=Decimal("5"))
    transfer = create_transfer(
        actor=hq, direction=TransferDirection.HQ_TO_SITE, project=project,
        from_warehouse=central, to_warehouse=site_warehouse, tx_date=date(2026, 8, 18), note="",
        lines=[{"item": item, "qty": "2", "uom": item.uom}],
    )
    submit_transfer(transfer, actor=hq)
    issue_transfer(transfer, actor=hq)
    transfer.refresh_from_db()
    assert transfer.status == TransferStatus.ISSUED
    receive_transfer(transfer, actor=hq)
    transfer.refresh_from_db()
    assert transfer.status == TransferStatus.RECEIVED


@pytest.mark.django_db
def test_civil_landscape_item_seed_registers_requested_search_items():
    call_command("seed_civil_landscape_items")

    assert set(
        ItemMaster.objects.filter(
            code__in=[
                "CIV-MAT-SAFETY-SIGN", "CIV-MAT-SAFETY-CONE", "CIV-MAT-DIESEL",
                "CIV-MAT-ASPHALT", "CIV-MAT-ROAD-PAINT", "CIV-MAT-GLASS-BEAD",
            ],
            is_active=True,
        ).values_list("name", flat=True)
    ) == {"안전표지판", "안전콘", "경유", "아스콘", "차선도색 페인트", "유리알"}


@pytest.mark.django_db
def test_field_material_request_is_approved_by_hq_with_project_cbs(field_issue_setup):
    field, project, _warehouse, _item, cbs = field_issue_setup
    field_client = Client()
    field_client.force_login(field)
    response = field_client.post("/app/field/inventory/item-requests/", {
        "project_id": project.id, "item_name": "특수 조경자재", "uom_text": "EA", "reason": "현장 추가 식재",
    })
    assert response.status_code == 302
    material_request = ProjectMaterialRequest.objects.get(project=project)

    hq = get_user_model().objects.create_user(username="material-hq", password="pass")
    UserProfile.objects.create(user=hq, role=Role.HQ)
    request = RequestFactory().post(
        f"/app/hq/inventory/material-requests/{material_request.id}/review/",
        {"action": "approve", "approved_cbs_id": cbs.id},
    )
    request.user = hq
    request.session = {}
    request._messages = FallbackStorage(request)
    response = hq_project_material_request_review(request, material_request.id)
    assert response.status_code == 302
    material_request.refresh_from_db()
    assert material_request.status == "approved"
    assert material_request.approved_item.name == "특수 조경자재"
    assert material_request.approved_cbs_id == cbs.id
