import logging
import re
from decimal import Decimal

from django.apps import apps
from django.core.exceptions import PermissionDenied
from django.core.paginator import Paginator
from django.db import IntegrityError, transaction
from django.db.models import Q
from django.forms import modelformset_factory
from django.shortcuts import get_object_or_404, redirect, render
from django.utils import timezone

from apps.audit.services.logger import log_action
from apps.core.rbac.models import Role
from apps.core.rbac.permissions import get_user_role, require_role
from .forms import (
    MasterBudgetTemplateItemForm,
    MasterTemplateForm,
    MasterWBSTemplateItemForm,
)
from .models import (
    CBSChangeRequest,
    CBSChangeRequestStatus,
    CBSChangeRequestType,
    MasterBudgetTemplateItem,
    MasterTemplate,
    MasterTemplateCategory,
    MasterTemplateDomain,
    MasterWBSTemplateItem,
)

logger = logging.getLogger(__name__)
_MAPPING_LOGGED = False
DEFAULT_LOCK_ON_UNKNOWN = True
COST_TYPE_CODES = ["M", "L", "E", "S", "O", "G", "P"]

COST_TYPE_LABELS = {
    "M": "???",
    "L": "???",
    "E": "??",
    "S": "??????",
    "O": "?????",
    "G": "?????",
    "P": "??/??(???)",
}
WORK_TYPE_LABELS = {
    "01": "??",
    "02": "????",
    "03": "??",
    "04": "??",
    "05": "??????",
    "06": "???",
    "07": "????",
    "08": "????",
    "09": "?????",
    "10": "??",
    "11": "??",
    "12": "?????",
    "13": "????",
    "99": "??",
}


def cbs_list_view(request):
    _require_cbs_access(request, allowed_roles=[Role.HQ])
    return _render_cbs_list(request, role_override=Role.HQ)


def ceo_cbs_list_view(request):
    _require_cbs_access(request, allowed_roles=[Role.CEO])
    return _render_cbs_list(request, role_override=Role.CEO)


def cbs_toggle_active(request, pk):
    require_role(request.user, [Role.HQ], request=request)
    model = _get_costitem_model()
    mapping = _resolve_field_map(model)
    _log_mapping_once(mapping)

    if not mapping["active"]:
        return _redirect_with_message(
            request,
            "ì´ íë¡ì í¸ì CostItemìë íì± íëê° ìì´ í ê¸ì ì¬ì©í  ì ììµëë¤.",
        )

    if request.method != "POST":
        raise PermissionDenied

    with transaction.atomic():
        item = model.objects.select_for_update().get(pk=pk)
        before = getattr(item, mapping["active"])
        after = not before
        setattr(item, mapping["active"], after)
        item.save(update_fields=[mapping["active"]])

    try:
        log_action(
            actor=request.user,
            action="MASTER_CBS_TOGGLE_ACTIVE",
            object_type="CostItem",
            object_id=item.pk,
            meta={
                "code": getattr(item, mapping["code"]),
                "before_active": before,
                "after_active": after,
            },
            request=request,
        )
    except Exception:
        logger.warning("AuditLog failed for CBS toggle.", exc_info=True)

    return _redirect_with_message(
        request,
        f"CBS 활성 상태가 변경되었습니다. ({getattr(item, mapping['code'])})",
    )


def cbs_edit_name(request, pk):
    require_role(request.user, [Role.HQ], request=request)
    model = _get_costitem_model()
    mapping = _resolve_field_map(model)
    _log_mapping_once(mapping)

    item = get_object_or_404(model, pk=pk)
    locked, reasons, stats = _is_costitem_locked(item, model)
    before_name = getattr(item, mapping["name"])

    if request.method == "POST":
        action = (request.POST.get("action") or "save").lower()
        attempt_name = (request.POST.get("name") or "").strip()
        if locked:
            _log_cbs_rename_blocked(
                request,
                item,
                mapping,
                before_name,
                attempt_name,
                reasons,
                stats,
            )
            return render(
                request,
                "app/hq/master_cbs_edit_name.html",
                _edit_name_context(
                    item,
                    mapping,
                    locked,
                    reasons,
                    stats,
                    error_message="이 CBS는 이미 제출/승인된 실적에 사용되어 이름을 변경할 수 없습니다.",
                ),
                status=403,
            )
        if not attempt_name:
            return render(
                request,
                "app/hq/master_cbs_edit_name.html",
                _edit_name_context(
                    item,
                    mapping,
                    locked,
                    reasons,
                    stats,
                    error_message="항목명을 입력해 주세요.",
                ),
                status=400,
            )
        if attempt_name == before_name:
            return _redirect_with_message(request, "변경 사항이 없습니다.")

        proposed = _build_proposed_payload(
            mapping,
            {
                mapping["code"]: getattr(item, mapping["code"]),
                mapping["name"]: attempt_name,
                mapping["cost_type"]: getattr(item, mapping["cost_type"]),
                mapping["work_type"]: getattr(item, mapping["work_type"]),
                mapping["active"]: getattr(item, mapping["active"]) if mapping["active"] else None,
            },
            model,
        )
        status = (
            CBSChangeRequestStatus.SUBMITTED
            if action == "submit"
            else CBSChangeRequestStatus.DRAFT
        )
        change_request = CBSChangeRequest.objects.create(
            cost_item=item,
            request_type=CBSChangeRequestType.UPDATE,
            requested_by=request.user,
            status=status,
            proposed=proposed,
            reason="",
        )
        _log_cbs_change_request(
            request,
            "MASTER_CBS_CHANGE_REQUEST_CREATE",
            change_request,
            status_before=None,
            status_after=status,
        )
        if status == CBSChangeRequestStatus.SUBMITTED:
            _log_cbs_change_request(
                request,
                "MASTER_CBS_CHANGE_REQUEST_SUBMIT",
                change_request,
                status_before=CBSChangeRequestStatus.DRAFT,
                status_after=status,
            )
        return _redirect_request_notice(
            request,
            "CBS 이름 변경 요청이 생성되었습니다. CEO 승인 후 반영됩니다.",
        )

    return render(
        request,
        "app/hq/master_cbs_edit_name.html",
        _edit_name_context(item, mapping, locked, reasons, stats),
    )

def cbs_create(request):
    require_role(request.user, [Role.HQ], request=request)
    model = _get_costitem_model()
    mapping = _resolve_field_map(model)
    _log_mapping_once(mapping)

    if request.method == "POST":
        action = (request.POST.get("action") or "save").lower()
        form_data = _extract_cbs_form_data(request, model, mapping, is_create=True)
        if form_data["errors"]:
            return render(
                request,
                "app/hq/master_cbs_form.html",
                _build_cbs_form_context(mapping, form_data, is_create=True),
                status=400,
            )

        proposed = _build_proposed_payload(mapping, form_data["values"], model)
        status = (
            CBSChangeRequestStatus.SUBMITTED
            if action == "submit"
            else CBSChangeRequestStatus.DRAFT
        )
        change_request = CBSChangeRequest.objects.create(
            cost_item=None,
            request_type=CBSChangeRequestType.CREATE,
            requested_by=request.user,
            status=status,
            proposed=proposed,
            reason=(request.POST.get("reason") or "").strip(),
        )
        _log_cbs_change_request(
            request,
            "MASTER_CBS_CHANGE_REQUEST_CREATE",
            change_request,
            status_before=None,
            status_after=status,
        )
        if status == CBSChangeRequestStatus.SUBMITTED:
            _log_cbs_change_request(
                request,
                "MASTER_CBS_CHANGE_REQUEST_SUBMIT",
                change_request,
                status_before=CBSChangeRequestStatus.DRAFT,
                status_after=status,
            )

        return _redirect_request_notice(
            request,
            "CBS 생성 요청이 생성되었습니다. CEO 승인 후 반영됩니다.",
        )

    form_data = _default_cbs_form_data(mapping)
    return render(
        request,
        "app/hq/master_cbs_form.html",
        _build_cbs_form_context(mapping, form_data, is_create=True),
    )

def cbs_edit(request, pk):
    require_role(request.user, [Role.HQ], request=request)
    model = _get_costitem_model()
    mapping = _resolve_field_map(model)
    _log_mapping_once(mapping)

    item = get_object_or_404(model, pk=pk)
    locked, reasons, stats = _is_costitem_locked(item, model)
    alias_available = _alias_available()

    if request.method == "POST":
        action = (request.POST.get("action") or "save").lower()
        form_data = _extract_cbs_form_data(request, model, mapping, is_create=False)
        if locked:
            _log_cbs_update_blocked(request, item, mapping, form_data, reasons, stats)
            form_data["errors"].append("잠긴 CBS는 별칭으로만 변경할 수 있습니다.")
            return render(
                request,
                "app/hq/master_cbs_form.html",
                _build_cbs_form_context(
                    mapping,
                    form_data,
                    is_create=False,
                    item=item,
                    locked=locked,
                    reasons=reasons,
                    stats=stats,
                    alias_available=alias_available,
                ),
                status=403,
            )

        if form_data["errors"]:
            return render(
                request,
                "app/hq/master_cbs_form.html",
                _build_cbs_form_context(
                    mapping,
                    form_data,
                    is_create=False,
                    item=item,
                    locked=locked,
                    reasons=reasons,
                    stats=stats,
                    alias_available=alias_available,
                ),
                status=400,
            )

        if not form_data["changed"]:
            return _redirect_request_notice(request, "변경 사항이 없습니다.")

        proposed = _build_proposed_payload(mapping, form_data["values"], model)
        status = (
            CBSChangeRequestStatus.SUBMITTED
            if action == "submit"
            else CBSChangeRequestStatus.DRAFT
        )
        change_request = CBSChangeRequest.objects.create(
            cost_item=item,
            request_type=CBSChangeRequestType.UPDATE,
            requested_by=request.user,
            status=status,
            proposed=proposed,
            reason=(request.POST.get("reason") or "").strip(),
        )
        _log_cbs_change_request(
            request,
            "MASTER_CBS_CHANGE_REQUEST_CREATE",
            change_request,
            status_before=None,
            status_after=status,
        )
        if status == CBSChangeRequestStatus.SUBMITTED:
            _log_cbs_change_request(
                request,
                "MASTER_CBS_CHANGE_REQUEST_SUBMIT",
                change_request,
                status_before=CBSChangeRequestStatus.DRAFT,
                status_after=status,
            )

        return _redirect_request_notice(
            request,
            "CBS 변경 요청이 생성되었습니다. CEO 승인 후 반영됩니다.",
        )

    form_data = _default_cbs_form_data(mapping, item)
    return render(
        request,
        "app/hq/master_cbs_form.html",
        _build_cbs_form_context(
            mapping,
            form_data,
            is_create=False,
            item=item,
            locked=locked,
            reasons=reasons,
            stats=stats,
            alias_available=alias_available,
        ),
    )

def cbs_aliases_view(request, pk):
    require_role(request.user, [Role.HQ], request=request)
    model = _get_costitem_model()
    alias_model = _get_costitem_alias_model()
    mapping = _resolve_field_map(model)
    _log_mapping_once(mapping)

    item = model.objects.get(pk=pk)
    locked, reasons, stats = _is_costitem_locked(item, model)
    notice = request.session.pop("cbs_alias_notice", None)

    if request.GET.get("from") == "rename_locked":
        try:
            log_action(
                actor=request.user,
                action="MASTER_CBS_RENAME_REDIRECT_TO_ALIAS",
                object_type="CostItem",
                object_id=item.pk,
                meta={"code": getattr(item, mapping["code"])},
                request=request,
            )
        except Exception:
            logger.warning("AuditLog failed for CBS rename redirect.", exc_info=True)

    aliases = (
        alias_model.objects.filter(cost_item=item)
        .select_related("created_by")
        .order_by("-is_primary", "-updated_at")
    )

    context = {
        "item": item,
        "aliases": aliases,
        "mapping": mapping,
        "notice": notice,
        "locked": locked,
        "reasons": reasons,
        "stats": stats,
        "cost_type_labels": COST_TYPE_LABELS,
        "work_type_labels": WORK_TYPE_LABELS,
    }
    return render(request, "app/hq/master_cbs_aliases.html", context)


def cbs_alias_add(request, pk):
    require_role(request.user, [Role.HQ], request=request)
    if request.method != "POST":
        raise PermissionDenied

    model = _get_costitem_model()
    alias_model = _get_costitem_alias_model()
    mapping = _resolve_field_map(model)
    _log_mapping_once(mapping)

    item = model.objects.get(pk=pk)
    alias_text = (request.POST.get("alias") or "").strip()
    note = (request.POST.get("note") or "").strip()
    is_primary = bool(request.POST.get("is_primary"))

    if not alias_text:
        return _redirect_alias_notice(
            request, item.pk, "별칭을 입력해 주세요.", level="error"
        )

    try:
        with transaction.atomic():
            if is_primary:
                alias_model.objects.filter(cost_item=item, is_primary=True).update(
                    is_primary=False
                )
            alias_obj = alias_model.objects.create(
                cost_item=item,
                alias=alias_text,
                is_primary=is_primary,
                note=note,
                created_by=request.user,
            )
    except IntegrityError:
        return _redirect_alias_notice(
            request, item.pk, "이미 등록된 별칭입니다.", level="error"
        )

    try:
        log_action(
            actor=request.user,
            action="MASTER_CBS_ALIAS_ADD",
            object_type="CostItem",
            object_id=item.pk,
            meta={
                "code": getattr(item, mapping["code"]),
                "alias": alias_obj.alias,
                "is_primary": alias_obj.is_primary,
                "note": alias_obj.note,
            },
            request=request,
        )
    except Exception:
        logger.exception("AuditLog failed: MASTER_CBS_ALIAS_ADD")

    return _redirect_alias_notice(
        request, item.pk, "별칭이 추가되었습니다.", level="success"
    )
def cbs_alias_set_primary(request, pk, alias_id):
    require_role(request.user, [Role.HQ], request=request)
    if request.method != "POST":
        raise PermissionDenied

    model = _get_costitem_model()
    alias_model = _get_costitem_alias_model()
    mapping = _resolve_field_map(model)
    _log_mapping_once(mapping)

    item = model.objects.get(pk=pk)
    alias_obj = alias_model.objects.get(pk=alias_id, cost_item=item)

    before_primary = (
        alias_model.objects.filter(cost_item=item, is_primary=True)
        .values_list("alias", flat=True)
        .first()
    )

    with transaction.atomic():
        alias_model.objects.filter(cost_item=item, is_primary=True).update(
            is_primary=False
        )
        alias_obj.is_primary = True
        alias_obj.save(update_fields=["is_primary"])

    try:
        log_action(
            actor=request.user,
            action="MASTER_CBS_ALIAS_SET_PRIMARY",
            object_type="CostItem",
            object_id=item.pk,
            meta={
                "code": getattr(item, mapping["code"]),
                "before_primary": before_primary,
                "after_primary": alias_obj.alias,
            },
            request=request,
        )
    except Exception:
        logger.warning("AuditLog failed for CBS alias set primary.", exc_info=True)

    return _redirect_alias_notice(request, item.pk, "ëí ë³ì¹­ì´ ë³ê²½ëììµëë¤.")


def cbs_alias_delete(request, pk, alias_id):
    require_role(request.user, [Role.HQ], request=request)
    if request.method != "POST":
        raise PermissionDenied

    model = _get_costitem_model()
    alias_model = _get_costitem_alias_model()
    mapping = _resolve_field_map(model)
    _log_mapping_once(mapping)

    item = model.objects.get(pk=pk)
    alias_obj = alias_model.objects.get(pk=alias_id, cost_item=item)

    if alias_obj.is_primary:
        return _redirect_alias_notice(
            request,
            item.pk,
            "ëí ë³ì¹­ì ì­ì í  ì ììµëë¤. ë¨¼ì  ë¤ë¥¸ ë³ì¹­ì ëíë¡ ì§ì íì¸ì.",
            level="error",
        )

    alias_value = alias_obj.alias
    alias_obj.delete()

    try:
        log_action(
            actor=request.user,
            action="MASTER_CBS_ALIAS_DELETE",
            object_type="CostItem",
            object_id=item.pk,
            meta={
                "code": getattr(item, mapping["code"]),
                "alias": alias_value,
            },
            request=request,
        )
    except Exception:
        logger.warning("AuditLog failed for CBS alias delete.", exc_info=True)

    return _redirect_alias_notice(request, item.pk, "ë³ì¹­ì´ ì­ì ëììµëë¤.")


def _render_cbs_list(request, role_override=None):
    model = _get_costitem_model()
    mapping = _resolve_field_map(model)
    _log_mapping_once(mapping)

    notice = request.session.pop("cbs_notice", None)

    q = (request.GET.get("q") or "").strip()
    cost_type = (request.GET.get("cost_type") or "").strip().upper()
    work_type = (request.GET.get("work_type") or "").strip()
    active_filter = (request.GET.get("active") or "").strip()
    page_size = _safe_int(request.GET.get("page_size"), default=50)
    page_size = max(10, min(page_size, 200))

    qs = model.objects.all()
    if q:
        qs = qs.filter(
            Q(**{f"{mapping['code']}__icontains": q})
            | Q(**{f"{mapping['name']}__icontains": q})
        )
    if cost_type:
        qs = qs.filter(**{mapping["cost_type"]: cost_type})
    if work_type:
        work_field = model._meta.get_field(mapping["work_type"])
        if work_field.get_internal_type() in ("IntegerField", "PositiveIntegerField"):
            work_value = _safe_int(work_type, default=None)
            if work_value is not None:
                qs = qs.filter(**{mapping["work_type"]: work_value})
        else:
            qs = qs.filter(**{mapping["work_type"]: work_type})
    if mapping["active"] and active_filter:
        if active_filter == "active":
            qs = qs.filter(**{mapping["active"]: True})
        elif active_filter == "inactive":
            qs = qs.filter(**{mapping["active"]: False})

    qs = qs.order_by(mapping["cost_type"], mapping["work_type"], mapping["code"])

    paginator = Paginator(qs, page_size)
    page_obj = paginator.get_page(request.GET.get("page"))

    work_type_options = [f"{i:02d}" for i in range(1, 21)] + ["99"]
    context = {
        "mapping": mapping,
        "page_obj": page_obj,
        "q": q,
        "cost_type": cost_type,
        "work_type": work_type,
        "active_filter": active_filter,
        "page_size": page_size,
        "cost_type_options": [
            {"code": code, "label": COST_TYPE_LABELS.get(code, "")}
            for code in ["M", "L", "E", "S", "O", "G", "P"]
        ],
        "work_type_options": [
            {"code": code, "label": WORK_TYPE_LABELS.get(code, "")}
            for code in work_type_options
        ],
        "cost_type_labels": COST_TYPE_LABELS,
        "work_type_labels": WORK_TYPE_LABELS,
        "role": role_override or get_user_role(request.user),
        "active_supported": bool(mapping["active"]),
        "active_notice": (
            ""
            if mapping["active"]
            else "ì´ íë¡ì í¸ì CostItemìë íì± íëê° ìì´ í ê¸ì ì¬ì©í  ì ììµëë¤."
        ),
        "notice": notice,
    }
    return render(request, "app/hq/master_cbs_list.html", context)


def hq_cbs_requests_list(request):
    _require_cbs_access(request, allowed_roles=[Role.HQ])
    status_filter = (request.GET.get("status") or "").strip().upper()
    qs = CBSChangeRequest.objects.filter(requested_by=request.user)
    if status_filter:
        qs = qs.filter(status=status_filter)
    qs = qs.select_related("requested_by", "cost_item").order_by("-created_at")
    notice = request.session.pop("cbs_request_notice", None)
    context = {
        "requests": qs,
        "status_filter": status_filter,
        "notice": notice,
    }
    return render(request, "app/hq/master_cbs_requests_list.html", context)


def hq_cbs_request_detail(request, pk):
    _require_cbs_access(request, allowed_roles=[Role.HQ])
    change_request = get_object_or_404(
        CBSChangeRequest.objects.select_related("cost_item", "requested_by"),
        pk=pk,
        requested_by=request.user,
    )
    context = {
        "request_obj": change_request,
        "can_submit": change_request.status == CBSChangeRequestStatus.DRAFT,
    }
    return render(request, "app/hq/master_cbs_request_detail.html", context)


def hq_cbs_request_submit(request, pk):
    _require_cbs_access(request, allowed_roles=[Role.HQ])
    if request.method != "POST":
        raise PermissionDenied

    change_request = get_object_or_404(
        CBSChangeRequest.objects.select_related("requested_by"),
        pk=pk,
        requested_by=request.user,
    )
    if change_request.status != CBSChangeRequestStatus.DRAFT:
        return _redirect_request_notice(request, "제출 가능한 요청이 아닙니다.")

    change_request.status = CBSChangeRequestStatus.SUBMITTED
    change_request.save(update_fields=["status", "updated_at"])
    _log_cbs_change_request(
        request,
        "MASTER_CBS_CHANGE_REQUEST_SUBMIT",
        change_request,
        status_before=CBSChangeRequestStatus.DRAFT,
        status_after=CBSChangeRequestStatus.SUBMITTED,
    )
    return _redirect_request_notice(request, "CBS 변경 요청을 제출했습니다.")
def ceo_cbs_requests_list(request):
    _require_cbs_access(request, allowed_roles=[Role.CEO])
    status_filter = (request.GET.get("status") or "").strip().upper()
    qs = CBSChangeRequest.objects.all()
    if status_filter:
        qs = qs.filter(status=status_filter)
    else:
        qs = qs.filter(status=CBSChangeRequestStatus.SUBMITTED)
    qs = qs.select_related("requested_by", "cost_item").order_by("-created_at")
    context = {
        "requests": qs,
        "status_filter": status_filter,
        "notice": request.GET.get("notice"),
    }
    return render(request, "app/ceo/master_cbs_requests_list.html", context)
def ceo_cbs_request_detail(request, pk):
    _require_cbs_access(request, allowed_roles=[Role.CEO])
    change_request = get_object_or_404(
        CBSChangeRequest.objects.select_related("cost_item", "requested_by"),
        pk=pk,
    )
    context = {
        "request_obj": change_request,
        "can_decide": change_request.status == CBSChangeRequestStatus.SUBMITTED,
    }
    return render(request, "app/ceo/master_cbs_request_detail.html", context)


def ceo_cbs_request_approve(request, pk):
    _require_cbs_access(request, allowed_roles=[Role.CEO])
    if request.method != "POST":
        raise PermissionDenied

    model = _get_costitem_model()
    mapping = _resolve_field_map(model)
    _log_mapping_once(mapping)

    with transaction.atomic():
        change_request = CBSChangeRequest.objects.select_for_update().get(pk=pk)
        if change_request.status != CBSChangeRequestStatus.SUBMITTED:
            return _redirect_ceo_request_notice("승인 가능한 요청이 아닙니다.")

        locked = False
        if change_request.cost_item_id:
            locked, _, _ = _is_costitem_locked(change_request.cost_item, model)
        if locked:
            return _redirect_ceo_request_notice("잠긴 CBS는 변경 요청을 승인할 수 없습니다.")

        if change_request.request_type == CBSChangeRequestType.CREATE:
            _apply_create_request(change_request, model, mapping)
        elif change_request.request_type == CBSChangeRequestType.UPDATE:
            _apply_update_request(change_request, model, mapping)
        elif change_request.request_type == CBSChangeRequestType.DEACTIVATE:
            _apply_deactivate_request(change_request, model, mapping)

        change_request.status = CBSChangeRequestStatus.APPROVED
        change_request.approved_by = request.user
        change_request.approved_at = timezone.now()
        change_request.save(update_fields=["status", "approved_by", "approved_at", "updated_at"])

    _log_cbs_change_request(
        request,
        "MASTER_CBS_CHANGE_REQUEST_APPROVE",
        change_request,
        status_before=CBSChangeRequestStatus.SUBMITTED,
        status_after=CBSChangeRequestStatus.APPROVED,
    )
    return _redirect_ceo_request_notice("CBS 변경 요청을 승인했습니다.")
def ceo_cbs_request_reject(request, pk):
    _require_cbs_access(request, allowed_roles=[Role.CEO])
    if request.method != "POST":
        raise PermissionDenied

    decision_note = (request.POST.get("decision_note") or "").strip()
    if not decision_note:
        return _redirect_ceo_request_notice("반려 사유를 입력해 주세요.")

    change_request = get_object_or_404(CBSChangeRequest, pk=pk)
    if change_request.status != CBSChangeRequestStatus.SUBMITTED:
        return _redirect_ceo_request_notice("반려 가능한 요청이 아닙니다.")

    change_request.status = CBSChangeRequestStatus.REJECTED
    change_request.decision_note = decision_note
    change_request.approved_by = request.user
    change_request.approved_at = timezone.now()
    change_request.save(update_fields=["status", "decision_note", "approved_by", "approved_at", "updated_at"])

    _log_cbs_change_request(
        request,
        "MASTER_CBS_CHANGE_REQUEST_REJECT",
        change_request,
        status_before=CBSChangeRequestStatus.SUBMITTED,
        status_after=CBSChangeRequestStatus.REJECTED,
    )
    return _redirect_ceo_request_notice("CBS 변경 요청을 반려했습니다.")
def _redirect_ceo_request_notice(message):
    return redirect(f"/app/ceo/cbs/requests/?notice={message}")


def _apply_create_request(change_request, model, mapping):
    proposed = _validate_proposed(change_request, model, mapping, require_code=True)
    model.objects.create(**proposed)


def _apply_update_request(change_request, model, mapping):
    if not change_request.cost_item_id:
        raise PermissionDenied("UPDATE request requires cost_item.")
    proposed = _validate_proposed(change_request, model, mapping, require_code=False)
    item = model.objects.select_for_update().get(pk=change_request.cost_item_id)
    for field_name, value in proposed.items():
        if field_name == mapping["code"]:
            continue
        setattr(item, field_name, value)
    update_fields = [field for field in proposed.keys() if field != mapping["code"]]
    if update_fields:
        item.save(update_fields=update_fields)


def _apply_deactivate_request(change_request, model, mapping):
    if not mapping["active"]:
        raise PermissionDenied("Active field not available.")
    if not change_request.cost_item_id:
        raise PermissionDenied("DEACTIVATE request requires cost_item.")
    item = model.objects.select_for_update().get(pk=change_request.cost_item_id)
    setattr(item, mapping["active"], False)
    item.save(update_fields=[mapping["active"]])


def _validate_proposed(change_request, model, mapping, *, require_code):
    proposed = change_request.proposed or {}
    code = (proposed.get("code") or "").strip().upper()
    name = (proposed.get("name") or "").strip()
    cost_type = (proposed.get("cost_type") or "").strip().upper()
    work_type = (proposed.get("work_type") or "").strip()
    active = proposed.get("active")

    errors = []
    if require_code and not code:
        errors.append("  .")
    if require_code and code:
        if model.objects.filter(**{mapping["code"]: code}).exists():
            errors.append("코드를 입력해 주세요.")
        if not re.match(r"^CB-[MLESGOP]-\d{2}-\d{3}$", code.replace(" ", "")):
            errors.append("코드 형식이 올바르지 않습니다.")

    if not name:
        errors.append("항목명을 입력해 주세요.")
    if cost_type not in COST_TYPE_CODES:
        errors.append("  .")
    if not re.match(r"^\d{2}$", work_type):
        errors.append("공종은 2자리 숫자(01~99)로 입력해 주세요.")

    if errors:
        raise PermissionDenied(", ".join(errors))

    work_value = _normalize_work_type(model, mapping["work_type"], work_type, [])
    payload = {
        mapping["name"]: name,
        mapping["cost_type"]: cost_type,
        mapping["work_type"]: work_value,
    }
    if require_code:
        payload[mapping["code"]] = code
    if mapping["active"] and active is not None:
        payload[mapping["active"]] = bool(active)
    return payload


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


def _get_costitem_alias_model():
    try:
        return apps.get_model("cost", "CostItemAlias")
    except Exception as exc:
        raise PermissionDenied("CostItemAlias model not found.") from exc


def _resolve_field_map(model):
    fields = {
        field.name: field
        for field in model._meta.get_fields()
        if hasattr(field, "attname")
    }

    code_field = _pick_field(fields, ["code", "item_code", "cost_code", "cbs_code"], True)
    if not getattr(fields[code_field], "unique", False):
        raise PermissionDenied("code field must be unique")

    name_field = _pick_field(fields, ["name", "title", "label", "display_name"], True)
    cost_type_field = _pick_field(
        fields, ["cost_type", "ctype", "type", "category", "cost_category"], True
    )
    work_type_field = _pick_field(
        fields, ["work_type", "work_code", "work_kind", "trade_code"], True
    )
    active_field = _pick_field(fields, ["active", "is_active", "enabled"], False)

    return {
        "code": code_field,
        "name": name_field,
        "cost_type": cost_type_field,
        "work_type": work_type_field,
        "active": active_field,
    }


def _pick_field(fields, candidates, required):
    for name in candidates:
        if name in fields:
            return name
    if required:
        field_list = ", ".join(sorted(fields.keys()))
        raise PermissionDenied(
            f"Required field not found for candidates {candidates}. "
            f"Model fields: {field_list}"
        )
    return None


def _safe_int(value, default=None):
    try:
        return int(value)
    except (TypeError, ValueError):
        return default


def _require_cbs_access(request, allowed_roles):
    role = get_user_role(request.user)
    if role in allowed_roles:
        return
    logger.warning(
        "CBS access denied: user=%s role=%s path=%s allowed_roles=%s",
        getattr(request.user, "username", None),
        role,
        request.path,
        allowed_roles,
    )
    raise PermissionDenied


def _redirect_with_message(request, message):
    request.session["cbs_notice"] = {"message": message, "time": timezone.now().isoformat()}
    return redirect("/app/hq/master/cbs/")


def _redirect_request_notice(request, message):
    request.session["cbs_request_notice"] = {"message": message, "time": timezone.now().isoformat()}
    return redirect("/app/hq/master/cbs/requests/")


def _redirect_alias_notice(request, pk, message, level="info"):
    request.session["cbs_alias_notice"] = {
        "message": message,
        "level": level,
        "time": timezone.now().isoformat(),
    }
    return redirect(f"/app/hq/master/cbs/{pk}/aliases/")


def _log_mapping_once(mapping):
    global _MAPPING_LOGGED
    if _MAPPING_LOGGED:
        return
    logger.debug(
        "CBS field mapping: code=%s, name=%s, cost_type=%s, work_type=%s, active=%s",
        mapping["code"],
        mapping["name"],
        mapping["cost_type"],
        mapping["work_type"],
        mapping["active"],
    )
    _MAPPING_LOGGED = True


def _edit_name_context(item, mapping, locked, reasons, stats, error_message=""):
    return {
        "item": item,
        "mapping": mapping,
        "locked": locked,
        "reasons": reasons,
        "stats": stats,
        "error_message": error_message,
        "cost_type_labels": COST_TYPE_LABELS,
        "work_type_labels": WORK_TYPE_LABELS,
    }


def _default_cbs_form_data(mapping, item=None):
    def get_value(field_key):
        if not item:
            return ""
        return getattr(item, mapping[field_key]) if mapping[field_key] else ""

    values = {
        mapping["code"]: get_value("code"),
        mapping["name"]: get_value("name"),
        mapping["cost_type"]: get_value("cost_type"),
        mapping["work_type"]: get_value("work_type"),
    }
    if mapping["active"]:
        values[mapping["active"]] = get_value("active")

    return {
        "values": values,
        "errors": [],
        "changed": False,
    }


def _build_cbs_form_context(
    mapping,
    form_data,
    *,
    is_create,
    item=None,
    locked=False,
    reasons=None,
    stats=None,
    alias_available=False,
):
    reasons = reasons or []
    stats = stats or {}
    return {
        "mapping": mapping,
        "item": item,
        "values": form_data["values"],
        "errors": form_data["errors"],
        "is_create": is_create,
        "locked": locked,
        "reasons": reasons,
        "stats": stats,
        "alias_available": alias_available,
        "cost_type_labels": COST_TYPE_LABELS,
        "work_type_labels": WORK_TYPE_LABELS,
        "cost_type_options": [
            {"code": code, "label": COST_TYPE_LABELS.get(code, "")}
            for code in COST_TYPE_CODES
        ],
        "work_type_options": [
            {"code": code, "label": WORK_TYPE_LABELS.get(code, "")}
            for code in ["01", "02", "03", "04", "05", "06", "07", "08", "09", "10", "11", "12", "13", "99"]
        ],
        "active_supported": bool(mapping["active"]),
    }


def _extract_cbs_form_data(request, model, mapping, *, is_create):
    errors = []
    values = {}
    changed = False

    code = (request.POST.get("code") or "").strip().upper()
    name = (request.POST.get("name") or "").strip()
    cost_type = (request.POST.get("cost_type") or "").strip().upper()
    work_type = (request.POST.get("work_type") or "").strip()

    if is_create:
        if not code:
            errors.append("코드를 입력하세요.")
        elif not re.match(r"^CB-[MLESGOP]-\d{2}-\d{3}$", code.replace(" ", "")):
            errors.append("코드 형식이 올바르지 않습니다. (예: CB-M-07-001)")
    values[mapping["code"]] = code

    if not name:
        errors.append("항목명을 입력하세요.")
    values[mapping["name"]] = name

    if cost_type not in COST_TYPE_CODES:
        errors.append("비목을 선택하세요.")
    values[mapping["cost_type"]] = cost_type

    work_type = _normalize_work_type(model, mapping["work_type"], work_type, errors)
    if work_type is not None:
        values[mapping["work_type"]] = work_type

    if mapping["active"]:
        active_raw = request.POST.get("active")
        values[mapping["active"]] = bool(active_raw)

    return errors, values, changed
def _normalize_work_type(model, field_name, raw_value, errors):
    value = raw_value.strip()
    if not re.match(r"^\d{2}$", value):
        errors.append("공종은 2자리 숫자(01~99)로 입력하세요.")
        return None
    field = model._meta.get_field(field_name)
    if field.get_internal_type() in ("IntegerField", "PositiveIntegerField"):
        return int(value)
    return value

def _snapshot_cbs_fields(item, mapping):
    return {
        "code": getattr(item, mapping["code"]),
        "name": getattr(item, mapping["name"]),
        "cost_type": getattr(item, mapping["cost_type"]),
        "work_type": getattr(item, mapping["work_type"]),
        "active": getattr(item, mapping["active"]) if mapping["active"] else None,
    }


def _alias_available():
    try:
        _get_costitem_alias_model()
        return True
    except Exception:
        return False


def _log_cbs_update_blocked(request, item, mapping, form_data, reasons, stats):
    try:
        log_action(
            actor=request.user,
            action="MASTER_CBS_UPDATE_BLOCKED",
            object_type="CostItem",
            object_id=item.pk,
            meta={
                "code": getattr(item, mapping["code"]),
                "attempted": form_data["values"],
                "reasons": reasons,
                "lock_stats": stats,
            },
            request=request,
        )
    except Exception:
        logger.warning("AuditLog failed for CBS update blocked.", exc_info=True)


def _log_cbs_rename_blocked(request, item, mapping, before_name, attempt_name, reasons, stats):
    try:
        log_action(
            actor=request.user,
            action="MASTER_CBS_RENAME_BLOCKED",
            object_type="CostItem",
            object_id=item.pk,
            meta={
                "code": getattr(item, mapping["code"]),
                "before_name": before_name,
                "attempt_name": attempt_name,
                "reasons": reasons,
                "lock_stats": stats,
            },
            request=request,
        )
    except Exception:
        logger.warning("AuditLog failed for CBS rename blocked.", exc_info=True)


def _is_costitem_locked(cost_item, cost_item_model):
    draft_count = 0
    submitted_count = 0
    approved_count = 0
    unknown_count = 0
    reasons = []

    usage_sources = _find_costitem_usages(cost_item_model)
    for model, field_name in usage_sources:
        qs = model.objects.filter(**{field_name: cost_item})
        if not qs.exists():
            continue
        status_field = _find_status_field(model)
        if status_field is None:
            count = qs.count()
            unknown_count += count
            if DEFAULT_LOCK_ON_UNKNOWN:
                reasons.append(f"{model.__name__}(status ë¯¸íì¸) {count}ê±´")
            continue
        model_draft = 0
        model_submitted = 0
        model_approved = 0
        model_unknown = 0
        for status_value in qs.values_list(status_field, flat=True):
            status = str(status_value).lower()
            if status in ("draft", "temp", "saved", "rejected"):
                model_draft += 1
            elif status == "submitted":
                model_submitted += 1
            elif status in ("approved", "final", "locked", "closed"):
                model_approved += 1
            else:
                model_unknown += 1

        draft_count += model_draft
        submitted_count += model_submitted
        approved_count += model_approved
        unknown_count += model_unknown

        if model_submitted:
            reasons.append(f"{model.__name__}(SUBMITTED) {model_submitted}ê±´")
        if model_approved:
            reasons.append(f"{model.__name__}(APPROVED) {model_approved}ê±´")
        if model_unknown and DEFAULT_LOCK_ON_UNKNOWN:
            reasons.append(f"{model.__name__}(ë¯¸íì¸) {model_unknown}ê±´")

    locked = submitted_count > 0 or approved_count > 0
    if DEFAULT_LOCK_ON_UNKNOWN and unknown_count > 0:
        locked = True

    stats = {
        "draft": draft_count,
        "submitted": submitted_count,
        "approved": approved_count,
        "unknown": unknown_count,
    }
    return locked, reasons, stats


def _find_costitem_usages(cost_item_model):
    sources = []
    for model in apps.get_models():
        for field in model._meta.fields:
            if getattr(field, "remote_field", None) and field.remote_field.model == cost_item_model:
                sources.append((model, field.name))
    return sources


def _find_status_field(model):
    candidates = ["status", "state", "approval_status", "workflow_status"]
    for name in candidates:
        if name in [field.name for field in model._meta.fields]:
            return name
    return None


def master_template_list_view(request):
    require_role(request.user, [Role.HQ], request=request)
    qs = MasterTemplate.objects.all().order_by("domain", "category", "-version")
    category = (request.GET.get("category") or "").upper()
    domain = (request.GET.get("domain") or "").upper()
    is_active = request.GET.get("active")
    if category in dict(MasterTemplateCategory.choices):
        qs = qs.filter(category=category)
    if domain in dict(MasterTemplateDomain.choices):
        qs = qs.filter(domain=domain)
    if is_active in {"0", "1"}:
        qs = qs.filter(is_active=is_active == "1")
    paginator = Paginator(qs, 20)
    page = paginator.get_page(request.GET.get("page", 1))
    return render(
        request,
        "app/hq/master_templates_list.html",
        {
            "page": page,
            "category": category,
            "domain": domain,
            "active": is_active,
            "categories": MasterTemplateCategory.choices,
            "domains": MasterTemplateDomain.choices,
        },
    )


def master_template_new_view(request):
    require_role(request.user, [Role.HQ], request=request)
    WBSFormSet = modelformset_factory(
        MasterWBSTemplateItem, form=MasterWBSTemplateItemForm, extra=8, can_delete=True
    )
    BudgetFormSet = modelformset_factory(
        MasterBudgetTemplateItem,
        form=MasterBudgetTemplateItemForm,
        extra=8,
        can_delete=True,
    )
    if request.method == "POST":
        template_form = MasterTemplateForm(request.POST)
        wbs_formset = WBSFormSet(
            request.POST, queryset=MasterWBSTemplateItem.objects.none(), prefix="wbs"
        )
        budget_formset = BudgetFormSet(
            request.POST, queryset=MasterBudgetTemplateItem.objects.none(), prefix="budget"
        )
        category = template_form.cleaned_data.get("category") if template_form.is_valid() else None
        if template_form.is_valid() and _template_items_valid(category, wbs_formset, budget_formset):
            with transaction.atomic():
                template = template_form.save(commit=False)
                template.created_by = request.user
                template.save()
                if category == MasterTemplateCategory.WBS:
                    _save_wbs_template_items(template, wbs_formset)
                if category == MasterTemplateCategory.BUDGET:
                    _save_budget_template_items(template, budget_formset)
            _log_template_action(request, "TEMPLATE_CREATE", template)
            messages.success(request, "마스터 템플릿이 생성되었습니다.")
            return redirect(f"/app/hq/master/templates/{template.id}/edit/")
    else:
        template_form = MasterTemplateForm(initial={"is_active": True})
        wbs_formset = WBSFormSet(queryset=MasterWBSTemplateItem.objects.none(), prefix="wbs")
        budget_formset = BudgetFormSet(queryset=MasterBudgetTemplateItem.objects.none(), prefix="budget")
    return render(
        request,
        "app/hq/master_template_form.html",
        {
            "template_form": template_form,
            "wbs_formset": wbs_formset,
            "budget_formset": budget_formset,
            "mode": "new",
        },
    )


def master_template_edit_view(request, pk):
    require_role(request.user, [Role.HQ], request=request)
    template = get_object_or_404(MasterTemplate, pk=pk)
    WBSFormSet = modelformset_factory(
        MasterWBSTemplateItem, form=MasterWBSTemplateItemForm, extra=3, can_delete=True
    )
    BudgetFormSet = modelformset_factory(
        MasterBudgetTemplateItem,
        form=MasterBudgetTemplateItemForm,
        extra=3,
        can_delete=True,
    )
    if request.method == "POST":
        template_form = MasterTemplateForm(request.POST, instance=template)
        wbs_formset = WBSFormSet(request.POST, queryset=template.wbs_items.all(), prefix="wbs")
        budget_formset = BudgetFormSet(
            request.POST, queryset=template.budget_items.all(), prefix="budget"
        )
        if template_form.is_valid() and _template_items_valid(template.category, wbs_formset, budget_formset):
            with transaction.atomic():
                template_form.save()
                if template.category == MasterTemplateCategory.WBS:
                    _save_wbs_template_items(template, wbs_formset)
                if template.category == MasterTemplateCategory.BUDGET:
                    _save_budget_template_items(template, budget_formset)
            _log_template_action(request, "TEMPLATE_UPDATE", template)
            messages.success(request, "템플릿이 저장되었습니다.")
            return redirect(f"/app/hq/master/templates/{template.id}/edit/")
    else:
        template_form = MasterTemplateForm(instance=template)
        wbs_formset = WBSFormSet(queryset=template.wbs_items.all(), prefix="wbs")
        budget_formset = BudgetFormSet(queryset=template.budget_items.all(), prefix="budget")
    return render(
        request,
        "app/hq/master_template_form.html",
        {
            "template": template,
            "template_form": template_form,
            "wbs_formset": wbs_formset,
            "budget_formset": budget_formset,
            "mode": "edit",
        },
    )


def master_template_clone_view(request, pk):
    require_role(request.user, [Role.HQ], request=request)
    if request.method != "POST":
        raise PermissionDenied
    template = get_object_or_404(MasterTemplate, pk=pk)
    with transaction.atomic():
        latest = (
            MasterTemplate.objects.filter(category=template.category, domain=template.domain)
            .order_by("-version")
            .first()
        )
        next_version = (latest.version if latest else template.version) + 1
        clone = MasterTemplate.objects.create(
            name=template.name,
            category=template.category,
            domain=template.domain,
            version=next_version,
            is_active=True,
            created_by=request.user,
            note=f"Cloned from v{template.version}",
        )
        if template.category == MasterTemplateCategory.WBS:
            items = [
                MasterWBSTemplateItem(
                    template=clone,
                    order=item.order,
                    task_name=item.task_name,
                    weight=item.weight,
                    default_offset_start_days=item.default_offset_start_days,
                    default_duration_days=item.default_duration_days,
                )
                for item in template.wbs_items.all()
            ]
            MasterWBSTemplateItem.objects.bulk_create(items)
        if template.category == MasterTemplateCategory.BUDGET:
            items = [
                MasterBudgetTemplateItem(
                    template=clone,
                    order=item.order,
                    cost_item=item.cost_item,
                    cost_item_code_snapshot=item.cost_item_code_snapshot,
                    label=item.label,
                    is_labor=item.is_labor,
                    default_amount=item.default_amount,
                )
                for item in template.budget_items.all()
            ]
            MasterBudgetTemplateItem.objects.bulk_create(items)
    _log_template_action(request, "TEMPLATE_CLONE", clone)
    return redirect(f"/app/hq/master/templates/{clone.id}/edit/")


def master_template_toggle_active(request, pk):
    require_role(request.user, [Role.HQ], request=request)
    if request.method != "POST":
        raise PermissionDenied
    template = get_object_or_404(MasterTemplate, pk=pk)
    template.is_active = not template.is_active
    template.save(update_fields=["is_active", "updated_at"])
    _log_template_action(request, "TEMPLATE_TOGGLE", template)
    return redirect("/app/hq/master/templates/")


def _template_items_valid(category, wbs_formset, budget_formset):
    if category == MasterTemplateCategory.WBS:
        if not wbs_formset.is_valid():
            return False
        weight_sum = Decimal("0")
        for form in wbs_formset:
            if not form.cleaned_data or form.cleaned_data.get("DELETE"):
                continue
            weight_sum += Decimal(form.cleaned_data.get("weight") or 0)
        if weight_sum != Decimal("100"):
            wbs_formset._non_form_errors = ["WBS 가중치 합계는 100%여야 합니다."]
            return False
    if category == MasterTemplateCategory.BUDGET:
        if not budget_formset.is_valid():
            return False
    if category not in (MasterTemplateCategory.WBS, MasterTemplateCategory.BUDGET):
        return False
    return True


def _save_wbs_template_items(template, formset):
    items = []
    for form in formset:
        if not form.cleaned_data:
            continue
        if form.cleaned_data.get("DELETE"):
            continue
        items.append(
            MasterWBSTemplateItem(
                template=template,
                order=form.cleaned_data.get("order") or 0,
                task_name=form.cleaned_data.get("task_name"),
                weight=form.cleaned_data.get("weight") or 0,
                default_offset_start_days=form.cleaned_data.get("default_offset_start_days"),
                default_duration_days=form.cleaned_data.get("default_duration_days"),
            )
        )
    template.wbs_items.all().delete()
    if items:
        MasterWBSTemplateItem.objects.bulk_create(items)


def _save_budget_template_items(template, formset):
    items = []
    for form in formset:
        if not form.cleaned_data:
            continue
        if form.cleaned_data.get("DELETE"):
            continue
        cost_item = form.cleaned_data.get("cost_item")
        items.append(
            MasterBudgetTemplateItem(
                template=template,
                order=form.cleaned_data.get("order") or 0,
                cost_item=cost_item,
                cost_item_code_snapshot=getattr(cost_item, "code", "") if cost_item else "",
                label=form.cleaned_data.get("label"),
                is_labor=bool(form.cleaned_data.get("is_labor")),
                default_amount=form.cleaned_data.get("default_amount"),
            )
        )
    template.budget_items.all().delete()
    if items:
        MasterBudgetTemplateItem.objects.bulk_create(items)


def _log_template_action(request, action, template):
    try:
        log_action(
            actor=request.user,
            action=action,
            object_type="MASTER_TEMPLATE",
            object_id=template.id,
            meta={
                "category": template.category,
                "domain": template.domain,
                "version": template.version,
            },
            request=request,
        )
    except Exception:
        logger.warning("AuditLog failed for master template action.", exc_info=True)
