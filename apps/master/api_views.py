import logging

from django.apps import apps
from django.core.exceptions import PermissionDenied
from django.db import transaction
from django.db.models import Q
from rest_framework.permissions import IsAuthenticated
from rest_framework.response import Response
from rest_framework.views import APIView

from apps.core.rbac.permissions import get_user_role, require_project_access
from apps.core.rbac.models import Role
from .models import FavoriteCostItem
from .cbs_policy import build_cbs_badges, evaluate_cbs_selectability

logger = logging.getLogger(__name__)


def _get_costitem_model():
    try:
        from apps.master.models import CostItem as MasterCostItem  # noqa: F401

        return MasterCostItem
    except Exception:
        pass

    for model in apps.get_models():
        if model.__name__ == "CostItem":
            return model

    raise PermissionDenied("CostItem model not found. Please create CostItem model first.")


def _resolve_field_map(model):
    fields = {
        field.name: field
        for field in model._meta.get_fields()
        if hasattr(field, "attname")
    }

    def pick(candidates, required):
        for name in candidates:
            if name in fields:
                return name
        if required:
            raise PermissionDenied(f"Required field not found for {candidates}.")
        return None

    code_field = pick(["code", "item_code", "cost_code", "cbs_code"], True)
    name_field = pick(["name", "title", "label", "display_name"], True)
    cost_type_field = pick(
        ["cost_type", "ctype", "type", "category", "cost_category"], True
    )
    work_type_field = pick(
        ["work_type", "work_code", "work_kind", "trade_code"], True
    )
    active_field = pick(["active", "is_active", "enabled"], False)

    return {
        "code": code_field,
        "name": name_field,
        "cost_type": cost_type_field,
        "work_type": work_type_field,
        "active": active_field,
    }


def _with_aliases(qs):
    try:
        return qs.prefetch_related("aliases")
    except Exception:
        return qs


def _display_name(item):
    getter = getattr(item, "get_display_name", None)
    if callable(getter):
        return getter()
    return getattr(item, "name", "")


def _alias_list(item):
    aliases = getattr(item, "aliases", None)
    if aliases is None:
        return []
    return [alias.alias for alias in aliases.all() if alias.alias]


def _alias_display(item):
    alias = _display_name(item)
    name = getattr(item, "name", "")
    code = getattr(item, "code", "")
    if alias and alias != name:
        return f"{code} - {alias} - {name}"
    return f"{code} - {name}"


def _serialize_item(item, mapping, policy_result=None):
    payload = {
        "id": item.id,
        "code": getattr(item, mapping["code"], ""),
        "name": getattr(item, mapping["name"], ""),
        "display_name": _display_name(item),
        "cost_type": getattr(item, mapping["cost_type"], ""),
        "work_type": getattr(item, mapping["work_type"], ""),
        "alias_list": _alias_list(item),
        "alias_display": _alias_display(item),
    }
    if mapping["active"]:
        payload["active"] = getattr(item, mapping["active"])
    if policy_result:
        payload["selectable"] = policy_result.selectable
        payload["severity"] = policy_result.severity
        payload["policy_message"] = policy_result.message
        payload["locked"] = policy_result.locked
        payload["pending_change"] = policy_result.pending
        payload["badges"] = build_cbs_badges(policy_result)
    return payload


class CbsSearchView(APIView):
    permission_classes = [IsAuthenticated]

    def get(self, request):
        model = _get_costitem_model()
        mapping = _resolve_field_map(model)
        role = get_user_role(request.user)

        raw_q = (request.GET.get("q") or "").strip()
        raw_limit = request.GET.get("limit") or "20"
        try:
            limit = max(1, min(int(raw_limit), 50))
        except (TypeError, ValueError):
            limit = 20

        qs = model.objects.all()
        if mapping["active"]:
            active_param = (request.GET.get("active") or "").strip().lower()
            if role == Role.FIELD:
                qs = qs.filter(**{mapping["active"]: True})
            elif active_param in ("1", "true", "active"):
                qs = qs.filter(**{mapping["active"]: True})
            elif active_param in ("0", "false", "inactive"):
                qs = qs.filter(**{mapping["active"]: False})
        else:
            if role == Role.FIELD:
                logger.info(
                    "CBS search active policy N/A: user=%s role=%s path=%s",
                    getattr(request.user, "username", None),
                    role,
                    request.path,
                )
        qs = _with_aliases(qs)

        items = []
        if raw_q:
            code_qs = qs.filter(**{f"{mapping['code']}__istartswith": raw_q}).order_by(
                mapping["code"]
            )
            code_items = list(code_qs[:limit])
            items.extend(code_items)

            remaining = limit - len(code_items)
            if remaining > 0:
                name_qs = qs.filter(
                    **{f"{mapping['name']}__icontains": raw_q}
                ).exclude(id__in=[item.id for item in code_items])
                name_items = list(name_qs.order_by(mapping["name"])[:remaining])
                items.extend(name_items)
        else:
            items = list(qs.order_by(mapping["code"])[:limit])

        data = []
        for item in items:
            policy = evaluate_cbs_selectability(
                item,
                role,
                "BUDGET",
                is_existing_usage=False,
            )
            data.append(_serialize_item(item, mapping, policy))
        if data:
            data.sort(
                key=lambda x: (
                    0 if x.get("selectable") else 1,
                    0 if x.get("active", True) else 1,
                    x.get("code", ""),
                )
            )
        return Response(data)


class CbsFavoritesView(APIView):
    permission_classes = [IsAuthenticated]

    def get(self, request):
        model = _get_costitem_model()
        mapping = _resolve_field_map(model)

        project_id = request.GET.get("project_id")
        if project_id:
            require_project_access(request.user, project_id)
        favorites = FavoriteCostItem.objects.filter(user=request.user)
        if project_id:
            favorites = favorites.filter(Q(project_id=project_id) | Q(project__isnull=True))
        favorites = favorites.select_related("cost_item").order_by("-created_at")[:20]

        cost_items = [fav.cost_item for fav in favorites if fav.cost_item_id]
        data = [_serialize_item(item, mapping) for item in cost_items]
        return Response(data)


class CbsFavoriteToggleView(APIView):
    permission_classes = [IsAuthenticated]

    def post(self, request):
        model = _get_costitem_model()
        mapping = _resolve_field_map(model)

        cost_item_id = request.data.get("cost_item_id")
        project_id = request.data.get("project_id")
        if not cost_item_id:
            return Response({"detail": "cost_item_id is required."}, status=400)
        if project_id:
            require_project_access(request.user, project_id)

        cost_item = model.objects.filter(id=cost_item_id).first()
        if cost_item is None:
            return Response({"detail": "cost_item not found."}, status=404)

        with transaction.atomic():
            existing = FavoriteCostItem.objects.filter(
                user=request.user,
                project_id=project_id,
                cost_item=cost_item,
            ).first()
            if existing:
                existing.delete()
                return Response({"favorited": False})
            FavoriteCostItem.objects.create(
                user=request.user,
                project_id=project_id,
                cost_item=cost_item,
            )
        return Response({"favorited": True})
