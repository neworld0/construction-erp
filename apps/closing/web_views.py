from __future__ import annotations

from datetime import date

from django.contrib import messages
from django.core.exceptions import PermissionDenied, ValidationError
from django.db.models import Sum
from django.shortcuts import get_object_or_404, redirect, render
from django.utils import timezone

from apps.audit.services.logger import log_action
from apps.core.rbac.models import Role
from apps.core.rbac.permissions import get_user_role, require_role
from apps.core.models import ApprovalRequest, ApprovalStatus
from apps.cost.models import CostActual, CostActualStatus

from .adjustments import (
    approve_adjustment,
    create_adjustment,
    reject_adjustment,
    submit_adjustment,
)
from .forms import AdjustmentDecisionForm, AdjustmentForm
from .models import Adjustment, AdjustmentStatus, AdjustmentTargetType, ClosingPeriod, ClosingStatus
from .services import close_month, get_closing_period


def _apply_filters(qs, request):
    project_id = request.GET.get("project_id")
    status = request.GET.get("status")
    year = request.GET.get("year")
    month = request.GET.get("month")
    if project_id and str(project_id).isdigit():
        qs = qs.filter(project_id=int(project_id))
    if status:
        qs = qs.filter(status=status)
    if year and month and str(year).isdigit() and str(month).isdigit():
        qs = qs.filter(period_year=int(year), period_month=int(month))
    return qs


def _get_cost_base_amount(adjustment: Adjustment):
    if adjustment.target_type != AdjustmentTargetType.COST:
        return None
    return (
        CostActual.objects.filter(
            project=adjustment.project,
            report_date__year=adjustment.period_year,
            report_date__month=adjustment.period_month,
            status__in=[CostActualStatus.APPROVED, CostActualStatus.CLOSED],
        ).aggregate(total=Sum("total_amount"))["total"]
    )


def field_adjustment_new(request):
    require_role(request.user, [Role.FIELD], request=request)
    role = get_user_role(request.user)
    if request.method == "POST":
        form = AdjustmentForm(request.POST, user=request.user, role=role)
        action = request.POST.get("action", "draft")
        if form.is_valid():
            adjustment = create_adjustment(
                actor=request.user,
                project=form.cleaned_data["project"],
                target_type=form.cleaned_data["target_type"],
                period_year=form.cleaned_data["period_year"],
                period_month=form.cleaned_data["period_month"],
                amount_delta=form.cleaned_data["amount_delta"],
                reason=form.cleaned_data["reason"],
                cbs=form.cleaned_data.get("cbs"),
            )
            if action == "submit":
                submit_adjustment(adjustment, actor=request.user, request=request)
                messages.success(request, "정정 요청이 제출되었습니다.")
            else:
                messages.success(request, "정정 요청이 임시저장되었습니다.")
            return redirect("/app/field/adjustments/new/")
        messages.error(request, "입력 오류가 있습니다. 아래 항목을 확인해 주세요.")
    else:
        form = AdjustmentForm(user=request.user, role=role)

    adjustments = (
        Adjustment.objects.filter(created_by=request.user)
        .select_related("project", "cbs", "created_by", "approved_by")
        .order_by("-created_at")[:20]
    )
    return render(
        request,
        "app/field/adjustment_form.html",
        {"form": form, "adjustments": adjustments, "role": role},
    )


def field_adjustment_detail(request, adjustment_id):
    require_role(request.user, [Role.FIELD], request=request)
    adjustment = get_object_or_404(
        Adjustment.objects.select_related("project", "cbs", "created_by", "approved_by"),
        id=adjustment_id,
        created_by=request.user,
    )
    if request.method == "POST":
        if adjustment.status in (AdjustmentStatus.DRAFT, AdjustmentStatus.REJECTED):
            try:
                submit_adjustment(adjustment, actor=request.user, request=request)
                messages.success(request, "정정 요청이 제출되었습니다.")
            except (ValidationError, PermissionDenied) as exc:
                messages.error(request, str(exc))
        else:
            messages.error(request, "제출할 수 없는 상태입니다.")
        return redirect(f"/app/field/adjustments/{adjustment.id}/")

    context = {
        "adjustment": adjustment,
        "base_amount": _get_cost_base_amount(adjustment),
        "can_submit": adjustment.status in (AdjustmentStatus.DRAFT, AdjustmentStatus.REJECTED),
        "role": get_user_role(request.user),
    }
    return render(request, "app/field/adjustment_detail.html", context)


def hq_adjustment_list(request):
    require_role(request.user, [Role.HQ], request=request)
    qs = Adjustment.objects.select_related(
        "project", "cbs", "created_by", "approved_by"
    ).order_by("-created_at")
    qs = _apply_filters(qs, request)
    return render(
        request,
        "app/hq/adjustment_list.html",
        {"adjustments": qs, "role": get_user_role(request.user)},
    )


def hq_adjustment_detail(request, adjustment_id):
    require_role(request.user, [Role.HQ], request=request)
    adjustment = get_object_or_404(
        Adjustment.objects.select_related("project", "cbs", "created_by", "approved_by"),
        id=adjustment_id,
    )
    context = {
        "adjustment": adjustment,
        "base_amount": _get_cost_base_amount(adjustment),
        "can_submit": adjustment.status in (AdjustmentStatus.DRAFT, AdjustmentStatus.REJECTED),
        "role": get_user_role(request.user),
    }
    return render(request, "app/hq/adjustment_detail.html", context)


def hq_adjustment_submit(request, adjustment_id):
    require_role(request.user, [Role.HQ], request=request)
    adjustment = get_object_or_404(Adjustment, id=adjustment_id)
    try:
        submit_adjustment(adjustment, actor=request.user, request=request)
        messages.success(request, "정정 요청이 제출되었습니다.")
    except (ValidationError, PermissionDenied) as exc:
        messages.error(request, str(exc))
    return redirect(f"/app/hq/adjustments/{adjustment.id}/")


def ceo_adjustment_list(request):
    require_role(request.user, [Role.CEO], request=request)
    qs = (
        Adjustment.objects.select_related("project", "cbs", "created_by", "approved_by")
        .order_by("-created_at")
    )
    qs = _apply_filters(qs, request)
    return render(
        request,
        "app/ceo/adjustment_list.html",
        {"adjustments": qs, "role": get_user_role(request.user)},
    )


def ceo_adjustment_detail(request, adjustment_id):
    require_role(request.user, [Role.CEO], request=request)
    adjustment = get_object_or_404(
        Adjustment.objects.select_related("project", "cbs", "created_by", "approved_by"),
        id=adjustment_id,
    )
    decision_form = AdjustmentDecisionForm()
    context = {
        "adjustment": adjustment,
        "base_amount": _get_cost_base_amount(adjustment),
        "decision_form": decision_form,
        "role": get_user_role(request.user),
    }
    return render(request, "app/ceo/adjustment_detail.html", context)


def ceo_adjustment_approve(request, adjustment_id):
    require_role(request.user, [Role.CEO], request=request)
    adjustment = get_object_or_404(Adjustment, id=adjustment_id)
    try:
        approve_adjustment(adjustment, actor=request.user, request=request)
        messages.success(request, "정정 요청이 승인되었습니다.")
    except ValidationError as exc:
        messages.error(request, str(exc))
    return redirect(f"/app/ceo/adjustments/{adjustment.id}/")


def ceo_adjustment_reject(request, adjustment_id):
    require_role(request.user, [Role.CEO], request=request)
    adjustment = get_object_or_404(Adjustment, id=adjustment_id)
    form = AdjustmentDecisionForm(request.POST)
    if not form.is_valid():
        messages.error(request, "반려 사유를 입력하세요.")
        return redirect(f"/app/ceo/adjustments/{adjustment.id}/")
    note = form.cleaned_data.get("note")
    try:
        reject_adjustment(adjustment, actor=request.user, request=request, note=note)
        messages.success(request, "정정 요청이 반려되었습니다.")
    except ValidationError as exc:
        messages.error(request, str(exc))
    return redirect(f"/app/ceo/adjustments/{adjustment.id}/")


def _month_back(date_value, months_back):
    year = date_value.year
    month = date_value.month - months_back
    while month <= 0:
        month += 12
        year -= 1
    return year, month


def _get_latest_closing_request(period: ClosingPeriod):
    return (
        ApprovalRequest.objects.filter(
            object_type="CLOSING_PERIOD", object_id=period.id
        )
        .order_by("-created_at")
        .first()
    )


def _log_closing_event(actor, *, action, period, request_obj=None, request=None, note=None):
    log_action(
        actor=actor,
        action=action,
        object_type="ClosingPeriod",
        object_id=period.id,
        request=request,
        meta={
            "year": period.year,
            "month": period.month,
            "request_id": request_obj.id if request_obj else None,
            "note": note or "",
        },
    )


def hq_closing_list(request):
    require_role(request.user, [Role.HQ, Role.CEO], request=request)
    role = get_user_role(request.user)
    year_filter = request.GET.get("year")
    status_filter = request.GET.get("status")
    q = (request.GET.get("q") or "").strip()

    today = timezone.localdate()
    periods = []
    for offset in range(12):
        year, month = _month_back(today, offset)
        period = get_closing_period(year, month)
        if not period:
            period = ClosingPeriod(
                year=year, month=month, status=ClosingStatus.OPEN, closed_at=None
            )
        periods.append(period)

    if year_filter and year_filter.isdigit():
        periods = [p for p in periods if p.year == int(year_filter)]
    if status_filter in (ClosingStatus.OPEN, ClosingStatus.CLOSED):
        periods = [p for p in periods if p.status == status_filter]
    if q:
        periods = [
            p for p in periods if q in f"{p.year}-{p.month:02d}"
        ]

    items = []
    for period in periods:
        request_obj = None
        if period.id:
            request_obj = _get_latest_closing_request(period)
        items.append(
            {
                "period": period,
                "request": request_obj,
            }
        )

    return render(
        request,
        "app/hq/closing_list.html",
        {
            "items": items,
            "role": role,
            "year_filter": year_filter or "",
            "status_filter": status_filter or "",
            "q": q,
        },
    )


def hq_closing_new(request):
    require_role(request.user, [Role.HQ, Role.CEO], request=request)
    role = get_user_role(request.user)
    if request.method == "POST":
        year = request.POST.get("year")
        month = request.POST.get("month")
        note = (request.POST.get("note") or "").strip()
        if not (year and month and year.isdigit() and month.isdigit()):
            messages.error(request, "연도와 월을 입력해 주세요.")
            return render(request, "app/hq/closing_new.html", {"role": role})
        year_int = int(year)
        month_int = int(month)
        if not (1 <= month_int <= 12):
            messages.error(request, "월은 1~12 사이여야 합니다.")
            return render(request, "app/hq/closing_new.html", {"role": role})

        period, _created = ClosingPeriod.objects.get_or_create(
            year=year_int, month=month_int, defaults={"status": ClosingStatus.OPEN}
        )
        if period.status == ClosingStatus.CLOSED:
            messages.error(request, "이미 마감된 월입니다.")
            return render(request, "app/hq/closing_new.html", {"role": role})

        existing = _get_latest_closing_request(period)
        if existing and existing.status in (ApprovalStatus.DRAFT, ApprovalStatus.SUBMITTED):
            messages.error(request, "해당 월에 대기 중인 마감 요청이 이미 있습니다.")
            return render(request, "app/hq/closing_new.html", {"role": role})

        request_obj = ApprovalRequest.objects.create(
            object_type="CLOSING_PERIOD",
            object_id=period.id,
            status=ApprovalStatus.DRAFT,
            submitted_by=request.user,
            comment=note,
        )
        _log_closing_event(
            request.user,
            action="CLOSING_REQUEST_CREATE",
            period=period,
            request_obj=request_obj,
            request=request,
            note=note,
        )
        messages.success(request, "마감 요청이 생성되었습니다.")
        return redirect(f"/app/hq/closing/{period.id}/")

    return render(request, "app/hq/closing_new.html", {"role": role})


def hq_closing_detail(request, closing_id):
    require_role(request.user, [Role.HQ, Role.CEO], request=request)
    role = get_user_role(request.user)
    period = get_object_or_404(ClosingPeriod, id=closing_id)
    request_obj = _get_latest_closing_request(period)
    return render(
        request,
        "app/hq/closing_detail.html",
        {
            "period": period,
            "request_obj": request_obj,
            "role": role,
        },
    )


def hq_closing_submit(request, closing_id):
    require_role(request.user, [Role.HQ], request=request)
    period = get_object_or_404(ClosingPeriod, id=closing_id)
    request_obj = _get_latest_closing_request(period)
    if not request_obj:
        messages.error(request, "제출할 마감 요청이 없습니다.")
        return redirect(f"/app/hq/closing/{period.id}/")
    if request_obj.status != ApprovalStatus.DRAFT:
        messages.error(request, "이미 제출되었거나 처리된 요청입니다.")
        return redirect(f"/app/hq/closing/{period.id}/")
    request_obj.status = ApprovalStatus.SUBMITTED
    request_obj.submitted_at = timezone.now()
    request_obj.submitted_by = request.user
    request_obj.save(update_fields=["status", "submitted_at", "submitted_by", "updated_at"])
    _log_closing_event(
        request.user,
        action="CLOSING_REQUEST_SUBMIT",
        period=period,
        request_obj=request_obj,
        request=request,
        note=request_obj.comment,
    )
    messages.success(request, "CEO 승인 요청이 제출되었습니다.")
    return redirect(f"/app/hq/closing/{period.id}/")


def ceo_closing_approve(request, closing_id):
    require_role(request.user, [Role.CEO], request=request)
    period = get_object_or_404(ClosingPeriod, id=closing_id)
    request_obj = _get_latest_closing_request(period)
    if not request_obj or request_obj.status != ApprovalStatus.SUBMITTED:
        messages.error(request, "승인 가능한 요청이 없습니다.")
        return redirect(f"/app/hq/closing/{period.id}/")
    try:
        close_month(period.year, period.month, request.user, note=request_obj.comment)
    except ValidationError as exc:
        messages.error(request, str(exc))
        return redirect(f"/app/hq/closing/{period.id}/")
    request_obj.status = ApprovalStatus.APPROVED
    request_obj.approved_by = request.user
    request_obj.approved_at = timezone.now()
    request_obj.save(update_fields=["status", "approved_by", "approved_at", "updated_at"])
    _log_closing_event(
        request.user,
        action="CLOSING_REQUEST_APPROVE",
        period=period,
        request_obj=request_obj,
        request=request,
        note=request_obj.comment,
    )
    messages.success(request, "월 마감이 완료되었습니다.")
    return redirect(f"/app/hq/closing/{period.id}/")


def ceo_closing_reject(request, closing_id):
    require_role(request.user, [Role.CEO], request=request)
    period = get_object_or_404(ClosingPeriod, id=closing_id)
    request_obj = _get_latest_closing_request(period)
    if not request_obj or request_obj.status != ApprovalStatus.SUBMITTED:
        messages.error(request, "반려 가능한 요청이 없습니다.")
        return redirect(f"/app/hq/closing/{period.id}/")
    note = (request.POST.get("decision_note") or "").strip()
    if not note:
        messages.error(request, "반려 사유를 입력해 주세요.")
        return redirect(f"/app/hq/closing/{period.id}/")
    request_obj.status = ApprovalStatus.REJECTED
    request_obj.reject_reason = note
    request_obj.save(update_fields=["status", "reject_reason", "updated_at"])
    _log_closing_event(
        request.user,
        action="CLOSING_REQUEST_REJECT",
        period=period,
        request_obj=request_obj,
        request=request,
        note=note,
    )
    messages.success(request, "마감 요청이 반려되었습니다.")
    return redirect(f"/app/hq/closing/{period.id}/")
