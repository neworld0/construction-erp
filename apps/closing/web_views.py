from __future__ import annotations

from datetime import date

from django.contrib import messages
from django.core.exceptions import PermissionDenied, ValidationError
from django.db.models import Sum
from django.shortcuts import get_object_or_404, redirect, render
from django.utils import timezone

from apps.audit.services.logger import log_action
from apps.core.rbac.models import LegalEntity, Role
from apps.core.rbac.permissions import get_current_legal_entity, get_user_legal_entities, get_user_role, require_legal_entity_access, require_role
from apps.core.models import ApprovalRequest, ApprovalStatus
from apps.cost.models import CostActual, CostActualStatus
from apps.projects.models import Project

from .adjustments import (
    approve_adjustment,
    create_adjustment,
    reject_adjustment,
    submit_adjustment,
)
from .forms import AdjustmentDecisionForm, AdjustmentForm
from .models import (
    Adjustment,
    AdjustmentStatus,
    AdjustmentTargetType,
    ClosingApprovalPolicy,
    ClosingPeriod,
    ClosingStatus,
)
from .services import close_month, get_closing_period
from .reconciliation import build_project_reconciliation
from .revenue_recognition import (
    build_revenue_recognition_preview,
    period_end_date,
    recognize_revenue_and_cost_for_close,
)
from apps.cost.models import RevenueRecognitionTrigger


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
    require_role(request.user, [Role.CEO, Role.HQ], request=request)
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
    require_role(request.user, [Role.CEO, Role.HQ], request=request)
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
        "ceo_read_only": get_user_role(request.user) != Role.CEO,
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


def _closing_periods_for_list(today, legal_entity):
    """Return the recent calendar months plus every persisted closing period.

    A period can be created and approved ahead of the server's current date
    during operational rehearsals.  Those persisted records must remain
    visible even though they are outside the default 12-month lookback.
    """
    periods_by_month = {}
    for offset in range(12):
        year, month = _month_back(today, offset)
        period = get_closing_period(year, month, legal_entity=legal_entity)
        if period is None:
            period = ClosingPeriod(
                legal_entity=legal_entity, year=year, month=month, status=ClosingStatus.OPEN, closed_at=None
            )
        periods_by_month[(year, month)] = period

    for period in ClosingPeriod.objects.filter(legal_entity=legal_entity):
        periods_by_month[(period.year, period.month)] = period

    return sorted(
        periods_by_month.values(), key=lambda period: (period.year, period.month), reverse=True
    )


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


def hq_project_reconciliation(request):
    require_role(request.user, [Role.HQ, Role.CEO], request=request)
    project_id = request.GET.get("project_id")
    project = Project.objects.filter(id=project_id, is_active=True).first() if str(project_id).isdigit() else None
    try:
        as_of_date = date.fromisoformat(request.GET.get("as_of_date") or "")
    except ValueError:
        as_of_date = timezone.localdate()
    purpose = request.GET.get("purpose") or "closing"
    reconciliation = None
    if project:
        reconciliation = build_project_reconciliation(
            project=project,
            as_of_date=as_of_date,
            require_completion=purpose == "completion",
        )
    return render(request, "app/hq/project_reconciliation.html", {
        "projects": Project.objects.filter(is_active=True).order_by("name"),
        "selected_project": project,
        "as_of_date": as_of_date,
        "purpose": purpose,
        "reconciliation": reconciliation,
    })


def hq_closing_list(request):
    require_role(request.user, [Role.HQ, Role.CEO], request=request)
    role = get_user_role(request.user)
    year_filter = request.GET.get("year")
    status_filter = request.GET.get("status")
    q = (request.GET.get("q") or "").strip()

    today = timezone.localdate()
    legal_entity = get_current_legal_entity(request)
    if legal_entity is None:
        raise PermissionDenied("법인 접근 권한이 없습니다.")
    periods = _closing_periods_for_list(today, legal_entity)

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


def hq_revenue_recognition(request):
    """HQ-only preview and execution of the evidence snapshot after month close."""
    require_role(request.user, [Role.HQ], request=request)
    today = timezone.localdate()
    project_id = request.POST.get("project_id") if request.method == "POST" else request.GET.get("project_id")
    year = request.POST.get("year") if request.method == "POST" else request.GET.get("year")
    month = request.POST.get("month") if request.method == "POST" else request.GET.get("month")
    year = int(year) if str(year).isdigit() else today.year
    month = int(month) if str(month).isdigit() and 1 <= int(month) <= 12 else today.month
    project = Project.objects.filter(id=project_id, is_active=True).first() if str(project_id).isdigit() else None
    preview = None
    if project is not None:
        close_date = period_end_date(year, month)
        preview = build_revenue_recognition_preview(project, close_date=close_date)
        if request.method == "POST" and request.POST.get("action") == "execute":
            try:
                recognize_revenue_and_cost_for_close(
                    project=project,
                    close_date=close_date,
                    trigger_type=RevenueRecognitionTrigger.MONTHLY_CLOSE,
                    actor=request.user,
                    memo=(request.POST.get("memo") or "").strip(),
                    request=request,
                )
                messages.success(request, "매출·원가 인식이 완료되었습니다.")
                return redirect(f"/app/hq/closing/revenue-recognition/?project_id={project.id}&year={year}&month={month}")
            except (PermissionDenied, ValidationError) as exc:
                messages.error(request, str(exc))
    return render(request, "app/hq/revenue_recognition.html", {
        "projects": Project.objects.filter(is_active=True).order_by("name"),
        "selected_project": project,
        "year": year,
        "month": month,
        "preview": preview,
    })


def hq_closing_new(request):
    require_role(request.user, [Role.HQ, Role.CEO], request=request)
    role = get_user_role(request.user)
    if request.method == "POST":
        year = request.POST.get("year")
        month = request.POST.get("month")
        approval_policy = request.POST.get("approval_policy") or ClosingApprovalPolicy.HQ_SINGLE
        note = (request.POST.get("note") or "").strip()
        if not (year and month and year.isdigit() and month.isdigit()):
            messages.error(request, "연도와 월을 입력해 주세요.")
            return render(request, "app/hq/closing_new.html", {"role": role})
        year_int = int(year)
        month_int = int(month)
        if not (1 <= month_int <= 12):
            messages.error(request, "월은 1~12 사이여야 합니다.")
            return render(request, "app/hq/closing_new.html", {"role": role})
        if approval_policy not in ClosingApprovalPolicy.values:
            messages.error(request, "마감 승인 방식을 선택해 주세요.")
            return render(request, "app/hq/closing_new.html", {"role": role})

        legal_entity = get_object_or_404(LegalEntity, id=request.POST.get("legal_entity_id"), is_active=True)
        require_legal_entity_access(request.user, legal_entity, request=request)
        period, _created = ClosingPeriod.objects.get_or_create(
            legal_entity=legal_entity,
            year=year_int,
            month=month_int,
            defaults={
                "status": ClosingStatus.OPEN,
                "approval_policy": approval_policy,
            },
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

    return render(
        request,
        "app/hq/closing_new.html",
        {"role": role, "approval_policies": ClosingApprovalPolicy.choices, "legal_entities": get_user_legal_entities(request.user), "current_legal_entity": get_current_legal_entity(request)},
    )


def hq_closing_detail(request, closing_id):
    require_role(request.user, [Role.HQ, Role.CEO], request=request)
    role = get_user_role(request.user)
    period = get_object_or_404(ClosingPeriod.objects.select_related("legal_entity"), id=closing_id)
    require_legal_entity_access(request.user, period.legal_entity, request=request)
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
    period = get_object_or_404(ClosingPeriod.objects.select_related("legal_entity"), id=closing_id)
    require_legal_entity_access(request.user, period.legal_entity, request=request)
    request_obj = _get_latest_closing_request(period)
    if not request_obj:
        messages.error(request, "제출할 마감 요청이 없습니다.")
        return redirect(f"/app/hq/closing/{period.id}/")
    if request_obj.status != ApprovalStatus.DRAFT:
        messages.error(request, "이미 제출되었거나 처리된 요청입니다.")
        return redirect(f"/app/hq/closing/{period.id}/")
    if period.approval_policy == ClosingApprovalPolicy.HQ_SINGLE:
        try:
            close_month(period.year, period.month, request.user, legal_entity=period.legal_entity, note=request_obj.comment)
        except ValidationError as exc:
            messages.error(request, str(exc))
            return redirect(f"/app/hq/closing/{period.id}/")
        request_obj.status = ApprovalStatus.APPROVED
        request_obj.approved_by = request.user
        request_obj.approved_at = timezone.now()
        request_obj.save(update_fields=["status", "approved_by", "approved_at", "updated_at"])
        _log_closing_event(
            request.user,
            action="CLOSING_HQ_SINGLE_APPROVE",
            period=period,
            request_obj=request_obj,
            request=request,
            note=request_obj.comment,
        )
        messages.success(request, "HQ 단독 확정으로 월 마감이 완료되었습니다.")
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
    if period.approval_policy == ClosingApprovalPolicy.HQ_DUAL:
        messages.success(request, "다른 HQ 담당자의 2차 검토 요청이 제출되었습니다.")
    else:
        messages.success(request, "CEO 예외 승인 요청이 제출되었습니다.")
    return redirect(f"/app/hq/closing/{period.id}/")


def hq_closing_dual_approve(request, closing_id):
    require_role(request.user, [Role.HQ], request=request)
    period = get_object_or_404(ClosingPeriod.objects.select_related("legal_entity"), id=closing_id)
    require_legal_entity_access(request.user, period.legal_entity, request=request)
    request_obj = _get_latest_closing_request(period)
    if period.approval_policy != ClosingApprovalPolicy.HQ_DUAL:
        messages.error(request, "HQ 2단계 통제로 요청된 마감만 2차 확정할 수 있습니다.")
    elif not request_obj or request_obj.status != ApprovalStatus.SUBMITTED:
        messages.error(request, "2차 확정 가능한 요청이 없습니다.")
    elif request_obj.submitted_by_id == request.user.id:
        messages.error(request, "HQ 2단계 통제에서는 요청자와 확정자가 달라야 합니다.")
    else:
        try:
            close_month(period.year, period.month, request.user, legal_entity=period.legal_entity, note=request_obj.comment)
        except ValidationError as exc:
            messages.error(request, str(exc))
        else:
            request_obj.status = ApprovalStatus.APPROVED
            request_obj.approved_by = request.user
            request_obj.approved_at = timezone.now()
            request_obj.save(update_fields=["status", "approved_by", "approved_at", "updated_at"])
            _log_closing_event(
                request.user,
                action="CLOSING_HQ_DUAL_APPROVE",
                period=period,
                request_obj=request_obj,
                request=request,
                note=request_obj.comment,
            )
            messages.success(request, "HQ 2차 확정으로 월 마감이 완료되었습니다.")
    return redirect(f"/app/hq/closing/{period.id}/")


def hq_closing_dual_reject(request, closing_id):
    require_role(request.user, [Role.HQ], request=request)
    period = get_object_or_404(ClosingPeriod.objects.select_related("legal_entity"), id=closing_id)
    require_legal_entity_access(request.user, period.legal_entity, request=request)
    request_obj = _get_latest_closing_request(period)
    note = (request.POST.get("decision_note") or "").strip()
    if period.approval_policy != ClosingApprovalPolicy.HQ_DUAL:
        messages.error(request, "HQ 2단계 통제로 요청된 마감만 반려할 수 있습니다.")
    elif not request_obj or request_obj.status != ApprovalStatus.SUBMITTED:
        messages.error(request, "반려 가능한 요청이 없습니다.")
    elif request_obj.submitted_by_id == request.user.id:
        messages.error(request, "HQ 2단계 통제에서는 요청자와 검토자가 달라야 합니다.")
    elif not note:
        messages.error(request, "반려 사유를 입력해 주세요.")
    else:
        request_obj.status = ApprovalStatus.REJECTED
        request_obj.reject_reason = note
        request_obj.save(update_fields=["status", "reject_reason", "updated_at"])
        _log_closing_event(
            request.user,
            action="CLOSING_HQ_DUAL_REJECT",
            period=period,
            request_obj=request_obj,
            request=request,
            note=note,
        )
        messages.success(request, "HQ 2차 검토에서 마감 요청을 반려했습니다.")
    return redirect(f"/app/hq/closing/{period.id}/")


def ceo_closing_approve(request, closing_id):
    require_role(request.user, [Role.CEO], request=request)
    period = get_object_or_404(ClosingPeriod.objects.select_related("legal_entity"), id=closing_id)
    require_legal_entity_access(request.user, period.legal_entity, request=request)
    request_obj = _get_latest_closing_request(period)
    if period.approval_policy != ClosingApprovalPolicy.CEO:
        messages.error(request, "CEO 예외 승인으로 요청된 마감이 아닙니다.")
        return redirect(f"/app/hq/closing/{period.id}/")
    if not request_obj or request_obj.status != ApprovalStatus.SUBMITTED:
        messages.error(request, "승인 가능한 요청이 없습니다.")
        return redirect(f"/app/hq/closing/{period.id}/")
    try:
        close_month(period.year, period.month, request.user, legal_entity=period.legal_entity, note=request_obj.comment)
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
    period = get_object_or_404(ClosingPeriod.objects.select_related("legal_entity"), id=closing_id)
    require_legal_entity_access(request.user, period.legal_entity, request=request)
    request_obj = _get_latest_closing_request(period)
    if period.approval_policy != ClosingApprovalPolicy.CEO:
        messages.error(request, "CEO 예외 승인으로 요청된 마감이 아닙니다.")
        return redirect(f"/app/hq/closing/{period.id}/")
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
