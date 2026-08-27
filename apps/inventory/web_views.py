import logging
from datetime import date

from django.contrib import messages
from django.contrib.auth.decorators import login_required
from django.core.exceptions import PermissionDenied, ValidationError
from django.db import transaction
from django.db.models import Q
from django.http import JsonResponse
from django.shortcuts import get_object_or_404, redirect, render
from django.utils import timezone

from apps.audit.services.logger import log_action
from apps.core.rbac.models import ProjectAssignment, Role
from apps.core.rbac.permissions import get_current_legal_entity, get_user_legal_entities, get_user_role, require_legal_entity_access, require_role

from .forms import (
    ItemCategoryForm,
    ItemMasterCreateForm,
    ItemMasterUpdateForm,
    UoMForm,
    WarehouseCreateForm,
    WarehouseUpdateForm,
)
from apps.cost.models import CostItem
from apps.projects.models import Project

from .models import (
    ItemCategory,
    ItemMaster,
    InventoryLedger,
    InventoryTxType,
    IssueToWork,
    IssueStatus,
    Location,
    UoM,
    Warehouse,
    WarehouseType,
    Stock,
    Transfer,
    TransferDirection,
    TransferStatus,
    MaterialRequestStatus,
    ProjectMaterialRequest,
)
from .services import (
    create_hq_warehouse,
    create_ledger_entry,
    create_transfer,
    cancel_transfer,
    create_item,
    get_issue_unit_cost,
    create_issue_to_work,
    ensure_default_location,
    issue_transfer,
    receive_transfer,
    submit_transfer,
    submit_issue_to_work,
    update_item,
)

logger = logging.getLogger(__name__)


# Standard item codes map to the most specific CBS first. The candidate is
# always constrained to the selected project's approved budget CBS list.
ITEM_CBS_RECOMMENDATION_CODES = {
    "CIV-MAT-SAFETY-SIGN": ("CIVIL-TRAFFIC-SAFETY", "CIVIL-SAFETY-HEALTH", "CIVIL-EXPENSE"),
    "CIV-MAT-SAFETY-CONE": ("CIVIL-TRAFFIC-SAFETY", "CIVIL-SAFETY-HEALTH", "CIVIL-EXPENSE"),
    "CIV-MAT-DIESEL": ("CIVIL-EQUIPMENT", "CIVIL-EXPENSE"),
    "CIV-MAT-ASPHALT": ("CIVIL-ASCON-PAVING", "CIVIL-PAVING", "CIVIL-MATERIAL"),
    "CIV-MAT-ROAD-PAINT": ("CIVIL-LANE-MARKING", "CIVIL-MATERIAL"),
    "CIV-MAT-GLASS-BEAD": ("CIVIL-LANE-MARKING", "CIVIL-MATERIAL"),
}


def _recommended_cbs_for_item(project, item):
    available = CostItem.objects.filter(is_active=True, budget_items__project=project).distinct()
    for code in ITEM_CBS_RECOMMENDATION_CODES.get(item.code, ()):
        cbs = available.filter(code=code).first()
        if cbs:
            return cbs
    # No dedicated mapping in this project's budget: use its material bucket
    # as a safe, visible recommendation rather than a CBS from another project.
    return available.filter(category="material").order_by("sort_order", "code").first()


def _field_warehouse_queryset(user):
    legal_entities = get_user_legal_entities(user)
    assigned_project_ids = ProjectAssignment.objects.filter(
        user=user, is_active=True, project__legal_entity__in=legal_entities
    ).values_list("project_id", flat=True)
    return Warehouse.objects.select_related("project").filter(
        Q(warehouse_type=WarehouseType.HQ, legal_entity__in=legal_entities)
        | Q(project_id__in=assigned_project_ids)
    )


@login_required
def hq_warehouse_list(request):
    require_role(request.user, [Role.HQ, Role.CEO], request=request)
    warehouses = (
        Warehouse.objects.select_related("project", "legal_entity").filter(legal_entity__in=get_user_legal_entities(request.user))
        .prefetch_related("locations")
        .order_by("warehouse_type", "name")
    )
    return render(
        request,
        "app/hq/warehouse_list.html",
        {"warehouses": warehouses, "role": get_user_role(request.user)},
    )


@login_required
def hq_warehouse_detail(request, warehouse_id):
    require_role(request.user, [Role.HQ, Role.CEO], request=request)
    warehouse = get_object_or_404(
        Warehouse.objects.select_related("project", "legal_entity").prefetch_related("locations"),
        id=warehouse_id,
    )
    require_legal_entity_access(request.user, warehouse.legal_entity, request=request)
    locations = warehouse.locations.order_by("-is_default", "name")
    return render(
        request,
        "app/hq/warehouse_detail.html",
        {"warehouse": warehouse, "locations": locations, "role": get_user_role(request.user)},
    )


@login_required
def field_warehouse_list(request):
    require_role(request.user, [Role.FIELD], request=request)
    warehouses = _field_warehouse_queryset(request.user).filter(
        legal_entity=get_current_legal_entity(request)
    ).prefetch_related("locations")
    return render(
        request,
        "app/field/warehouse_list.html",
        {"warehouses": warehouses, "role": get_user_role(request.user)},
    )


@login_required
def field_warehouse_stock(request, warehouse_id):
    require_role(request.user, [Role.FIELD], request=request)
    current_legal_entity = get_current_legal_entity(request)
    assigned_project_ids = ProjectAssignment.objects.filter(
        user=request.user, is_active=True, project__legal_entity=current_legal_entity
    ).values_list("project_id", flat=True)
    warehouse = get_object_or_404(
        Warehouse.objects.select_related("project").filter(
            Q(warehouse_type=WarehouseType.HQ, legal_entity=current_legal_entity)
            | Q(warehouse_type=WarehouseType.SITE, project_id__in=assigned_project_ids)
        ).distinct(), id=warehouse_id,
    )
    stocks = Stock.objects.filter(warehouse=warehouse, qty_on_hand__gt=0).select_related("item", "item__uom", "location").order_by("item__code")
    hq_warehouses = Warehouse.objects.filter(warehouse_type=WarehouseType.HQ, legal_entity=current_legal_entity, is_active=True).order_by("code")
    if request.method == "POST" and warehouse.warehouse_type == WarehouseType.SITE:
        try:
            item = get_object_or_404(ItemMaster.objects.filter(is_active=True), id=request.POST.get("item_id"))
            to_warehouse = get_object_or_404(hq_warehouses, id=request.POST.get("to_warehouse_id"))
            transfer = create_transfer(
                actor=request.user, direction=TransferDirection.SITE_TO_HQ, project=warehouse.project,
                from_warehouse=warehouse, to_warehouse=to_warehouse, tx_date=timezone.localdate(),
                note=(request.POST.get("note") or "").strip(),
                lines=[{"item": item, "qty": request.POST.get("qty"), "uom": item.uom}],
            )
            messages.success(request, f"중앙창고 반송 요청 {transfer.transfer_no}을 등록했습니다. HQ가 확정·출고·입고 처리합니다.")
            return redirect(f"/app/field/inventory/warehouses/{warehouse.id}/stock/")
        except (ValidationError, PermissionDenied) as exc:
            messages.error(request, str(exc))
    return render(request, "app/field/warehouse_stock.html", {"warehouse": warehouse, "stocks": stocks, "hq_warehouses": hq_warehouses, "can_return": warehouse.warehouse_type == WarehouseType.SITE})


@login_required
def field_inventory_issue_form(request):
    require_role(request.user, [Role.FIELD], request=request)
    current_legal_entity = get_current_legal_entity(request)
    assigned_projects = Project.objects.filter(
        projectassignment__user=request.user,
        projectassignment__is_active=True,
        legal_entity=current_legal_entity,
    ).distinct()
    if not assigned_projects.exists():
        messages.error(request, "배정된 프로젝트가 없어 자재 투입을 등록할 수 없습니다.")
        return render(
            request,
            "app/field/inventory_issue_form.html",
            {"projects": [], "items": [], "cbs_items": [], "issues": []},
        )
    items = []
    cbs_items = []
    issues = (
        IssueToWork.objects.select_related("project", "cost_actual")
        .filter(project__in=assigned_projects)
        .order_by("-issue_date", "-id")[:20]
    )
    if request.method == "POST":
        project_id = request.POST.get("project_id")
        issue_date_raw = request.POST.get("issue_date") or ""
        note = request.POST.get("note") or ""
        action = request.POST.get("action") or "draft"
        lines_payload = []
        for idx in range(0, 20):
            item_id = request.POST.get(f"lines-{idx}-item_id")
            cbs_id = request.POST.get(f"lines-{idx}-cbs_id")
            item_query = request.POST.get(f"lines-{idx}-item_query") or ""
            cbs_query = request.POST.get(f"lines-{idx}-cbs_query") or ""
            qty = request.POST.get(f"lines-{idx}-qty")
            unit_cost = request.POST.get(f"lines-{idx}-unit_cost")
            memo = request.POST.get(f"lines-{idx}-memo") or ""
            if not item_id and not cbs_id and not item_query.strip() and not cbs_query.strip() and not qty and not unit_cost and not memo.strip():
                continue
            lines_payload.append(
                {
                    "item_id": item_id,
                    "cbs_id": cbs_id,
                    "item_query": item_query,
                    "cbs_query": cbs_query,
                    "qty": qty,
                    "unit_cost": unit_cost,
                    "memo": memo,
                }
            )
        try:
            project = assigned_projects.get(id=project_id)
        except Project.DoesNotExist:
            messages.error(request, "유효하지 않은 프로젝트입니다.")
            project = None
        try:
            issue_date = date.fromisoformat(issue_date_raw)
        except ValueError:
            issue_date = None
        if project is None or issue_date is None:
            messages.error(request, "입력값을 확인해 주세요.")
        else:
            for payload in lines_payload:
                item_query = payload.get("item_query", "").strip()
                cbs_query = payload.get("cbs_query", "").strip()
                if not payload.get("item_id") and item_query:
                    matched_items = ItemMaster.objects.filter(
                        is_active=True,
                    ).filter(Q(code__iexact=item_query) | Q(name__iexact=item_query)).distinct()[:2]
                    if len(matched_items) == 1:
                        payload["item_id"] = matched_items[0].id
                if not payload.get("cbs_id") and cbs_query:
                    matched_cbs = CostItem.objects.filter(
                        is_active=True,
                        budget_items__project=project,
                    ).filter(Q(code__iexact=cbs_query) | Q(name__iexact=cbs_query)).distinct()[:2]
                    if len(matched_cbs) == 1:
                        payload["cbs_id"] = matched_cbs[0].id
            try:
                issue = create_issue_to_work(
                    actor=request.user,
                    project=project,
                    issue_date=issue_date,
                    lines_payload=lines_payload,
                    note=note,
                )
                if action == "submit":
                    submit_issue_to_work(issue, actor=request.user)
                    messages.success(
                        request,
                        "자재 투입이 제출되었습니다. 원가 실적·재고 원장과 CEO 승인 요청이 생성되었습니다.",
                    )
                else:
                    messages.success(request, "자재 투입이 임시저장되었습니다.")
                return redirect("/app/field/inventory/issues/")
            except PermissionDenied as exc:
                messages.error(request, str(exc))
            except ValidationError as exc:
                if hasattr(exc, "message_dict"):
                    message_parts = []
                    for values in exc.message_dict.values():
                        if isinstance(values, (list, tuple)):
                            message_parts.extend(values)
                        else:
                            message_parts.append(str(values))
                    messages.error(request, " ".join(message_parts))
                else:
                    messages.error(request, str(exc))
    return render(
        request,
        "app/field/inventory_issue_form.html",
        {
            "projects": assigned_projects,
            "items": items,
            "cbs_items": cbs_items,
            "issues": issues,
        },
    )


@login_required
def field_inventory_issue_detail(request, issue_id):
    require_role(request.user, [Role.FIELD], request=request)
    current_legal_entity = get_current_legal_entity(request)
    issue = get_object_or_404(
        IssueToWork.objects.select_related("project").prefetch_related("lines__item", "lines__cbs", "lines__uom"),
        id=issue_id,
        project__projectassignment__user=request.user,
        project__projectassignment__is_active=True,
        project__legal_entity=current_legal_entity,
    )
    if issue.created_by_id != request.user.id:
        raise PermissionDenied("본인이 임시저장한 자재 투입만 제출할 수 있습니다.")
    if request.method == "POST" and request.POST.get("action") == "submit":
        try:
            submit_issue_to_work(issue, actor=request.user)
            messages.success(request, "자재 투입을 제출했습니다. 원가 실적과 CEO 승인 요청이 생성되었습니다.")
            return redirect("/app/field/inventory/issues/")
        except (PermissionDenied, ValidationError) as exc:
            messages.error(request, str(exc))
    return render(request, "app/field/inventory_issue_detail.html", {"issue": issue, "can_submit": issue.status == IssueStatus.DRAFT})


@login_required
def field_inventory_issue_options(request):
    """Return only material/CBS choices available to the selected FIELD project."""
    require_role(request.user, [Role.FIELD], request=request)
    project_id = request.GET.get("project_id")
    option_type = request.GET.get("type")
    q = (request.GET.get("q") or "").strip()
    try:
        limit = min(max(int(request.GET.get("limit", 20)), 1), 50)
    except (TypeError, ValueError):
        limit = 20
    if option_type not in {"item", "cbs"}:
        return JsonResponse({"detail": "유효하지 않은 조회 유형입니다."}, status=400)
    project = get_object_or_404(
        Project.objects.filter(
            projectassignment__user=request.user,
            projectassignment__is_active=True,
            legal_entity=get_current_legal_entity(request),
        ).distinct(),
        id=project_id,
    )
    if option_type == "item":
        # FIELD 자재 투입은 해당 프로젝트 현장창고로 이관되어 현재고가
        # 있는 품목만 선택한다. 단가는 중앙창고 입고/이관 원장에서 자동 적용한다.
        site_warehouse = Warehouse.objects.filter(
            project=project,
            warehouse_type=WarehouseType.SITE,
            is_active=True,
        ).first()
        available_item_ids = Stock.objects.filter(
            warehouse=site_warehouse,
            qty_on_hand__gt=0,
            item__is_active=True,
        ).values_list("item_id", flat=True)
        options = ItemMaster.objects.filter(id__in=available_item_ids, is_active=True).select_related("uom").distinct()
        if q:
            options = options.filter(Q(code__icontains=q) | Q(name__icontains=q) | Q(spec__icontains=q))
        data = [
            {
                "id": item.id,
                "label": f"{item.code} - {item.name}" + (f" ({item.spec})" if item.spec else ""),
                "standard_cost": item.standard_cost,
                "issue_unit_cost": get_issue_unit_cost(warehouse=site_warehouse, item=item) if site_warehouse else None,
                "recommended_cbs": (
                    {"id": cbs.id, "label": f"{cbs.code} - {cbs.get_display_name()}"}
                    if (cbs := _recommended_cbs_for_item(project, item)) else None
                ),
            }
            for item in options.order_by("code")[:limit]
        ]
    else:
        options = CostItem.objects.filter(is_active=True, budget_items__project=project).distinct()
        if q:
            options = options.filter(Q(code__icontains=q) | Q(name__icontains=q))
        data = [{"id": item.id, "label": f"{item.code} - {item.get_display_name()}"} for item in options.order_by("code")[:limit]]
    return JsonResponse(data, safe=False)


@login_required
def field_project_material_requests(request):
    require_role(request.user, [Role.FIELD], request=request)
    projects = Project.objects.filter(
        projectassignment__user=request.user,
        projectassignment__is_active=True,
        legal_entity=get_current_legal_entity(request),
    ).distinct()
    if request.method == "POST":
        project = get_object_or_404(projects, id=request.POST.get("project_id"))
        item_name = (request.POST.get("item_name") or "").strip()
        if not item_name:
            messages.error(request, "요청할 품목명을 입력해 주세요.")
        else:
            requested = ProjectMaterialRequest.objects.create(
                project=project, item_name=item_name, spec=(request.POST.get("spec") or "").strip(),
                uom_text=(request.POST.get("uom_text") or "EA").strip().upper()[:10],
                requested_qty=request.POST.get("requested_qty") or None,
                reason=(request.POST.get("reason") or "").strip(), requested_by=request.user,
            )
            log_action(actor=request.user, action="PROJECT_MATERIAL_REQUEST_SUBMIT", object_type="ProjectMaterialRequest", object_id=requested.id, project=project, after={"item_name": item_name, "status": requested.status})
            messages.success(request, "HQ 품목 승인 요청을 등록했습니다.")
            return redirect("/app/field/inventory/item-requests/")
    requests = ProjectMaterialRequest.objects.filter(project__in=projects).select_related("project", "approved_item", "approved_cbs").order_by("-requested_at")[:30]
    return render(request, "app/field/project_material_requests.html", {"projects": projects, "requests": requests, "role": get_user_role(request.user)})


@login_required
def hq_project_material_requests(request):
    require_role(request.user, [Role.HQ], request=request)
    requests = list(ProjectMaterialRequest.objects.filter(status=MaterialRequestStatus.SUBMITTED).select_related("project", "requested_by").order_by("requested_at"))
    for material_request in requests:
        material_request.cbs_choices = CostItem.objects.filter(is_active=True, budget_items__project=material_request.project).distinct().order_by("code")
    return render(request, "app/hq/project_material_requests.html", {"requests": requests, "role": get_user_role(request.user)})


@login_required
def hq_project_material_request_review(request, request_id):
    require_role(request.user, [Role.HQ], request=request)
    if request.method != "POST":
        return redirect("/app/hq/inventory/material-requests/")
    material_request = get_object_or_404(ProjectMaterialRequest.objects.select_related("project"), id=request_id)
    if material_request.status != MaterialRequestStatus.SUBMITTED:
        messages.error(request, "이미 처리된 품목 요청입니다.")
        return redirect("/app/hq/inventory/material-requests/")
    action = request.POST.get("action")
    if action == "reject":
        reason = (request.POST.get("reject_reason") or "").strip()
        if not reason:
            messages.error(request, "반려 사유를 입력해 주세요.")
            return redirect("/app/hq/inventory/material-requests/")
        material_request.status = MaterialRequestStatus.REJECTED
        material_request.reject_reason = reason
        material_request.reviewed_by = request.user
        material_request.reviewed_at = timezone.now()
        material_request.save(update_fields=["status", "reject_reason", "reviewed_by", "reviewed_at", "updated_at"])
        log_action(actor=request.user, action="PROJECT_MATERIAL_REQUEST_REJECT", object_type="ProjectMaterialRequest", object_id=material_request.id, project=material_request.project, after={"reason": reason})
        messages.success(request, "품목 요청을 반려했습니다.")
        return redirect("/app/hq/inventory/material-requests/")
    cbs = get_object_or_404(CostItem, id=request.POST.get("approved_cbs_id"), is_active=True, budget_items__project=material_request.project)
    item = ItemMaster.objects.filter(name__iexact=material_request.item_name, is_active=True).first()
    if item is None:
        uom, _ = UoM.objects.get_or_create(code=material_request.uom_text or "EA", defaults={"name": material_request.uom_text or "EA"})
        item = create_item({"code": "", "name": material_request.item_name, "uom": uom, "spec": material_request.spec, "is_active": True}, actor=request.user)
    material_request.status = MaterialRequestStatus.APPROVED
    material_request.approved_item = item
    material_request.approved_cbs = cbs
    material_request.reviewed_by = request.user
    material_request.reviewed_at = timezone.now()
    material_request.save(update_fields=["status", "approved_item", "approved_cbs", "reviewed_by", "reviewed_at", "updated_at"])
    log_action(actor=request.user, action="PROJECT_MATERIAL_REQUEST_APPROVE", object_type="ProjectMaterialRequest", object_id=material_request.id, project=material_request.project, after={"item_id": item.id, "cbs_id": cbs.id})
    messages.success(request, "품목을 승인하고 프로젝트 CBS를 지정했습니다.")
    return redirect("/app/hq/inventory/material-requests/")


@login_required
def hq_master_warehouse_list(request):
    require_role(request.user, [Role.HQ, Role.CEO], request=request)
    role = get_user_role(request.user)
    show_sites = request.GET.get("show_sites") == "1"
    q = (request.GET.get("q") or "").strip()
    base_qs = Warehouse.objects.select_related("project").prefetch_related("locations")
    if not show_sites:
        base_qs = base_qs.filter(warehouse_type=WarehouseType.HQ)
    if q:
        base_qs = base_qs.filter(Q(code__icontains=q) | Q(name__icontains=q))
    warehouses = base_qs.order_by("warehouse_type", "name", "code")
    for warehouse in warehouses:
        warehouse.default_location = next(
            (loc for loc in warehouse.locations.all() if loc.is_default),
            None,
        )
    return render(
        request,
        "app/hq/master_warehouse_list.html",
        {
            "warehouses": warehouses,
            "q": q,
            "role": role,
            "show_sites": show_sites,
        },
    )


@login_required
def hq_master_inventory_receipt(request):
    require_role(request.user, [Role.HQ], request=request)
    warehouses = Warehouse.objects.filter(warehouse_type=WarehouseType.HQ, is_active=True).order_by("code")
    items = ItemMaster.objects.filter(is_active=True).select_related("uom").order_by("code")[:500]
    if request.method == "POST":
        warehouse = get_object_or_404(warehouses, id=request.POST.get("warehouse_id"))
        item = get_object_or_404(ItemMaster.objects.filter(is_active=True), id=request.POST.get("item_id"))
        try:
            receipt_date = date.fromisoformat(request.POST.get("receipt_date") or "")
            unit_cost_raw = (request.POST.get("unit_cost") or "").replace(",", "").strip()
            unit_cost = int(unit_cost_raw) if unit_cost_raw else None
            if unit_cost is not None and unit_cost < 0:
                raise ValueError
            ledger, stock = create_ledger_entry(
                actor=request.user, tx_type=InventoryTxType.RECEIPT, tx_date=receipt_date,
                warehouse=warehouse, item=item, qty_delta=request.POST.get("qty"),
                unit_cost=unit_cost, note=(request.POST.get("note") or "").strip(),
            )
            messages.success(request, f"입고 처리했습니다. 현재 재고: {stock.qty_on_hand}{item.uom.code}")
            return redirect("/app/hq/master/warehouses/receipt/")
        except (ValueError, ValidationError, PermissionDenied) as exc:
            messages.error(request, "입력값을 확인해 주세요." if isinstance(exc, ValueError) else str(exc))
    return render(request, "app/hq/master_inventory_receipt.html", {"warehouses": warehouses, "items": items, "today": timezone.localdate()})


@login_required
def hq_master_warehouse_stock(request, warehouse_id):
    require_role(request.user, [Role.HQ, Role.CEO], request=request)
    warehouse = get_object_or_404(Warehouse.objects.select_related("project"), id=warehouse_id)
    stocks = Stock.objects.filter(warehouse=warehouse).select_related("item", "item__uom", "location").order_by("item__code")
    ledgers = InventoryLedger.objects.filter(warehouse=warehouse).select_related("item", "uom").order_by("-tx_date", "-id")[:30]
    return render(request, "app/hq/master_warehouse_stock.html", {"warehouse": warehouse, "stocks": stocks, "ledgers": ledgers})


@login_required
def hq_master_transfer_list(request):
    require_role(request.user, [Role.HQ], request=request)
    transfers = Transfer.objects.select_related("project", "from_warehouse", "to_warehouse").prefetch_related("lines__item").order_by("-tx_date", "-id")[:50]
    return render(request, "app/hq/master_transfer_list.html", {"transfers": transfers})


@login_required
def hq_master_transfer_new(request):
    require_role(request.user, [Role.HQ], request=request)
    hq_warehouses = Warehouse.objects.filter(warehouse_type=WarehouseType.HQ, is_active=True).order_by("code")
    site_warehouses = Warehouse.objects.filter(warehouse_type=WarehouseType.SITE, is_active=True).select_related("project").order_by("project__name")
    items = ItemMaster.objects.filter(is_active=True).select_related("uom").order_by("code")[:500]
    if request.method == "POST":
        try:
            from_warehouse = get_object_or_404(hq_warehouses, id=request.POST.get("from_warehouse_id"))
            to_warehouse = get_object_or_404(site_warehouses, id=request.POST.get("to_warehouse_id"))
            item = get_object_or_404(ItemMaster.objects.filter(is_active=True), id=request.POST.get("item_id"))
            transfer = create_transfer(
                actor=request.user, direction=TransferDirection.HQ_TO_SITE, project=to_warehouse.project,
                from_warehouse=from_warehouse, to_warehouse=to_warehouse,
                tx_date=date.fromisoformat(request.POST.get("tx_date") or ""), note=request.POST.get("note") or "",
                lines=[{"item": item, "qty": request.POST.get("qty"), "uom": item.uom}],
            )
            messages.success(request, f"이관 요청 {transfer.transfer_no}을 등록했습니다. 출고 처리 후 현장 입고를 완료해 주세요.")
            return redirect("/app/hq/master/warehouses/transfers/")
        except (ValueError, ValidationError, PermissionDenied) as exc:
            messages.error(request, "입력값을 확인해 주세요." if isinstance(exc, ValueError) else str(exc))
    return render(request, "app/hq/master_transfer_form.html", {"hq_warehouses": hq_warehouses, "site_warehouses": site_warehouses, "items": items, "today": timezone.localdate()})


@login_required
def hq_master_transfer_action(request, transfer_id, action):
    require_role(request.user, [Role.HQ], request=request)
    if request.method != "POST":
        return redirect("/app/hq/master/warehouses/transfers/")
    transfer = get_object_or_404(Transfer.objects.select_related("project"), id=transfer_id)
    try:
        if action == "submit":
            submit_transfer(transfer, actor=request.user)
        elif action == "issue":
            issue_transfer(transfer, actor=request.user)
        elif action == "receive":
            receive_transfer(transfer, actor=request.user)
        elif action == "cancel":
            cancel_transfer(transfer, actor=request.user)
        else:
            raise ValidationError("유효하지 않은 이관 처리입니다.")
        messages.success(request, "이관 상태를 처리했습니다.")
    except (ValidationError, PermissionDenied) as exc:
        messages.error(request, str(exc))
    return redirect("/app/hq/master/warehouses/transfers/")


@login_required
def hq_master_warehouse_new(request):
    require_role(request.user, [Role.HQ, Role.CEO], request=request)
    if request.method == "POST":
        form = WarehouseCreateForm(request.POST)
        if form.is_valid():
            legal_entity = form.cleaned_data["legal_entity"]
            require_legal_entity_access(request.user, legal_entity, request=request)
            create_hq_warehouse(
                name=form.cleaned_data["name"],
                code=form.cleaned_data["code"],
                legal_entity=legal_entity,
                actor=request.user,
            )
            messages.success(request, "본사 창고가 생성되었습니다.")
            return redirect("/app/hq/master/warehouses/")
        messages.error(request, "입력 오류가 있습니다. 항목을 확인하세요.")
    else:
        form = WarehouseCreateForm(initial={"legal_entity": get_current_legal_entity(request)})
    return render(
        request,
        "app/hq/master_warehouse_form.html",
        {"form": form, "mode": "create"},
    )


@login_required
def hq_master_warehouse_edit(request, warehouse_id):
    require_role(request.user, [Role.HQ, Role.CEO], request=request)
    warehouse = get_object_or_404(Warehouse.objects.select_related("legal_entity"), id=warehouse_id)
    require_legal_entity_access(request.user, warehouse.legal_entity, request=request)
    if warehouse.warehouse_type != WarehouseType.HQ:
        messages.error(request, "본사 창고만 수정할 수 있습니다.")
        return redirect("/app/hq/master/warehouses/")
    if request.method == "POST":
        form = WarehouseUpdateForm(request.POST, instance=warehouse)
        if form.is_valid():
            before = {"code": warehouse.code, "name": warehouse.name}
            form.save()
            ensure_default_location(warehouse, actor=request.user)
            _log_action_safe(
                request.user,
                action="WAREHOUSE_UPDATE",
                object_id=warehouse.id,
                summary=f"Warehouse update: {warehouse.code}",
                metadata={
                    "warehouse_id": warehouse.id,
                    "before": before,
                    "after": {"code": warehouse.code, "name": warehouse.name},
                },
            )
            messages.success(request, "창고 정보가 저장되었습니다.")
            return redirect("/app/hq/master/warehouses/")
        messages.error(request, "입력 오류가 있습니다. 항목을 확인하세요.")
    else:
        form = WarehouseUpdateForm(instance=warehouse)
    return render(
        request,
        "app/hq/master_warehouse_form.html",
        {"form": form, "mode": "edit", "warehouse": warehouse},
    )


@login_required
def hq_master_warehouse_toggle(request, warehouse_id):
    require_role(request.user, [Role.HQ], request=request)
    if request.method != "POST":
        return redirect("/app/hq/master/warehouses/")
    with transaction.atomic():
        warehouse = get_object_or_404(
            Warehouse.objects.select_for_update(), id=warehouse_id
        )
        before = warehouse.is_active
        warehouse.is_active = not warehouse.is_active
        warehouse.save(update_fields=["is_active", "updated_at"])
    _log_action_safe(
        request.user,
        action="WAREHOUSE_TOGGLE_ACTIVE",
        object_id=warehouse.id,
        summary=f"Warehouse toggle: {warehouse.code} {before}->{warehouse.is_active}",
        metadata={
            "warehouse_id": warehouse.id,
            "before_active": before,
            "after_active": warehouse.is_active,
        },
    )
    messages.success(request, "창고 활성 상태가 변경되었습니다.")
    return redirect("/app/hq/master/warehouses/")


@login_required
def hq_master_item_list(request):
    require_role(request.user, [Role.HQ, Role.CEO], request=request)
    q = (request.GET.get("q") or "").strip()
    category_id = request.GET.get("category")
    active = request.GET.get("active", "1")
    qs = ItemMaster.objects.select_related("category", "uom").order_by("code")
    if q:
        qs = qs.filter(
            Q(code__icontains=q)
            | Q(name__icontains=q)
            | Q(spec__icontains=q)
            | Q(barcode__icontains=q)
        )
    if category_id:
        qs = qs.filter(category_id=category_id)
    if active == "1":
        qs = qs.filter(is_active=True)
    elif active == "0":
        qs = qs.filter(is_active=False)
    categories = ItemCategory.objects.order_by("name")
    return render(
        request,
        "app/hq/master_item_list.html",
        {
            "items": qs,
            "q": q,
            "active": active,
            "categories": categories,
            "category_id": str(category_id) if category_id else "",
        },
    )


@login_required
def hq_master_item_new(request):
    require_role(request.user, [Role.HQ, Role.CEO], request=request)
    if request.method == "POST":
        form = ItemMasterCreateForm(request.POST)
        if form.is_valid():
            data = form.cleaned_data
            if data.get("auto_code"):
                data["code"] = ""
            item = create_item(
                {
                    "code": data.get("code"),
                    "name": data.get("name"),
                    "category": data.get("category"),
                    "uom": data.get("uom"),
                    "spec": data.get("spec"),
                    "description": data.get("description"),
                    "barcode": data.get("barcode"),
                    "is_active": data.get("is_active"),
                },
                actor=request.user,
            )
            messages.success(request, f"품목이 생성되었습니다: {item.code}")
            return redirect("/app/hq/master/items/")
        messages.error(request, "입력 오류가 있습니다. 항목을 확인하세요.")
    else:
        form = ItemMasterCreateForm()
    return render(
        request,
        "app/hq/master_item_form.html",
        {"form": form, "mode": "create"},
    )


@login_required
def hq_master_item_edit(request, item_id):
    require_role(request.user, [Role.HQ, Role.CEO], request=request)
    item = get_object_or_404(ItemMaster, id=item_id)
    if request.method == "POST":
        form = ItemMasterUpdateForm(request.POST, instance=item)
        if form.is_valid():
            data = form.cleaned_data
            update_item(
                item,
                {
                    "code": data.get("code"),
                    "name": data.get("name"),
                    "category": data.get("category"),
                    "uom": data.get("uom"),
                    "spec": data.get("spec"),
                    "description": data.get("description"),
                    "barcode": data.get("barcode"),
                    "is_active": data.get("is_active"),
                },
                actor=request.user,
            )
            messages.success(request, "품목 정보가 저장되었습니다.")
            return redirect("/app/hq/master/items/")
        messages.error(request, "입력 오류가 있습니다. 항목을 확인하세요.")
    else:
        form = ItemMasterUpdateForm(instance=item)
    return render(
        request,
        "app/hq/master_item_form.html",
        {"form": form, "mode": "edit", "item": item},
    )


@login_required
def hq_master_uom_list(request):
    require_role(request.user, [Role.HQ, Role.CEO], request=request)
    uoms = UoM.objects.order_by("code")
    return render(request, "app/hq/master_uom_list.html", {"uoms": uoms})


@login_required
def hq_master_uom_new(request):
    require_role(request.user, [Role.HQ, Role.CEO], request=request)
    if request.method == "POST":
        form = UoMForm(request.POST)
        if form.is_valid():
            uom = form.save()
            _log_action_safe(
                request.user,
                action="UOM_CREATE",
                object_id=uom.id,
                summary=f"UoM create: {uom.code}",
                metadata={"uom_id": uom.id, "code": uom.code},
                object_type="UoM",
            )
            messages.success(request, "단위가 생성되었습니다.")
            return redirect("/app/hq/master/uom/")
        messages.error(request, "입력 오류가 있습니다. 항목을 확인하세요.")
    else:
        form = UoMForm()
    return render(request, "app/hq/master_uom_form.html", {"form": form, "mode": "create"})


@login_required
def hq_master_uom_edit(request, uom_id):
    require_role(request.user, [Role.HQ, Role.CEO], request=request)
    uom = get_object_or_404(UoM, id=uom_id)
    if request.method == "POST":
        form = UoMForm(request.POST, instance=uom)
        if form.is_valid():
            before = {"code": uom.code, "name": uom.name, "is_active": uom.is_active}
            form.save()
            _log_action_safe(
                request.user,
                action="UOM_UPDATE",
                object_id=uom.id,
                summary=f"UoM update: {uom.code}",
                metadata={
                    "uom_id": uom.id,
                    "before": before,
                    "after": {"code": uom.code, "name": uom.name, "is_active": uom.is_active},
                },
                object_type="UoM",
            )
            messages.success(request, "단위 정보가 저장되었습니다.")
            return redirect("/app/hq/master/uom/")
        messages.error(request, "입력 오류가 있습니다. 항목을 확인하세요.")
    else:
        form = UoMForm(instance=uom)
    return render(
        request,
        "app/hq/master_uom_form.html",
        {"form": form, "mode": "edit", "uom": uom},
    )


@login_required
def hq_master_category_list(request):
    require_role(request.user, [Role.HQ, Role.CEO], request=request)
    categories = ItemCategory.objects.select_related("parent").order_by("sort_order", "name")
    return render(
        request,
        "app/hq/master_category_list.html",
        {"categories": categories},
    )


@login_required
def hq_master_category_new(request):
    require_role(request.user, [Role.HQ, Role.CEO], request=request)
    if request.method == "POST":
        form = ItemCategoryForm(request.POST)
        if form.is_valid():
            category = form.save()
            _log_action_safe(
                request.user,
                action="ITEM_CATEGORY_CREATE",
                object_id=category.id,
                summary=f"Category create: {category.name}",
                metadata={"category_id": category.id, "name": category.name},
                object_type="ItemCategory",
            )
            messages.success(request, "카테고리가 생성되었습니다.")
            return redirect("/app/hq/master/categories/")
        messages.error(request, "입력 오류가 있습니다. 항목을 확인하세요.")
    else:
        form = ItemCategoryForm()
    return render(
        request,
        "app/hq/master_category_form.html",
        {"form": form, "mode": "create"},
    )


@login_required
def hq_master_category_edit(request, category_id):
    require_role(request.user, [Role.HQ, Role.CEO], request=request)
    category = get_object_or_404(ItemCategory, id=category_id)
    if request.method == "POST":
        form = ItemCategoryForm(request.POST, instance=category)
        if form.is_valid():
            before = {
                "name": category.name,
                "code": category.code,
                "parent_id": category.parent_id,
                "sort_order": category.sort_order,
                "is_active": category.is_active,
            }
            form.save()
            _log_action_safe(
                request.user,
                action="ITEM_CATEGORY_UPDATE",
                object_id=category.id,
                summary=f"Category update: {category.name}",
                metadata={"category_id": category.id, "before": before},
                object_type="ItemCategory",
            )
            messages.success(request, "카테고리 정보가 저장되었습니다.")
            return redirect("/app/hq/master/categories/")
        messages.error(request, "입력 오류가 있습니다. 항목을 확인하세요.")
    else:
        form = ItemCategoryForm(instance=category)
    return render(
        request,
        "app/hq/master_category_form.html",
        {"form": form, "mode": "edit", "category": category},
    )


def _log_action_safe(actor, *, action, object_id, summary, metadata, object_type="Warehouse"):
    if actor is None:
        return
    try:
        log_action(
            actor=actor,
            action=action,
            object_type=object_type,
            object_id=object_id,
            summary=summary,
            metadata={
                "actor_role": get_user_role(actor),
                **metadata,
            },
        )
    except Exception:
        logger.warning("AuditLog failed for inventory action %s.", action, exc_info=True)
