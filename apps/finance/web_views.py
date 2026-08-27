from datetime import date

from django.contrib import messages
from django.contrib.auth.decorators import login_required
from django.core.exceptions import PermissionDenied, ValidationError
from django.shortcuts import get_object_or_404, redirect, render
from django.utils import timezone

from apps.core.rbac.models import Role
from apps.core.rbac.permissions import (
    get_current_legal_entity,
    get_user_legal_entities,
    require_legal_entity_access,
    require_role,
)
from apps.closing.services import is_month_closed
from apps.finance.models import AdvancePayment, ExpenseExecution, ExpenseExecutionStatus, ProgressBilling
from apps.finance.services.expense_execution import cancel_expense_execution, pay_expense_execution, schedule_expense_execution
from apps.finance.services.progress_billing import (
    build_progress_billing_preview,
    collect_progress_billing,
    issue_progress_billing,
    register_advance_payment,
)
from apps.projects.models import Project


def _parse_date(value, default=None):
    try:
        return date.fromisoformat(value) if value else default
    except ValueError:
        return None


def _first_open_collection_date(start_date, legal_entity):
    """Suggest the first available cash-receipt date without changing its actual-date rule."""
    candidate = start_date
    while is_month_closed(candidate, legal_entity=legal_entity):
        if candidate.month == 12:
            candidate = candidate.replace(year=candidate.year + 1, month=1, day=1)
        else:
            candidate = candidate.replace(month=candidate.month + 1, day=1)
    return candidate


@login_required
def hq_progress_billing(request):
    require_role(request.user, [Role.HQ], request=request)
    today = timezone.localdate()
    legal_entity = get_current_legal_entity(request)
    if legal_entity is None:
        raise PermissionDenied("선택 가능한 법인이 없습니다.")
    projects = Project.objects.filter(
        is_active=True,
        legal_entity=legal_entity,
    ).order_by("name")
    selected_id = request.POST.get("project_id") if request.method == "POST" else request.GET.get("project_id")
    selected_project = projects.filter(id=selected_id).first() if str(selected_id).isdigit() else None
    billing_date = _parse_date(request.POST.get("billing_date") if request.method == "POST" else request.GET.get("billing_date"), today)
    if request.method == "POST":
        action = request.POST.get("action")
        try:
            if action == "register_advance":
                if selected_project is None or billing_date is None:
                    raise ValidationError("프로젝트와 선급금 수령일을 확인해 주세요.")
                register_advance_payment(project=selected_project, advance_rate_percent=request.POST.get("advance_rate_percent"), received_amount=request.POST.get("received_amount"), received_date=billing_date, actor=request.user, memo=(request.POST.get("memo") or "").strip(), request=request)
                messages.success(request, "선급금 수령이 등록되었습니다.")
            elif action == "issue":
                if selected_project is None or billing_date is None:
                    raise ValidationError("프로젝트와 기성 기준일을 확인해 주세요.")
                issue_progress_billing(project=selected_project, billing_date=billing_date, actor=request.user, memo=(request.POST.get("memo") or "").strip(), request=request)
                messages.success(request, "기성청구가 확정되었습니다. 예정 수금에 반영됩니다.")
            elif action == "collect":
                billing = get_object_or_404(
                    ProgressBilling.objects.select_related("project").filter(project__legal_entity=legal_entity),
                    id=request.POST.get("billing_id"),
                )
                collected_date = _parse_date(request.POST.get("collected_date"), today)
                if collected_date is None:
                    raise ValidationError("수금일을 확인해 주세요.")
                collect_progress_billing(billing=billing, collected_date=collected_date, actor=request.user, request=request)
                messages.success(request, "기성금 수금이 등록되었습니다.")
            else:
                raise ValidationError("처리 방식을 확인해 주세요.")
        except (PermissionDenied, ValidationError) as exc:
            messages.error(request, str(exc))
        query = f"?project_id={selected_project.id}" if selected_project else ""
        if billing_date:
            query += ("&" if query else "?") + f"billing_date={billing_date.isoformat()}"
        return redirect("/app/hq/finance/billings/" + query)

    preview = build_progress_billing_preview(selected_project, billing_date=billing_date) if selected_project and billing_date else None
    billings = ProgressBilling.objects.select_related("project").filter(
        project__legal_entity=legal_entity,
    ).order_by("-billing_date", "-id")
    if selected_project:
        billings = billings.filter(project=selected_project)
    billings = list(billings[:30])
    for billing in billings:
        billing.collection_date_default = _first_open_collection_date(billing.billing_date, legal_entity)
    return render(request, "app/hq/progress_billing.html", {
        "projects": projects,
        "legal_entities": get_user_legal_entities(request.user),
        "current_legal_entity": legal_entity,
        "selected_project": selected_project,
        "billing_date": billing_date,
        "advance": AdvancePayment.objects.filter(project=selected_project).first() if selected_project else None,
        "preview": preview,
        "billings": billings,
        "today": today,
    })


@login_required
def hq_expense_execution_list(request):
    require_role(request.user, [Role.HQ], request=request)
    today = timezone.localdate()
    legal_entity = get_current_legal_entity(request)
    if legal_entity is None:
        raise PermissionDenied("선택 가능한 법인이 없습니다.")
    selected_status = (request.POST.get("status") if request.method == "POST" else request.GET.get("status")) or "open"
    if request.method == "POST":
        execution = get_object_or_404(
            ExpenseExecution.objects.select_related("cost_actual__project", "cash_event").filter(
                cost_actual__project__legal_entity=legal_entity,
            ),
            id=request.POST.get("execution_id"),
        )
        action = request.POST.get("action")
        try:
            if action == "schedule":
                scheduled_date = _parse_date(request.POST.get("scheduled_date"))
                if scheduled_date is None:
                    raise ValidationError("지급 예정일을 확인해 주세요.")
                schedule_expense_execution(execution=execution, scheduled_date=scheduled_date, memo=request.POST.get("memo", ""), actor=request.user, request=request)
                messages.success(request, "비용 집행 예정일을 등록했습니다.")
            elif action == "pay":
                paid_date = _parse_date(request.POST.get("paid_date"))
                if paid_date is None:
                    raise ValidationError("실제 지급일을 확인해 주세요.")
                pay_expense_execution(execution=execution, paid_date=paid_date, payment_reference=request.POST.get("payment_reference", ""), memo=request.POST.get("memo", ""), actor=request.user, request=request)
                messages.success(request, "비용 지급 완료로 처리했습니다. 확정 현금흐름에 반영됩니다.")
            elif action == "cancel":
                cancel_expense_execution(execution=execution, memo=request.POST.get("memo", ""), actor=request.user, request=request)
                messages.success(request, "비용 집행 대상을 취소했습니다.")
            else:
                raise ValidationError("처리 방식을 확인해 주세요.")
        except (PermissionDenied, ValidationError) as exc:
            messages.error(request, str(exc))
        return redirect(f"/app/hq/finance/expense-executions/?status={selected_status}")

    executions = ExpenseExecution.objects.select_related(
        "cost_actual__project", "cash_event", "ceo_approved_by", "scheduled_by", "paid_by"
    ).filter(cost_actual__project__legal_entity=legal_entity).order_by("-created_at", "-id")
    if selected_status == "open":
        executions = executions.filter(status__in=[ExpenseExecutionStatus.READY, ExpenseExecutionStatus.SCHEDULED])
    elif selected_status in ExpenseExecutionStatus.values:
        executions = executions.filter(status=selected_status)
    return render(request, "app/hq/expense_execution_list.html", {
        "executions": executions[:100], "selected_status": selected_status,
        "today": today, "legal_entities": get_user_legal_entities(request.user),
        "current_legal_entity": legal_entity,
    })
