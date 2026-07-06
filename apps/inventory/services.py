import logging
from datetime import date
from decimal import Decimal, ROUND_HALF_UP

from django.conf import settings
from django.core.exceptions import PermissionDenied, ValidationError
from django.db import transaction
from django.db.models import Q
from django.utils import timezone

from apps.audit.services.logger import log_action
from apps.closing.guards import assert_project_open
from apps.closing.services import is_month_closed
from apps.core.rbac.models import ProjectAssignment, Role
from apps.core.rbac.permissions import get_user_role, require_role
from apps.cost.models import CostActual, CostActualLine, CostActualStatus

from .models import (
    InventoryLedger,
    InventoryRefType,
    InventoryTxType,
    ItemCategory,
    ItemCodeSequence,
    ItemMaster,
    IssueNumberSequence,
    IssueStatus,
    IssueToWork,
    IssueToWorkLine,
    Location,
    Stock,
    Transfer,
    TransferDirection,
    TransferLine,
    TransferNumberSequence,
    TransferStatus,
    UoM,
    Warehouse,
    WarehouseType,
)

logger = logging.getLogger(__name__)


def ensure_default_location(warehouse, *, actor=None) -> Location:
    default_loc = warehouse.locations.filter(is_default=True).first()
    if default_loc:
        return default_loc
    location = Location.objects.create(
        warehouse=warehouse,
        name="기본 위치",
        code="MAIN",
        is_default=True,
    )
    _log_action_safe(
        actor,
        action="LOCATION_CREATE",
        object_id=location.id,
        summary=f"Location create: {warehouse.code} MAIN",
        metadata={"warehouse_id": warehouse.id, "warehouse_type": warehouse.warehouse_type},
        object_type="Location",
    )
    return location


def create_hq_warehouse(name, code, *, actor=None) -> Warehouse:
    with transaction.atomic():
        warehouse, created = Warehouse.objects.get_or_create(
            code=code,
            defaults={
                "name": name,
                "warehouse_type": WarehouseType.HQ,
                "project": None,
            },
        )
        if not created:
            warehouse.name = name
            warehouse.warehouse_type = WarehouseType.HQ
            warehouse.project = None
            warehouse.save(update_fields=["name", "warehouse_type", "project", "updated_at"])
            _log_action_safe(
                actor,
                action="WAREHOUSE_UPDATE",
                object_id=warehouse.id,
                summary=f"Warehouse update: {warehouse.code}",
                metadata={"warehouse_id": warehouse.id, "warehouse_type": warehouse.warehouse_type},
                object_type="Warehouse",
            )
        else:
            _log_action_safe(
                actor,
                action="WAREHOUSE_CREATE",
                object_id=warehouse.id,
                summary=f"Warehouse create: {warehouse.code}",
                metadata={"warehouse_id": warehouse.id, "warehouse_type": warehouse.warehouse_type},
                object_type="Warehouse",
            )
        ensure_default_location(warehouse, actor=actor)
        return warehouse


def create_site_warehouse(project, name=None, code=None, *, actor=None) -> Warehouse:
    if not project:
        raise ValueError("project is required for site warehouse")
    warehouse_name = name or f"{project.name} 창고"
    warehouse_code = code or f"SITE-{project.code}"
    with transaction.atomic():
        warehouse, created = Warehouse.objects.get_or_create(
            project=project,
            warehouse_type=WarehouseType.SITE,
            defaults={
                "name": warehouse_name,
                "code": warehouse_code,
            },
        )
        if not created:
            if warehouse.name != warehouse_name or warehouse.code != warehouse_code:
                warehouse.name = warehouse_name
                warehouse.code = warehouse_code
                warehouse.save(update_fields=["name", "code", "updated_at"])
                _log_action_safe(
                    actor,
                    action="WAREHOUSE_UPDATE",
                    object_id=warehouse.id,
                    summary=f"Warehouse update: {warehouse.code}",
                    metadata={
                        "warehouse_id": warehouse.id,
                        "warehouse_type": warehouse.warehouse_type,
                        "project_id": project.id,
                    },
                    object_type="Warehouse",
                )
        else:
            _log_action_safe(
                actor,
                action="WAREHOUSE_CREATE",
                object_id=warehouse.id,
                summary=f"Warehouse create: {warehouse.code}",
                metadata={
                    "warehouse_id": warehouse.id,
                    "warehouse_type": warehouse.warehouse_type,
                    "project_id": project.id,
                },
                object_type="Warehouse",
            )
        ensure_default_location(warehouse, actor=actor)
        return warehouse


def create_item(data, *, actor=None) -> ItemMaster:
    if actor is None:
        raise PermissionDenied("Actor required.")
    require_role(actor, [Role.HQ, Role.CEO])
    code = (data.get("code") or "").strip().upper()
    name = (data.get("name") or "").strip()
    uom = data.get("uom")
    category = data.get("category")
    if not name:
        raise ValueError("name is required")
    if not uom:
        raise ValueError("uom is required")
    if not code:
        code = _generate_item_code(category)
    item = ItemMaster.objects.create(
        code=code,
        name=name,
        category=category,
        uom=uom,
        spec=(data.get("spec") or "").strip(),
        description=(data.get("description") or "").strip(),
        barcode=(data.get("barcode") or "").strip(),
        is_active=bool(data.get("is_active", True)),
        created_by=actor,
        updated_by=actor,
    )
    _log_action_safe(
        actor,
        action="ITEM_CREATE",
        object_id=item.id,
        summary=f"Item create: {item.code}",
        metadata={"item_id": item.id, "code": item.code},
        object_type="ItemMaster",
    )
    return item


def update_item(item: ItemMaster, data, *, actor=None) -> ItemMaster:
    if actor is None:
        raise PermissionDenied("Actor required.")
    require_role(actor, [Role.HQ, Role.CEO])
    before = {
        "code": item.code,
        "name": item.name,
        "category_id": item.category_id,
        "uom_id": item.uom_id,
        "spec": item.spec,
        "description": item.description,
        "barcode": item.barcode,
        "is_active": item.is_active,
    }
    if "code" in data and data["code"]:
        item.code = str(data["code"]).strip().upper()
    if "name" in data and data["name"] is not None:
        item.name = str(data["name"]).strip()
    if "category" in data:
        item.category = data["category"]
    if "uom" in data:
        item.uom = data["uom"]
    if "spec" in data:
        item.spec = str(data.get("spec") or "").strip()
    if "description" in data:
        item.description = str(data.get("description") or "").strip()
    if "barcode" in data:
        item.barcode = str(data.get("barcode") or "").strip()
    if "is_active" in data:
        item.is_active = bool(data.get("is_active"))
    item.updated_by = actor
    item.save()
    _log_action_safe(
        actor,
        action="ITEM_UPDATE",
        object_id=item.id,
        summary=f"Item update: {item.code}",
        metadata={
            "item_id": item.id,
            "before": before,
            "after": {
                "code": item.code,
                "name": item.name,
                "category_id": item.category_id,
                "uom_id": item.uom_id,
                "spec": item.spec,
                "description": item.description,
                "barcode": item.barcode,
                "is_active": item.is_active,
            },
        },
        object_type="ItemMaster",
    )
    return item


def search_items(q=None, *, include_inactive=False, category_id=None, limit=30):
    qs = ItemMaster.objects.select_related("category", "uom").order_by("code")
    if not include_inactive:
        qs = qs.filter(is_active=True)
    if category_id:
        qs = qs.filter(category_id=category_id)
    if q:
        qs = qs.filter(
            Q(code__icontains=q)
            | Q(name__icontains=q)
            | Q(spec__icontains=q)
            | Q(barcode__icontains=q)
        )
    limit = max(1, min(int(limit or 30), 50))
    return qs[:limit]


def get_item_display(item: ItemMaster) -> str:
    parts = [item.code, item.name]
    if item.spec:
        parts.append(item.spec)
    if item.uom_id:
        parts.append(item.uom.code)
    return " | ".join(parts)


def _generate_item_code(category: ItemCategory | None) -> str:
    cat_code = (category.code or "").strip().upper() if category else ""
    if not cat_code:
        cat_code = "GEN"
    key = f"MAT-{cat_code}"
    with transaction.atomic():
        seq, _created = ItemCodeSequence.objects.select_for_update().get_or_create(
            key=key, defaults={"last_number": 0}
        )
        seq.last_number += 1
        seq.save(update_fields=["last_number", "updated_at"])
    return f"{key}-{seq.last_number:06d}"


def _log_action_safe(actor, *, action, object_id, summary, metadata, object_type):
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


def _normalize_qty(value) -> Decimal:
    if value is None:
        raise ValidationError({"qty": "qty is required."})
    try:
        qty = Decimal(str(value))
    except Exception as exc:
        raise ValidationError({"qty": "qty must be a number."}) from exc
    if qty == 0:
        raise ValidationError({"qty": "qty must not be zero."})
    return qty


def _closed_month_message(target_date: date) -> str:
    return (
        f"{target_date.year}년 {target_date.month}월은 마감되었습니다. "
        "마감 후 재고 이동은 정정/후속 절차로 처리해야 합니다."
    )

def _issue_closed_message(target_date: date) -> str:
    return (
        f"{target_date.year}년 {target_date.month}월은 마감되었습니다. "
        "마감월 자재 투입은 정정 절차로 처리해야 합니다."
    )



def _ensure_actor_can_use_warehouse(actor, warehouse: Warehouse) -> None:
    role = get_user_role(actor)
    if role in (Role.CEO, Role.HQ):
        return
    if role != Role.FIELD:
        raise PermissionDenied("User role not permitted.")
    if warehouse.warehouse_type == WarehouseType.HQ:
        raise PermissionDenied("HQ warehouse is read-only for field users.")
    if not ProjectAssignment.objects.filter(
        user=actor, project_id=warehouse.project_id, is_active=True
    ).exists():
        raise PermissionDenied("Project access denied.")


def create_ledger_entry(
    *,
    actor,
    tx_type: str,
    tx_date,
    warehouse: Warehouse,
    item: ItemMaster,
    qty_delta,
    uom: UoM | None = None,
    location: Location | None = None,
    unit_cost: int | None = None,
    note: str = "",
    ref_type: str = InventoryRefType.MANUAL,
    ref_id: int | None = None,
):
    if actor is None:
        raise PermissionDenied("Actor required.")
    if not isinstance(tx_date, date):
        raise ValidationError({"tx_date": "tx_date must be a date."})
    assert_project_open(
        warehouse.project if warehouse else None,
        message_context="재고 원장 기준일입니다.",
        exc=PermissionDenied,
    )
    if is_month_closed(tx_date):
        _log_action_safe(
            actor,
            action="INVENTORY_LEDGER_BLOCKED_CLOSED",
            object_id=None,
            summary="Inventory ledger blocked by closing period.",
            metadata={
                "tx_date": str(tx_date),
                "warehouse_id": warehouse.id if warehouse else None,
                "item_id": item.id if item else None,
            },
            object_type="InventoryLedger",
        )
        raise PermissionDenied(_closed_month_message(tx_date))
    _ensure_actor_can_use_warehouse(actor, warehouse)
    if tx_type not in InventoryTxType.values:
        raise ValidationError({"tx_type": "Invalid tx_type."})
    qty = _normalize_qty(qty_delta)
    if uom is None:
        uom = item.uom
    if uom.id != item.uom_id:
        raise ValidationError({"uom": "UoM must match item default unit."})
    if location and location.warehouse_id != warehouse.id:
        raise ValidationError({"location": "Location does not belong to warehouse."})
    if location is None:
        location = warehouse.locations.filter(is_default=True).first()
        if not location:
            location = ensure_default_location(warehouse, actor=actor)
    amount = None
    if unit_cost is not None:
        amount = int((qty * Decimal(unit_cost)).quantize(Decimal("1"), rounding=ROUND_HALF_UP))
    allow_negative = bool(getattr(settings, "INVENTORY_ALLOW_NEGATIVE", False))
    with transaction.atomic():
        stock = (
            Stock.objects.select_for_update()
            .filter(warehouse=warehouse, location=location, item=item)
            .first()
        )
        if not stock:
            stock = Stock.objects.create(
                warehouse=warehouse,
                location=location,
                item=item,
                qty_on_hand=Decimal("0"),
            )
        new_qty = stock.qty_on_hand + qty
        if not allow_negative and new_qty < 0:
            raise ValidationError(
                {
                    "qty": (
                        "\uD604\uC7AC\uACE0\uAC00 \uBD80\uC871\uD569\uB2C8\uB2E4. "
                        f"(\uD604\uC7AC: {stock.qty_on_hand}, \uC694\uCCAD: {qty})"
                    )
                }
            )
        ledger = InventoryLedger.objects.create(
            tx_type=tx_type,
            tx_date=tx_date,
            warehouse=warehouse,
            location=location,
            item=item,
            qty_delta=qty,
            uom=uom,
            unit_cost=unit_cost,
            amount=amount,
            ref_type=ref_type,
            ref_id=ref_id,
            note=note or "",
            created_by=actor,
        )
        stock.qty_on_hand = new_qty
        stock.save(update_fields=["qty_on_hand", "updated_at"])
    _log_action_safe(
        actor,
        action="INVENTORY_LEDGER_CREATE",
        object_id=ledger.id,
        summary=f"Inventory ledger create: {ledger.id}",
        metadata={
            "tx_type": ledger.tx_type,
            "tx_date": str(ledger.tx_date),
            "warehouse_id": warehouse.id,
            "location_id": location.id if location else None,
            "item_id": item.id,
            "qty_delta": str(ledger.qty_delta),
            "qty_on_hand_after": str(stock.qty_on_hand),
        },
        object_type="InventoryLedger",
    )
    _log_action_safe(
        actor,
        action="STOCK_UPDATE",
        object_id=stock.id,
        summary=f"Stock update: {stock.id}",
        metadata={
            "warehouse_id": warehouse.id,
            "location_id": location.id if location else None,
            "item_id": item.id,
            "qty_on_hand": str(stock.qty_on_hand),
        },
        object_type="Stock",
    )
    return ledger, stock


def _generate_transfer_no(tx_date: date) -> str:
    key = f"TR-{tx_date.year}{tx_date.month:02d}"
    with transaction.atomic():
        seq, _created = TransferNumberSequence.objects.select_for_update().get_or_create(
            key=key, defaults={"last_number": 0}
        )
        seq.last_number += 1
        seq.save(update_fields=["last_number", "updated_at"])
    return f"{key}-{seq.last_number:04d}"


def _validate_transfer_direction(direction, project, from_warehouse, to_warehouse):
    if direction not in TransferDirection.values:
        raise ValidationError({"direction": "Invalid direction."})
    if from_warehouse.id == to_warehouse.id:
        raise ValidationError({"warehouse": "from_warehouse and to_warehouse must differ."})
    if direction == TransferDirection.HQ_TO_SITE:
        if not project:
            raise ValidationError({"project": "Project is required for HQ_TO_SITE."})
        if from_warehouse.warehouse_type != WarehouseType.HQ:
            raise ValidationError({"from_warehouse": "from_warehouse must be HQ."})
        if to_warehouse.warehouse_type != WarehouseType.SITE:
            raise ValidationError({"to_warehouse": "to_warehouse must be SITE."})
        if to_warehouse.project_id != project.id:
            raise ValidationError({"to_warehouse": "to_warehouse project mismatch."})
    if direction == TransferDirection.SITE_TO_HQ:
        if not project:
            raise ValidationError({"project": "Project is required for SITE_TO_HQ."})
        if from_warehouse.warehouse_type != WarehouseType.SITE:
            raise ValidationError({"from_warehouse": "from_warehouse must be SITE."})
        if to_warehouse.warehouse_type != WarehouseType.HQ:
            raise ValidationError({"to_warehouse": "to_warehouse must be HQ."})
        if from_warehouse.project_id != project.id:
            raise ValidationError({"from_warehouse": "from_warehouse project mismatch."})


def _ensure_actor_can_receive(actor, transfer: Transfer) -> None:
    role = get_user_role(actor)
    if role in (Role.CEO, Role.HQ):
        return
    if role != Role.FIELD:
        raise PermissionDenied("User role not permitted.")
    if not transfer.project_id:
        raise PermissionDenied("Project access denied.")
    if not ProjectAssignment.objects.filter(
        user=actor, project_id=transfer.project_id, is_active=True
    ).exists():
        raise PermissionDenied("Project access denied.")


def create_transfer(
    *,
    actor,
    direction: str,
    project,
    from_warehouse: Warehouse,
    to_warehouse: Warehouse,
    tx_date: date,
    note: str,
    lines: list[dict],
    from_location: Location | None = None,
    to_location: Location | None = None,
) -> Transfer:
    require_role(actor, [Role.HQ, Role.CEO])
    assert_project_open(project, message_context="재고 이동 기준일입니다.", exc=PermissionDenied)
    if is_month_closed(tx_date):
        raise PermissionDenied(_closed_month_message(tx_date))
    _validate_transfer_direction(direction, project, from_warehouse, to_warehouse)
    if not from_location:
        from_location = from_warehouse.locations.filter(is_default=True).first()
        if not from_location:
            from_location = ensure_default_location(from_warehouse, actor=actor)
    if not to_location:
        to_location = to_warehouse.locations.filter(is_default=True).first()
        if not to_location:
            to_location = ensure_default_location(to_warehouse, actor=actor)
    if not lines:
        raise ValidationError({"lines": "At least one line is required."})
    with transaction.atomic():
        transfer = Transfer.objects.create(
            transfer_no=_generate_transfer_no(tx_date),
            direction=direction,
            project=project,
            from_warehouse=from_warehouse,
            from_location=from_location,
            to_warehouse=to_warehouse,
            to_location=to_location,
            tx_date=tx_date,
            status=TransferStatus.DRAFT,
            note=note or "",
            created_by=actor,
        )
        created_lines = []
        for line in lines:
            item = line["item"]
            qty = _normalize_qty(line["qty"])
            if qty <= 0:
                raise ValidationError({"qty": "qty must be greater than zero."})
            if not item.is_active:
                raise ValidationError({"item": "Item must be active."})
            uom = line.get("uom") or item.uom
            if uom.id != item.uom_id:
                raise ValidationError({"uom": "UoM must match item default unit."})
            created_lines.append(
                TransferLine(
                    transfer=transfer,
                    item=item,
                    uom=uom,
                    qty=qty,
                    note=str(line.get("note") or "").strip(),
                )
            )
        TransferLine.objects.bulk_create(created_lines)
    _log_action_safe(
        actor,
        action="TRANSFER_CREATE",
        object_id=transfer.id,
        summary=f"Transfer create: {transfer.transfer_no}",
        metadata={
            "transfer_id": transfer.id,
            "transfer_no": transfer.transfer_no,
            "project_id": project.id if project else None,
            "status": transfer.status,
        },
        object_type="Transfer",
    )
    return transfer


def submit_transfer(transfer: Transfer, *, actor) -> Transfer:
    require_role(actor, [Role.HQ, Role.CEO])
    if transfer.status != TransferStatus.DRAFT:
        raise ValidationError({"status": "Transfer is not in DRAFT."})
    assert_project_open(transfer.project, message_context="?? ??????.", exc=PermissionDenied)
    if is_month_closed(transfer.tx_date):
        raise PermissionDenied(_closed_month_message(transfer.tx_date))
    transfer.status = TransferStatus.SUBMITTED
    transfer.submitted_at = timezone.now()
    transfer.save(update_fields=["status", "submitted_at", "updated_at"])
    _log_action_safe(
        actor,
        action="TRANSFER_SUBMIT",
        object_id=transfer.id,
        summary=f"Transfer submit: {transfer.transfer_no}",
        metadata={"transfer_id": transfer.id, "transfer_no": transfer.transfer_no},
        object_type="Transfer",
    )
    return transfer


def issue_transfer(transfer: Transfer, *, actor) -> Transfer:
    require_role(actor, [Role.HQ, Role.CEO])
    if transfer.status != TransferStatus.SUBMITTED:
        raise ValidationError({"status": "Transfer is not in SUBMITTED."})
    assert_project_open(transfer.project, message_context="?? ??????.", exc=PermissionDenied)
    if is_month_closed(transfer.tx_date):
        raise PermissionDenied(_closed_month_message(transfer.tx_date))
    with transaction.atomic():
        transfer = (
            Transfer.objects.select_for_update()
            .select_related("from_warehouse", "from_location")
            .get(id=transfer.id)
        )
        if transfer.status != TransferStatus.SUBMITTED:
            raise ValidationError({"status": "Transfer is not in SUBMITTED."})
        lines = list(transfer.lines.select_related("item", "uom"))
        for line in lines:
            create_ledger_entry(
                actor=actor,
                tx_type=InventoryTxType.ISSUE,
                tx_date=transfer.tx_date,
                warehouse=transfer.from_warehouse,
                location=transfer.from_location,
                item=line.item,
                qty_delta=-line.qty,
                uom=line.uom,
                note=f"Transfer issue {transfer.transfer_no}",
                ref_type=InventoryRefType.TRANSFER,
                ref_id=transfer.id,
            )
        transfer.status = TransferStatus.ISSUED
        transfer.issued_at = timezone.now()
        transfer.save(update_fields=["status", "issued_at", "updated_at"])
    _log_action_safe(
        actor,
        action="TRANSFER_ISSUE",
        object_id=transfer.id,
        summary=f"Transfer issue: {transfer.transfer_no}",
        metadata={"transfer_id": transfer.id, "transfer_no": transfer.transfer_no},
        object_type="Transfer",
    )
    return transfer


def receive_transfer(transfer: Transfer, *, actor) -> Transfer:
    _ensure_actor_can_receive(actor, transfer)
    if transfer.status != TransferStatus.ISSUED:
        raise ValidationError({"status": "Transfer is not in ISSUED."})
    assert_project_open(transfer.project, message_context="?? ??????.", exc=PermissionDenied)
    if is_month_closed(transfer.tx_date):
        raise PermissionDenied(_closed_month_message(transfer.tx_date))
    with transaction.atomic():
        transfer = (
            Transfer.objects.select_for_update()
            .select_related("to_warehouse", "to_location")
            .get(id=transfer.id)
        )
        if transfer.status != TransferStatus.ISSUED:
            raise ValidationError({"status": "Transfer is not in ISSUED."})
        lines = list(transfer.lines.select_related("item", "uom"))
        for line in lines:
            create_ledger_entry(
                actor=actor,
                tx_type=InventoryTxType.RECEIPT,
                tx_date=transfer.tx_date,
                warehouse=transfer.to_warehouse,
                location=transfer.to_location,
                item=line.item,
                qty_delta=line.qty,
                uom=line.uom,
                note=f"Transfer receive {transfer.transfer_no}",
                ref_type=InventoryRefType.TRANSFER,
                ref_id=transfer.id,
            )
        transfer.status = TransferStatus.RECEIVED
        transfer.received_at = timezone.now()
        transfer.save(update_fields=["status", "received_at", "updated_at"])
    _log_action_safe(
        actor,
        action="TRANSFER_RECEIVE",
        object_id=transfer.id,
        summary=f"Transfer receive: {transfer.transfer_no}",
        metadata={"transfer_id": transfer.id, "transfer_no": transfer.transfer_no},
        object_type="Transfer",
    )
    return transfer


def cancel_transfer(transfer: Transfer, *, actor) -> Transfer:
    require_role(actor, [Role.HQ, Role.CEO])
    if transfer.status not in (TransferStatus.DRAFT, TransferStatus.SUBMITTED):
        raise ValidationError({"status": "Transfer cannot be cancelled."})
    assert_project_open(transfer.project, message_context="?? ??????.", exc=PermissionDenied)
    if is_month_closed(transfer.tx_date):
        raise PermissionDenied(_closed_month_message(transfer.tx_date))
    transfer.status = TransferStatus.CANCELLED
    transfer.cancelled_at = timezone.now()
    transfer.save(update_fields=["status", "cancelled_at", "updated_at"])
    _log_action_safe(
        actor,
        action="TRANSFER_CANCEL",
        object_id=transfer.id,
        summary=f"Transfer cancel: {transfer.transfer_no}",
        metadata={"transfer_id": transfer.id, "transfer_no": transfer.transfer_no},
        object_type="Transfer",
    )
    return transfer


def _generate_issue_no(target_date: date) -> str:
    key = f"IW-{target_date.strftime('%Y%m')}"
    with transaction.atomic():
        seq, _created = IssueNumberSequence.objects.select_for_update().get_or_create(
            key=key
        )
        seq.last_number += 1
        seq.save(update_fields=["last_number", "updated_at"])
        return f"{key}-{seq.last_number:04d}"


def _ensure_actor_can_use_issue_project(actor, project_id) -> None:
    role = get_user_role(actor)
    if role in (Role.CEO, Role.HQ):
        return
    if role != Role.FIELD:
        raise PermissionDenied("User role not permitted.")
    if not ProjectAssignment.objects.filter(
        user=actor, project_id=project_id, is_active=True
    ).exists():
        raise PermissionDenied("Project access denied.")


def _resolve_issue_warehouse(actor, project, warehouse_id=None) -> Warehouse:
    role = get_user_role(actor)
    if warehouse_id:
        warehouse = Warehouse.objects.select_related("project").get(id=warehouse_id)
    else:
        warehouse = Warehouse.objects.filter(
            project=project,
            warehouse_type=WarehouseType.SITE,
            is_active=True,
        ).first()
        if warehouse is None:
            raise ValidationError({"warehouse": "현장 창고를 찾을 수 없습니다."})
    if role == Role.FIELD:
        if warehouse.warehouse_type != WarehouseType.SITE:
            raise PermissionDenied("Field users can use site warehouse only.")
        if warehouse.project_id != project.id:
            raise PermissionDenied("Project warehouse mismatch.")
    if not warehouse.is_active:
        raise ValidationError({"warehouse": "Warehouse is inactive."})
    return warehouse


def _build_issue_lines(lines_payload: list[dict], *, actor) -> list[IssueToWorkLine]:
    if not lines_payload:
        raise ValidationError({"lines": "At least one line is required."})
    created_lines = []
    seen_items = set()
    for payload in lines_payload:
        item_id = payload.get("item_id")
        cbs_id = payload.get("cbs_id")
        qty = _normalize_qty(payload.get("qty"))
        memo = str(payload.get("memo") or "").strip()
        if not item_id or not cbs_id:
            raise ValidationError({"lines": "item_id and cbs_id are required."})
        if item_id in seen_items:
            raise ValidationError({"lines": "Duplicate item in lines."})
        seen_items.add(item_id)
        item = ItemMaster.objects.select_related("uom").get(id=item_id)
        if not item.is_active:
            raise ValidationError({"item_id": "Inactive item cannot be used."})
        cbs_model = IssueToWorkLine._meta.get_field("cbs").remote_field.model
        cbs = cbs_model.objects.filter(id=cbs_id).first()
        if not cbs:
            raise ValidationError({"cbs_id": "CBS item not found."})
        if hasattr(cbs, "is_active") and not cbs.is_active:
            raise ValidationError({"cbs_id": "Inactive CBS cannot be used."})
        created_lines.append(
            IssueToWorkLine(
                item=item,
                qty=qty,
                uom=item.uom,
                cbs=cbs,
                memo=memo,
            )
        )
    return created_lines


def create_issue_to_work(
    *,
    actor,
    project,
    issue_date,
    lines_payload: list[dict],
    note: str = "",
    warehouse_id=None,
    location_id=None,
) -> IssueToWork:
    if actor is None:
        raise PermissionDenied("Actor required.")
    if not isinstance(issue_date, date):
        raise ValidationError({"issue_date": "issue_date must be a date."})
    assert_project_open(project, message_context="?? ??????.", exc=PermissionDenied)
    if is_month_closed(issue_date):
        raise PermissionDenied(_issue_closed_message(issue_date))
    _ensure_actor_can_use_issue_project(actor, project.id)
    warehouse = _resolve_issue_warehouse(actor, project, warehouse_id)
    location = None
    if location_id:
        location = Location.objects.filter(id=location_id, warehouse=warehouse).first()
        if not location:
            raise ValidationError({"location": "Invalid location for warehouse."})
    if location is None:
        location = warehouse.locations.filter(is_default=True).first()
        if not location:
            location = ensure_default_location(warehouse, actor=actor)
    lines = _build_issue_lines(lines_payload, actor=actor)
    with transaction.atomic():
        issue = IssueToWork.objects.create(
            issue_no=_generate_issue_no(issue_date),
            project=project,
            warehouse=warehouse,
            location=location,
            issue_date=issue_date,
            status=IssueStatus.DRAFT,
            note=str(note or "").strip(),
            created_by=actor,
        )
        for line in lines:
            line.issue = issue
        IssueToWorkLine.objects.bulk_create(lines)
        _log_action_safe(
            actor,
            action="ISSUE_TO_WORK_CREATE",
            object_id=issue.id,
            summary=f"Issue create: {issue.issue_no}",
            metadata={
                "issue_no": issue.issue_no,
                "project_id": issue.project_id,
                "issue_date": str(issue.issue_date),
                "line_count": len(lines),
            },
            object_type="IssueToWork",
        )
    return issue


def update_issue_to_work(
    issue: IssueToWork,
    *,
    actor,
    issue_date,
    lines_payload: list[dict],
    note: str = "",
    location_id=None,
) -> IssueToWork:
    if issue.status != IssueStatus.DRAFT:
        raise ValidationError({"status": "Issue is not in DRAFT."})
    if get_user_role(actor) == Role.FIELD and issue.created_by_id != actor.id:
        raise PermissionDenied("Only creator can update draft issue.")
    if not isinstance(issue_date, date):
        raise ValidationError({"issue_date": "issue_date must be a date."})
    assert_project_open(issue.project, message_context="자재 투입 수정 기준입니다.", exc=PermissionDenied)
    if is_month_closed(issue_date):
        raise PermissionDenied(_issue_closed_message(issue_date))
    lines = _build_issue_lines(lines_payload, actor=actor)
    location = issue.location
    if location_id:
        location = Location.objects.filter(id=location_id, warehouse=issue.warehouse).first()
        if not location:
            raise ValidationError({"location": "Invalid location for warehouse."})
    with transaction.atomic():
        issue.issue_date = issue_date
        issue.note = str(note or "").strip()
        issue.location = location
        issue.save(update_fields=["issue_date", "note", "location", "updated_at"])
        IssueToWorkLine.objects.filter(issue=issue).delete()
        for line in lines:
            line.issue = issue
        IssueToWorkLine.objects.bulk_create(lines)
        _log_action_safe(
            actor,
            action="ISSUE_TO_WORK_UPDATE",
            object_id=issue.id,
            summary=f"Issue update: {issue.issue_no}",
            metadata={
                "issue_no": issue.issue_no,
                "project_id": issue.project_id,
                "issue_date": str(issue.issue_date),
                "line_count": len(lines),
            },
            object_type="IssueToWork",
        )
    return issue


def submit_issue_to_work(issue: IssueToWork, *, actor) -> IssueToWork:
    if issue.status != IssueStatus.DRAFT:
        raise ValidationError({"status": "Issue is not in DRAFT."})
    if get_user_role(actor) == Role.FIELD and issue.created_by_id != actor.id:
        raise PermissionDenied("Only creator can submit issue.")
    assert_project_open(issue.project, message_context="?? ??????.", exc=PermissionDenied)
    if is_month_closed(issue.issue_date):
        raise PermissionDenied(_issue_closed_message(issue.issue_date))
    lines = list(issue.lines.select_related("item", "uom", "cbs"))
    if not lines:
        raise ValidationError({"lines": "At least one line is required."})
    with transaction.atomic():
        issue = IssueToWork.objects.select_for_update().get(id=issue.id)
        if issue.status != IssueStatus.DRAFT:
            raise ValidationError({"status": "Issue is not in DRAFT."})
        total_amount = 0
        cost_actual = CostActual.objects.create(
            project=issue.project,
            report_date=issue.issue_date,
            status=CostActualStatus.SUBMITTED,
        )
        for line in lines:
            unit_cost = line.unit_cost
            if unit_cost is None:
                unit_cost = line.item.standard_cost
            if unit_cost is None:
                unit_cost = 0
            amount = int(
                (line.qty * Decimal(unit_cost)).quantize(
                    Decimal("1"), rounding=ROUND_HALF_UP
                )
            )
            line.unit_cost = unit_cost
            line.amount = amount
            line.save(update_fields=["unit_cost", "amount"])
            total_amount += amount
            create_ledger_entry(
                actor=actor,
                tx_type=InventoryTxType.ISSUE,
                tx_date=issue.issue_date,
                warehouse=issue.warehouse,
                location=issue.location,
                item=line.item,
                qty_delta=-line.qty,
                uom=line.uom,
                unit_cost=unit_cost,
                note=f"Issue {issue.issue_no} {line.cbs.code}",
                ref_type=InventoryRefType.ISSUE_TO_WORK,
                ref_id=issue.id,
            )
            CostActualLine.objects.create(
                cost_actual=cost_actual,
                cost_item=line.cbs,
                description=(
                    f"[자재투입] {line.item.code} {line.item.name} "
                    f"{line.qty}{line.uom.code} (IW {issue.issue_no}) {line.memo}"
                ),
                quantity=line.qty,
                unit_price=Decimal(unit_cost),
                amount=Decimal(amount),
            )
        issue.status = IssueStatus.SUBMITTED
        issue.submitted_at = timezone.now()
        issue.save(update_fields=["status", "submitted_at", "updated_at"])
        _log_action_safe(
            actor,
            action="ISSUE_TO_WORK_SUBMIT",
            object_id=issue.id,
            summary=f"Issue submit: {issue.issue_no}",
            metadata={
                "issue_no": issue.issue_no,
                "project_id": issue.project_id,
                "issue_date": str(issue.issue_date),
                "line_count": len(lines),
                "total_amount": total_amount,
            },
            object_type="IssueToWork",
        )
        _log_action_safe(
            actor,
            action="AUTO_COSTACTUAL_CREATE_FROM_ISSUE",
            object_id=cost_actual.id,
            summary=f"CostActual from issue: {issue.issue_no}",
            metadata={
                "issue_no": issue.issue_no,
                "project_id": issue.project_id,
                "issue_date": str(issue.issue_date),
            },
            object_type="CostActual",
        )
    return issue
