from datetime import date

from django.core.exceptions import PermissionDenied, ValidationError
from django.db.models import Q
from django.shortcuts import get_object_or_404
from rest_framework.response import Response
from rest_framework.views import APIView

from apps.core.rbac.models import ProjectAssignment, Role
from apps.core.rbac.permissions import get_user_role, require_role
from apps.audit.services.logger import log_action
from apps.projects.models import Project

from .models import (
    InventoryLedger,
    IssueToWork,
    ItemCategory,
    ItemMaster,
    Location,
    Stock,
    Transfer,
    TransferDirection,
    TransferStatus,
    UoM,
    Warehouse,
    WarehouseType,
)
from .services import (
    create_hq_warehouse,
    create_ledger_entry,
    create_issue_to_work,
    create_transfer,
    create_item,
    create_site_warehouse,
    ensure_default_location,
    get_item_display,
    receive_transfer,
    search_items,
    submit_transfer,
    issue_transfer,
    cancel_transfer,
    update_item,
    submit_issue_to_work,
    update_issue_to_work,
)


class WarehouseListView(APIView):
    def get(self, request):
        role = get_user_role(request.user)
        qs = Warehouse.objects.select_related("project").order_by("warehouse_type", "name")
        if role == Role.FIELD:
            assigned_project_ids = ProjectAssignment.objects.filter(
                user=request.user, is_active=True
            ).values_list("project_id", flat=True)
            qs = qs.filter(
                Q(warehouse_type=WarehouseType.HQ) | Q(project_id__in=assigned_project_ids)
            )
        data = [
            {
                "id": wh.id,
                "name": wh.name,
                "code": wh.code,
                "warehouse_type": wh.warehouse_type,
                "project_id": wh.project_id,
                "is_active": wh.is_active,
            }
            for wh in qs
        ]
        return Response(data)

    def post(self, request):
        require_role(request.user, [Role.HQ, Role.CEO], request=request)
        payload = request.data or {}
        warehouse_type = str(payload.get("warehouse_type", "")).lower()
        name = str(payload.get("name", "")).strip()
        code = str(payload.get("code", "")).strip()
        project_id = payload.get("project_id")
        if not name or not code:
            return Response({"detail": "name and code are required."}, status=400)
        if warehouse_type not in (WarehouseType.HQ, WarehouseType.SITE):
            return Response({"detail": "warehouse_type must be HQ or SITE."}, status=400)
        if warehouse_type == WarehouseType.HQ:
            warehouse = create_hq_warehouse(name, code, actor=request.user)
        else:
            if not project_id:
                return Response({"detail": "project_id is required for SITE."}, status=400)
            project = get_object_or_404(Project, id=project_id)
            warehouse = create_site_warehouse(project, name=name, code=code, actor=request.user)
        return Response(
            {
                "id": warehouse.id,
                "name": warehouse.name,
                "code": warehouse.code,
                "warehouse_type": warehouse.warehouse_type,
                "project_id": warehouse.project_id,
                "is_active": warehouse.is_active,
            },
            status=201,
        )


class WarehouseLocationsView(APIView):
    def get(self, request, warehouse_id):
        role = get_user_role(request.user)
        warehouse = get_object_or_404(Warehouse.objects.select_related("project"), id=warehouse_id)
        if role == Role.FIELD:
            if warehouse.warehouse_type == WarehouseType.SITE:
                if not ProjectAssignment.objects.filter(
                    user=request.user, project_id=warehouse.project_id, is_active=True
                ).exists():
                    return Response({"detail": "Project access denied."}, status=403)
        locations = warehouse.locations.order_by("-is_default", "name")
        data = [
            {
                "id": loc.id,
                "name": loc.name,
                "code": loc.code,
                "is_default": loc.is_default,
                "is_active": loc.is_active,
            }
            for loc in locations
        ]
        return Response(
            {
                "warehouse_id": warehouse.id,
                "warehouse_type": warehouse.warehouse_type,
                "project_id": warehouse.project_id,
                "locations": data,
            }
        )


class LocationCreateView(APIView):
    def post(self, request):
        require_role(request.user, [Role.HQ, Role.CEO], request=request)
        payload = request.data or {}
        warehouse_id = payload.get("warehouse_id")
        name = str(payload.get("name", "")).strip()
        code = str(payload.get("code", "")).strip()
        is_default = bool(payload.get("is_default", False))
        if not warehouse_id or not name or not code:
            return Response({"detail": "warehouse_id, name, code required."}, status=400)
        warehouse = get_object_or_404(Warehouse, id=warehouse_id)
        if is_default:
            warehouse.locations.filter(is_default=True).update(is_default=False)
        location = Location.objects.create(
            warehouse=warehouse,
            name=name,
            code=code,
            is_default=is_default,
        )
        if not warehouse.locations.filter(is_default=True).exists():
            ensure_default_location(warehouse, actor=request.user)
        try:
            log_action(
                actor=request.user,
                action="LOCATION_CREATE",
                object_type="Location",
                object_id=location.id,
                summary=f"Location create: {warehouse.code} {location.code}",
                metadata={
                    "warehouse_id": warehouse.id,
                    "warehouse_type": warehouse.warehouse_type,
                    "project_id": warehouse.project_id,
                },
            )
        except Exception:
            pass
        return Response(
            {
                "id": location.id,
                "warehouse_id": warehouse.id,
                "name": location.name,
                "code": location.code,
                "is_default": location.is_default,
                "is_active": location.is_active,
            },
            status=201,
        )


class ItemListView(APIView):
    def get(self, request):
        role = get_user_role(request.user)
        q = (request.GET.get("q") or "").strip()
        category_id = request.GET.get("category")
        active = (request.GET.get("active") or "").lower()
        limit = request.GET.get("limit") or 30
        include_inactive = False
        if active in ("0", "false"):
            include_inactive = True
        elif active in ("all", "any"):
            include_inactive = True
        if role not in (Role.HQ, Role.CEO) and active in ("0", "false", "all", "any"):
            return Response({"detail": "Inactive items are not allowed."}, status=403)
        items = search_items(
            q,
            include_inactive=include_inactive,
            category_id=category_id,
            limit=limit,
        )
        if active in ("0", "false"):
            items = [item for item in items if not item.is_active]
        elif active in ("1", "true", ""):
            items = [item for item in items if item.is_active]
        data = [
            {
                "id": item.id,
                "code": item.code,
                "name": item.name,
                "spec": item.spec,
                "barcode": item.barcode,
                "is_active": item.is_active,
                "uom": {"id": item.uom_id, "code": item.uom.code, "name": item.uom.name},
                "category": {
                    "id": item.category_id,
                    "name": item.category.name if item.category else None,
                },
                "display_label": get_item_display(item),
            }
            for item in items
        ]
        return Response(data)

    def post(self, request):
        require_role(request.user, [Role.HQ, Role.CEO], request=request)
        payload = request.data or {}
        uom_id = payload.get("uom_id")
        category_id = payload.get("category_id")
        uom = get_object_or_404(UoM, id=uom_id)
        category = None
        if category_id:
            category = get_object_or_404(ItemCategory, id=category_id)
        item = create_item(
            {
                "code": payload.get("code"),
                "name": payload.get("name"),
                "category": category,
                "uom": uom,
                "spec": payload.get("spec"),
                "description": payload.get("description"),
                "barcode": payload.get("barcode"),
                "is_active": payload.get("is_active", True),
            },
            actor=request.user,
        )
        return Response(
            {
                "id": item.id,
                "code": item.code,
                "name": item.name,
                "spec": item.spec,
                "barcode": item.barcode,
                "is_active": item.is_active,
                "uom": {"id": item.uom_id, "code": item.uom.code, "name": item.uom.name},
                "category": {
                    "id": item.category_id,
                    "name": item.category.name if item.category else None,
                },
                "display_label": get_item_display(item),
            },
            status=201,
        )


class ItemDetailView(APIView):
    def get(self, request, item_id):
        item = get_object_or_404(ItemMaster.objects.select_related("category", "uom"), id=item_id)
        return Response(
            {
                "id": item.id,
                "code": item.code,
                "name": item.name,
                "spec": item.spec,
                "barcode": item.barcode,
                "is_active": item.is_active,
                "uom": {"id": item.uom_id, "code": item.uom.code, "name": item.uom.name},
                "category": {
                    "id": item.category_id,
                    "name": item.category.name if item.category else None,
                },
                "display_label": get_item_display(item),
            }
        )


class InventoryLedgerView(APIView):
    def get(self, request):
        role = get_user_role(request.user)
        qs = InventoryLedger.objects.select_related(
            "warehouse",
            "location",
            "item",
            "uom",
            "created_by",
        ).order_by("-tx_date", "-id")
        if role == Role.FIELD:
            assigned_project_ids = ProjectAssignment.objects.filter(
                user=request.user, is_active=True
            ).values_list("project_id", flat=True)
            allowed_warehouse_ids = Warehouse.objects.filter(
                Q(warehouse_type=WarehouseType.HQ)
                | Q(project_id__in=assigned_project_ids, warehouse_type=WarehouseType.SITE)
            ).values_list("id", flat=True)
            qs = qs.filter(warehouse_id__in=allowed_warehouse_ids)
        warehouse_id = request.GET.get("warehouse")
        item_id = request.GET.get("item")
        start = request.GET.get("start")
        end = request.GET.get("end")
        q = (request.GET.get("q") or "").strip()
        limit = max(1, min(int(request.GET.get("limit") or 50), 200))
        if warehouse_id:
            qs = qs.filter(warehouse_id=warehouse_id)
        if item_id:
            qs = qs.filter(item_id=item_id)
        if start:
            qs = qs.filter(tx_date__gte=start)
        if end:
            qs = qs.filter(tx_date__lte=end)
        if q:
            qs = qs.filter(
                Q(item__code__icontains=q)
                | Q(item__name__icontains=q)
                | Q(item__spec__icontains=q)
                | Q(item__barcode__icontains=q)
                | Q(note__icontains=q)
            )
        data = [
            {
                "id": entry.id,
                "tx_type": entry.tx_type,
                "tx_date": entry.tx_date,
                "warehouse": {
                    "id": entry.warehouse_id,
                    "code": entry.warehouse.code,
                    "name": entry.warehouse.name,
                    "warehouse_type": entry.warehouse.warehouse_type,
                },
                "location": {
                    "id": entry.location_id,
                    "code": entry.location.code if entry.location else None,
                    "name": entry.location.name if entry.location else None,
                },
                "item": {
                    "id": entry.item_id,
                    "code": entry.item.code,
                    "name": entry.item.name,
                    "spec": entry.item.spec,
                },
                "qty_delta": str(entry.qty_delta),
                "uom": {
                    "id": entry.uom_id,
                    "code": entry.uom.code,
                    "name": entry.uom.name,
                },
                "unit_cost": entry.unit_cost,
                "amount": entry.amount,
                "note": entry.note,
                "created_by": getattr(entry.created_by, "username", None),
                "created_at": entry.created_at,
            }
            for entry in qs[:limit]
        ]
        return Response(data)

    def post(self, request):
        payload = request.data or {}
        warehouse_id = payload.get("warehouse_id")
        item_id = payload.get("item_id")
        tx_date_raw = payload.get("tx_date")
        if not warehouse_id or not item_id:
            return Response({"detail": "warehouse_id and item_id are required."}, status=400)
        if not tx_date_raw:
            return Response({"detail": "tx_date is required."}, status=400)
        try:
            tx_date = date.fromisoformat(str(tx_date_raw))
        except ValueError:
            return Response({"detail": "tx_date must be YYYY-MM-DD."}, status=400)
        warehouse = get_object_or_404(Warehouse, id=warehouse_id)
        item = get_object_or_404(ItemMaster, id=item_id)
        location = None
        if payload.get("location_id"):
            location = get_object_or_404(Location, id=payload.get("location_id"))
        uom = None
        if payload.get("uom_id"):
            uom = get_object_or_404(UoM, id=payload.get("uom_id"))
        unit_cost = payload.get("unit_cost")
        if isinstance(unit_cost, str):
            unit_cost = unit_cost.replace(",", "").strip()
            unit_cost = int(unit_cost) if unit_cost else None
        elif unit_cost is not None:
            unit_cost = int(unit_cost)
        try:
            ledger, stock = create_ledger_entry(
                actor=request.user,
                tx_type=payload.get("tx_type"),
                tx_date=tx_date,
                warehouse=warehouse,
                location=location,
                item=item,
                qty_delta=payload.get("qty"),
                uom=uom,
                unit_cost=unit_cost,
                note=payload.get("note", ""),
            )
        except PermissionDenied as exc:
            return Response({"detail": str(exc)}, status=403)
        except ValidationError as exc:
            return Response({"detail": exc.message_dict if hasattr(exc, "message_dict") else str(exc)}, status=400)
        return Response(
            {
                "ledger_id": ledger.id,
                "stock_qty_on_hand": str(stock.qty_on_hand),
                "message": "\uC7AC\uACE0 \uC6D0\uC7A5\uC774 \uC800\uC7A5\uB418\uC5B4\uC2B5\uB2C8\uB2E4.",
            },
            status=201,
        )


class InventoryStockView(APIView):
    def get(self, request):
        role = get_user_role(request.user)
        qs = Stock.objects.select_related(
            "warehouse",
            "location",
            "item",
            "item__uom",
        ).order_by("warehouse__name", "item__code")
        if role == Role.FIELD:
            assigned_project_ids = ProjectAssignment.objects.filter(
                user=request.user, is_active=True
            ).values_list("project_id", flat=True)
            allowed_warehouse_ids = Warehouse.objects.filter(
                Q(warehouse_type=WarehouseType.HQ)
                | Q(project_id__in=assigned_project_ids, warehouse_type=WarehouseType.SITE)
            ).values_list("id", flat=True)
            qs = qs.filter(warehouse_id__in=allowed_warehouse_ids)
        warehouse_id = request.GET.get("warehouse")
        item_id = request.GET.get("item")
        q = (request.GET.get("q") or "").strip()
        include_inactive = request.GET.get("include_inactive") in ("1", "true", "True")
        if include_inactive and role not in (Role.HQ, Role.CEO):
            return Response({"detail": "Inactive items are not allowed."}, status=403)
        if not include_inactive:
            qs = qs.filter(item__is_active=True)
        if warehouse_id:
            qs = qs.filter(warehouse_id=warehouse_id)
        if item_id:
            qs = qs.filter(item_id=item_id)
        if q:
            qs = qs.filter(
                Q(item__code__icontains=q)
                | Q(item__name__icontains=q)
                | Q(item__spec__icontains=q)
                | Q(item__barcode__icontains=q)
            )
        data = [
            {
                "id": stock.id,
                "warehouse": {
                    "id": stock.warehouse_id,
                    "code": stock.warehouse.code,
                    "name": stock.warehouse.name,
                },
                "location": {
                    "id": stock.location_id,
                    "code": stock.location.code if stock.location else None,
                    "name": stock.location.name if stock.location else None,
                },
                "item": {
                    "id": stock.item_id,
                    "code": stock.item.code,
                    "name": stock.item.name,
                    "spec": stock.item.spec,
                },
                "qty_on_hand": str(stock.qty_on_hand),
                "uom": {
                    "id": stock.item.uom_id,
                    "code": stock.item.uom.code,
                    "name": stock.item.uom.name,
                },
            }
            for stock in qs
        ]
        return Response(data)


class TransferListView(APIView):
    def get(self, request):
        role = get_user_role(request.user)
        qs = Transfer.objects.select_related(
            "project",
            "from_warehouse",
            "to_warehouse",
            "created_by",
        ).order_by("-created_at")
        if role == Role.FIELD:
            assigned_project_ids = ProjectAssignment.objects.filter(
                user=request.user, is_active=True
            ).values_list("project_id", flat=True)
            qs = qs.filter(project_id__in=assigned_project_ids)
        project_id = request.GET.get("project")
        status = request.GET.get("status")
        start = request.GET.get("start")
        end = request.GET.get("end")
        q = (request.GET.get("q") or "").strip()
        if project_id:
            qs = qs.filter(project_id=project_id)
        if status:
            qs = qs.filter(status=status)
        if start:
            qs = qs.filter(tx_date__gte=start)
        if end:
            qs = qs.filter(tx_date__lte=end)
        if q:
            qs = qs.filter(
                Q(transfer_no__icontains=q)
                | Q(note__icontains=q)
                | Q(from_warehouse__code__icontains=q)
                | Q(to_warehouse__code__icontains=q)
            )
        data = [
            {
                "id": transfer.id,
                "transfer_no": transfer.transfer_no,
                "direction": transfer.direction,
                "project_id": transfer.project_id,
                "status": transfer.status,
                "tx_date": transfer.tx_date,
                "from_warehouse": {
                    "id": transfer.from_warehouse_id,
                    "code": transfer.from_warehouse.code,
                    "name": transfer.from_warehouse.name,
                },
                "to_warehouse": {
                    "id": transfer.to_warehouse_id,
                    "code": transfer.to_warehouse.code,
                    "name": transfer.to_warehouse.name,
                },
                "note": transfer.note,
                "lines_count": transfer.lines.count(),
            }
            for transfer in qs
        ]
        return Response(data)

    def post(self, request):
        require_role(request.user, [Role.HQ, Role.CEO], request=request)
        payload = request.data or {}
        direction = payload.get("direction")
        project_id = payload.get("project_id")
        from_warehouse_id = payload.get("from_warehouse_id")
        to_warehouse_id = payload.get("to_warehouse_id")
        tx_date_raw = payload.get("tx_date")
        lines = payload.get("lines") or []
        if not direction or not from_warehouse_id or not to_warehouse_id or not tx_date_raw:
            return Response({"detail": "direction, from_warehouse_id, to_warehouse_id, tx_date are required."}, status=400)
        try:
            tx_date = date.fromisoformat(str(tx_date_raw))
        except ValueError:
            return Response({"detail": "tx_date must be YYYY-MM-DD."}, status=400)
        project = None
        if project_id:
            project = get_object_or_404(Project, id=project_id)
        from_warehouse = get_object_or_404(Warehouse, id=from_warehouse_id)
        to_warehouse = get_object_or_404(Warehouse, id=to_warehouse_id)
        from_location = None
        if payload.get("from_location_id"):
            from_location = get_object_or_404(Location, id=payload.get("from_location_id"))
        to_location = None
        if payload.get("to_location_id"):
            to_location = get_object_or_404(Location, id=payload.get("to_location_id"))
        prepared_lines = []
        for line in lines:
            item_id = line.get("item_id")
            qty = line.get("qty")
            if not item_id:
                return Response({"detail": "line item_id is required."}, status=400)
            item = get_object_or_404(ItemMaster, id=item_id)
            prepared_lines.append(
                {
                    "item": item,
                    "qty": qty,
                    "note": line.get("note", ""),
                    "uom": item.uom,
                }
            )
        try:
            transfer = create_transfer(
                actor=request.user,
                direction=direction,
                project=project,
                from_warehouse=from_warehouse,
                to_warehouse=to_warehouse,
                tx_date=tx_date,
                note=payload.get("note", ""),
                lines=prepared_lines,
                from_location=from_location,
                to_location=to_location,
            )
        except PermissionDenied as exc:
            return Response({"detail": str(exc)}, status=403)
        except ValidationError as exc:
            return Response({"detail": exc.message_dict if hasattr(exc, "message_dict") else str(exc)}, status=400)
        return Response(
            {
                "id": transfer.id,
                "transfer_no": transfer.transfer_no,
                "status": transfer.status,
            },
            status=201,
        )


class TransferActionView(APIView):
    def post(self, request, transfer_id, action):
        transfer = get_object_or_404(Transfer.objects.select_related("project"), id=transfer_id)
        try:
            if action == "submit":
                transfer = submit_transfer(transfer, actor=request.user)
            elif action == "issue":
                transfer = issue_transfer(transfer, actor=request.user)
            elif action == "receive":
                transfer = receive_transfer(transfer, actor=request.user)
            elif action == "cancel":
                transfer = cancel_transfer(transfer, actor=request.user)
            else:
                return Response({"detail": "Invalid action."}, status=400)
        except PermissionDenied as exc:
            return Response({"detail": str(exc)}, status=403)
        except ValidationError as exc:
            return Response({"detail": exc.message_dict if hasattr(exc, "message_dict") else str(exc)}, status=400)
        return Response(
            {"id": transfer.id, "transfer_no": transfer.transfer_no, "status": transfer.status},
            status=200,
        )

    def patch(self, request, item_id):
        require_role(request.user, [Role.HQ, Role.CEO], request=request)
        item = get_object_or_404(ItemMaster, id=item_id)
        payload = request.data or {}
        data = {}
        if "code" in payload:
            data["code"] = payload.get("code")
        if "name" in payload:
            data["name"] = payload.get("name")
        if "spec" in payload:
            data["spec"] = payload.get("spec")
        if "description" in payload:
            data["description"] = payload.get("description")
        if "barcode" in payload:
            data["barcode"] = payload.get("barcode")
        if "is_active" in payload:
            data["is_active"] = payload.get("is_active")
        if "uom_id" in payload:
            data["uom"] = get_object_or_404(UoM, id=payload.get("uom_id"))
        if "category_id" in payload:
            category_id = payload.get("category_id")
            data["category"] = get_object_or_404(ItemCategory, id=category_id) if category_id else None
        item = update_item(item, data, actor=request.user)
        return Response(
            {
                "id": item.id,
                "code": item.code,
                "name": item.name,
                "spec": item.spec,
                "barcode": item.barcode,
                "is_active": item.is_active,
                "uom": {"id": item.uom_id, "code": item.uom.code, "name": item.uom.name},
                "category": {
                    "id": item.category_id,
                    "name": item.category.name if item.category else None,
                },
                "display_label": get_item_display(item),
            }
        )


class IssueListView(APIView):
    def get(self, request):
        role = get_user_role(request.user)
        qs = IssueToWork.objects.select_related(
            "project", "warehouse", "location", "created_by"
        ).prefetch_related("lines")
        project_id = request.GET.get("project")
        status = request.GET.get("status")
        start = request.GET.get("start")
        end = request.GET.get("end")
        if project_id:
            qs = qs.filter(project_id=project_id)
        if status:
            qs = qs.filter(status=status)
        if start:
            try:
                qs = qs.filter(issue_date__gte=date.fromisoformat(start))
            except ValueError:
                return Response({"detail": "Invalid start date."}, status=400)
        if end:
            try:
                qs = qs.filter(issue_date__lte=date.fromisoformat(end))
            except ValueError:
                return Response({"detail": "Invalid end date."}, status=400)
        if role == Role.FIELD:
            assigned_project_ids = ProjectAssignment.objects.filter(
                user=request.user, is_active=True
            ).values_list("project_id", flat=True)
            qs = qs.filter(project_id__in=assigned_project_ids)
        qs = qs.order_by("-issue_date", "-id")
        data = []
        for issue in qs:
            total_amount = sum(
                (line.amount or 0) for line in issue.lines.all()
            )
            data.append(
                {
                    "id": issue.id,
                    "issue_no": issue.issue_no,
                    "project_id": issue.project_id,
                    "warehouse_id": issue.warehouse_id,
                    "location_id": issue.location_id,
                    "issue_date": str(issue.issue_date),
                    "status": issue.status,
                    "line_count": issue.lines.count(),
                    "total_amount": total_amount,
                }
            )
        return Response(data)

    def post(self, request):
        payload = request.data or {}
        project_id = payload.get("project_id")
        issue_date_raw = payload.get("issue_date")
        note = payload.get("note", "")
        lines = payload.get("lines") or []
        warehouse_id = payload.get("warehouse_id")
        location_id = payload.get("location_id")
        if not project_id or not issue_date_raw:
            return Response({"detail": "project_id and issue_date are required."}, status=400)
        project = get_object_or_404(Project, id=project_id)
        try:
            issue_date = date.fromisoformat(str(issue_date_raw))
        except ValueError:
            return Response({"detail": "Invalid issue_date."}, status=400)
        try:
            issue = create_issue_to_work(
                actor=request.user,
                project=project,
                issue_date=issue_date,
                lines_payload=lines,
                note=note,
                warehouse_id=warehouse_id,
                location_id=location_id,
            )
        except PermissionDenied as exc:
            return Response({"detail": str(exc)}, status=403)
        except ValidationError as exc:
            return Response(
                {"detail": exc.message_dict if hasattr(exc, "message_dict") else str(exc)},
                status=400,
            )
        return Response(
            {
                "id": issue.id,
                "issue_no": issue.issue_no,
                "status": issue.status,
                "issue_date": str(issue.issue_date),
            },
            status=201,
        )


class IssueDetailView(APIView):
    def get(self, request, issue_id):
        issue = get_object_or_404(
            IssueToWork.objects.select_related("project", "warehouse", "location"),
            id=issue_id,
        )
        if get_user_role(request.user) == Role.FIELD:
            has_access = ProjectAssignment.objects.filter(
                user=request.user, project_id=issue.project_id, is_active=True
            ).exists()
            if not has_access:
                return Response({"detail": "Project access denied."}, status=403)
        lines = [
            {
                "id": line.id,
                "item_id": line.item_id,
                "item_code": line.item.code,
                "item_name": line.item.name,
                "qty": str(line.qty),
                "uom": line.uom.code,
                "cbs_id": line.cbs_id,
                "cbs_code": line.cbs.code,
                "cbs_name": line.cbs.get_display_name(),
                "unit_cost": line.unit_cost,
                "amount": line.amount,
                "memo": line.memo,
            }
            for line in issue.lines.select_related("item", "uom", "cbs")
        ]
        return Response(
            {
                "id": issue.id,
                "issue_no": issue.issue_no,
                "project_id": issue.project_id,
                "warehouse_id": issue.warehouse_id,
                "location_id": issue.location_id,
                "issue_date": str(issue.issue_date),
                "status": issue.status,
                "note": issue.note,
                "lines": lines,
            }
        )

    def patch(self, request, issue_id):
        issue = get_object_or_404(IssueToWork.objects.select_related("project"), id=issue_id)
        payload = request.data or {}
        issue_date_raw = payload.get("issue_date") or issue.issue_date
        note = payload.get("note", issue.note)
        lines = payload.get("lines") or []
        location_id = payload.get("location_id")
        try:
            issue_date = (
                issue_date_raw if isinstance(issue_date_raw, date) else date.fromisoformat(str(issue_date_raw))
            )
        except ValueError:
            return Response({"detail": "Invalid issue_date."}, status=400)
        try:
            issue = update_issue_to_work(
                issue,
                actor=request.user,
                issue_date=issue_date,
                lines_payload=lines,
                note=note,
                location_id=location_id,
            )
        except PermissionDenied as exc:
            return Response({"detail": str(exc)}, status=403)
        except ValidationError as exc:
            return Response(
                {"detail": exc.message_dict if hasattr(exc, "message_dict") else str(exc)},
                status=400,
            )
        return Response(
            {
                "id": issue.id,
                "issue_no": issue.issue_no,
                "status": issue.status,
                "issue_date": str(issue.issue_date),
            }
        )


class IssueSubmitView(APIView):
    def post(self, request, issue_id):
        issue = get_object_or_404(IssueToWork, id=issue_id)
        try:
            issue = submit_issue_to_work(issue, actor=request.user)
        except PermissionDenied as exc:
            return Response({"detail": str(exc)}, status=403)
        except ValidationError as exc:
            return Response(
                {"detail": exc.message_dict if hasattr(exc, "message_dict") else str(exc)},
                status=400,
            )
        return Response(
            {"id": issue.id, "issue_no": issue.issue_no, "status": issue.status},
            status=200,
        )
