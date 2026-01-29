import logging
from datetime import date

from django.contrib import messages
from django.contrib.auth.decorators import login_required
from django.core.exceptions import PermissionDenied, ValidationError
from django.db import transaction
from django.db.models import Q
from django.shortcuts import get_object_or_404, redirect, render

from apps.audit.services.logger import log_action
from apps.core.rbac.models import ProjectAssignment, Role
from apps.core.rbac.permissions import get_user_role, require_role

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
    IssueToWork,
    Location,
    UoM,
    Warehouse,
    WarehouseType,
)
from .services import (
    create_hq_warehouse,
    create_item,
    create_issue_to_work,
    ensure_default_location,
    submit_issue_to_work,
    update_item,
)

logger = logging.getLogger(__name__)


def _field_warehouse_queryset(user):
    assigned_project_ids = ProjectAssignment.objects.filter(
        user=user, is_active=True
    ).values_list("project_id", flat=True)
    return Warehouse.objects.select_related("project").filter(
        Q(warehouse_type=WarehouseType.HQ) | Q(project_id__in=assigned_project_ids)
    )


@login_required
def hq_warehouse_list(request):
    require_role(request.user, [Role.HQ, Role.CEO], request=request)
    warehouses = (
        Warehouse.objects.select_related("project")
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
        Warehouse.objects.select_related("project").prefetch_related("locations"),
        id=warehouse_id,
    )
    locations = warehouse.locations.order_by("-is_default", "name")
    return render(
        request,
        "app/hq/warehouse_detail.html",
        {"warehouse": warehouse, "locations": locations, "role": get_user_role(request.user)},
    )


@login_required
def field_warehouse_list(request):
    require_role(request.user, [Role.FIELD], request=request)
    warehouses = _field_warehouse_queryset(request.user).prefetch_related("locations")
    return render(
        request,
        "app/field/warehouse_list.html",
        {"warehouses": warehouses, "role": get_user_role(request.user)},
    )


@login_required
def field_inventory_issue_form(request):
    require_role(request.user, [Role.FIELD], request=request)
    assigned_projects = Project.objects.filter(
        projectassignment__user=request.user, projectassignment__is_active=True
    ).distinct()
    if not assigned_projects.exists():
        messages.error(request, "배정된 프로젝트가 없어 자재 투입을 등록할 수 없습니다.")
        return render(
            request,
            "app/field/inventory_issue_form.html",
            {"projects": [], "items": [], "cbs_items": [], "issues": []},
        )
    items = ItemMaster.objects.filter(is_active=True).order_by("code")[:200]
    cbs_items = CostItem.objects.filter(is_active=True).order_by("code")[:200]
    issues = (
        IssueToWork.objects.select_related("project")
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
            qty = request.POST.get(f"lines-{idx}-qty")
            memo = request.POST.get(f"lines-{idx}-memo") or ""
            if not item_id and not cbs_id and not qty:
                continue
            lines_payload.append(
                {
                    "item_id": item_id,
                    "cbs_id": cbs_id,
                    "qty": qty,
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
                        "자재 투입이 제출되었습니다. 원가 실적과 재고 원장이 자동 생성되었습니다.",
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
def hq_master_warehouse_new(request):
    require_role(request.user, [Role.HQ, Role.CEO], request=request)
    if request.method == "POST":
        form = WarehouseCreateForm(request.POST)
        if form.is_valid():
            create_hq_warehouse(
                name=form.cleaned_data["name"],
                code=form.cleaned_data["code"],
                actor=request.user,
            )
            messages.success(request, "본사 창고가 생성되었습니다.")
            return redirect("/app/hq/master/warehouses/")
        messages.error(request, "입력 오류가 있습니다. 항목을 확인하세요.")
    else:
        form = WarehouseCreateForm()
    return render(
        request,
        "app/hq/master_warehouse_form.html",
        {"form": form, "mode": "create"},
    )


@login_required
def hq_master_warehouse_edit(request, warehouse_id):
    require_role(request.user, [Role.HQ, Role.CEO], request=request)
    warehouse = get_object_or_404(Warehouse, id=warehouse_id)
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
