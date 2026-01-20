from django.contrib import messages
from django.contrib.auth.decorators import login_required
from django.forms import modelformset_factory
from django.shortcuts import get_object_or_404, redirect, render
from django.utils import timezone

from apps.audit.constants import (
    ASSIGNMENT_ADD,
    ASSIGNMENT_UPDATE,
    BASELINE_APPROVE,
    BASELINE_SUBMIT,
)
from apps.audit.services.logger import log_action
from apps.core.rbac.models import ProjectAssignment, Role
from apps.core.rbac.permissions import get_user_role, require_role
from apps.core.models import ApprovalRequest, ApprovalStatus

from .forms import (
    BudgetItemForm,
    LaborBudgetItemForm,
    ProjectAssignmentForm,
    ProjectContractForm,
    ProjectOnboardingForm,
    WBSItemForm,
)
from .models import (
    BudgetCategory,
    BudgetItem,
    Project,
    ProjectContract,
    ProjectStatus,
    WBSItem,
)
from .services.baseline import is_baseline_locked


@login_required
def hq_project_list(request):
    require_role(request.user, [Role.HQ, Role.CEO])
    projects = Project.objects.all().order_by("-created_at")
    return render(request, "app/hq_projects_list.html", {"projects": projects})


@login_required
def hq_project_new(request):
    require_role(request.user, [Role.HQ, Role.CEO])
    if request.method == "POST":
        project_form = ProjectOnboardingForm(request.POST)
        contract_form = ProjectContractForm(request.POST, request.FILES)
        if project_form.is_valid() and contract_form.is_valid():
            project = project_form.save(commit=False)
            if not project.status:
                project.status = ProjectStatus.DRAFT
            project.save()
            contract = contract_form.save(commit=False)
            contract.project = project
            contract.save()
            messages.success(request, "프로젝트가 임시저장되었습니다.")
            return redirect(f"/app/hq/projects/{project.id}/")
    else:
        project_form = ProjectOnboardingForm(initial={"status": ProjectStatus.DRAFT})
        contract_form = ProjectContractForm()
    return render(
        request,
        "app/hq_project_form.html",
        {"project_form": project_form, "contract_form": contract_form},
    )


@login_required
def hq_project_detail(request, project_id):
    require_role(request.user, [Role.HQ, Role.CEO])
    project = get_object_or_404(Project, id=project_id)
    contract = ProjectContract.objects.filter(project=project).first()
    role = get_user_role(request.user)

    role_filter = request.GET.get("role") or ""
    assignments_qs = ProjectAssignment.objects.filter(project=project).select_related(
        "user"
    )
    if role_filter:
        assignments_qs = assignments_qs.filter(role_in_project=role_filter)
    assignments = assignments_qs.order_by("-is_active", "user__username")
    assignment_form = ProjectAssignmentForm(initial={"is_active": True})

    BudgetFormSet = modelformset_factory(
        BudgetItem, form=BudgetItemForm, extra=3, can_delete=True
    )
    LaborFormSet = modelformset_factory(
        BudgetItem, form=LaborBudgetItemForm, extra=2, can_delete=True
    )
    budget_qs = BudgetItem.objects.filter(project=project).exclude(
        category=BudgetCategory.LABOR
    )
    labor_qs = BudgetItem.objects.filter(
        project=project, category=BudgetCategory.LABOR
    )
    budget_formset = BudgetFormSet(queryset=budget_qs, prefix="budget")
    labor_formset = LaborFormSet(queryset=labor_qs, prefix="labor")
    WBSFormSet = modelformset_factory(
        WBSItem, form=WBSItemForm, extra=4, can_delete=True
    )
    wbs_qs = WBSItem.objects.filter(project=project)
    wbs_formset = WBSFormSet(queryset=wbs_qs, prefix="wbs")
    for form in wbs_formset:
        form.fields["parent"].queryset = wbs_qs
    wbs_locked = is_baseline_locked(project)
    if wbs_locked:
        for form in wbs_formset:
            for field in form.fields.values():
                field.disabled = True
        for form in budget_formset:
            for field in form.fields.values():
                field.disabled = True
        for form in labor_formset:
            for field in form.fields.values():
                field.disabled = True
        for field in assignment_form.fields.values():
            field.disabled = True

    if request.method == "POST":
        action = request.POST.get("action")
        if action == "submit_baseline":
            if project.status != ProjectStatus.DRAFT:
                messages.error(request, "제출된 프로젝트는 다시 제출할 수 없습니다.")
                return redirect(f"/app/hq/projects/{project.id}/")
            if contract is None or not contract.contract_file:
                messages.error(request, "계약 파일을 첨부해 주세요.")
                return redirect(f"/app/hq/projects/{project.id}/")
            if contract.contract_amount is None or contract.contract_amount <= 0:
                messages.error(request, "계약 금액은 0보다 커야 합니다.")
                return redirect(f"/app/hq/projects/{project.id}/")
            if project.start_date and project.end_date and project.start_date > project.end_date:
                messages.error(request, "시작일은 종료일보다 늦을 수 없습니다.")
                return redirect(f"/app/hq/projects/{project.id}/")
            if not WBSItem.objects.filter(project=project).exists():
                messages.warning(request, "WBS가 없습니다. 권장 항목입니다.")
            if not BudgetItem.objects.filter(project=project).exists():
                messages.warning(request, "예산 항목이 없습니다. 권장 항목입니다.")
            project.status = ProjectStatus.SUBMITTED
            project.save(update_fields=["status", "updated_at"])
            ApprovalRequest.objects.update_or_create(
                object_type="PROJECT_BASELINE",
                object_id=project.id,
                defaults={
                    "status": ApprovalStatus.SUBMITTED,
                    "submitted_by": request.user,
                    "submitted_at": timezone.now(),
                },
            )
            log_action(
                actor=request.user,
                action=BASELINE_SUBMIT,
                object_type="PROJECT",
                object_id=project.id,
                project=project,
                request=request,
                after={"status": project.status},
            )
            messages.success(request, "프로젝트가 제출되었습니다.")
            return redirect(f"/app/hq/projects/{project.id}/")
        if action == "approve_baseline":
            if role != Role.CEO:
                messages.error(request, "CEO만 승인할 수 있습니다.")
                return redirect(f"/app/hq/projects/{project.id}/")
            if project.status != ProjectStatus.SUBMITTED:
                messages.error(request, "제출된 프로젝트만 승인할 수 있습니다.")
                return redirect(f"/app/hq/projects/{project.id}/")
            project.status = ProjectStatus.APPROVED
            project.save(update_fields=["status", "updated_at"])
            ApprovalRequest.objects.update_or_create(
                object_type="PROJECT_BASELINE",
                object_id=project.id,
                defaults={
                    "status": ApprovalStatus.APPROVED,
                    "approved_by": request.user,
                    "approved_at": timezone.now(),
                },
            )
            log_action(
                actor=request.user,
                action=BASELINE_APPROVE,
                object_type="PROJECT",
                object_id=project.id,
                project=project,
                request=request,
                after={"status": project.status},
            )
            messages.success(request, "프로젝트가 승인되었습니다.")
            return redirect(f"/app/hq/projects/{project.id}/")
        if action == "add_assignment":
            if wbs_locked:
                messages.error(request, "제출 이후에는 배정을 수정할 수 없습니다.")
                return redirect(f"/app/hq/projects/{project.id}/")
            assignment_form = ProjectAssignmentForm(request.POST)
            if assignment_form.is_valid():
                user = assignment_form.cleaned_data["user"]
                role_in_project = assignment_form.cleaned_data["role_in_project"]
                is_active = assignment_form.cleaned_data["is_active"]
                assignment, created = ProjectAssignment.objects.get_or_create(
                    project=project,
                    user=user,
                    defaults={
                        "role_in_project": role_in_project,
                        "is_active": is_active,
                    },
                )
                before = None
                audit_action = ASSIGNMENT_ADD
                if not created:
                    before = {
                        "role_in_project": assignment.role_in_project,
                        "is_active": assignment.is_active,
                    }
                    assignment.role_in_project = role_in_project
                    assignment.is_active = is_active
                    assignment.save(update_fields=["role_in_project", "is_active"])
                    audit_action = ASSIGNMENT_UPDATE
                log_action(
                    actor=request.user,
                    action=audit_action,
                    object_type="PROJECT_ASSIGNMENT",
                    object_id=assignment.id,
                    project=project,
                    request=request,
                    before=before,
                    after={
                        "user_id": user.id,
                        "role_in_project": assignment.role_in_project,
                        "is_active": assignment.is_active,
                    },
                )
                messages.success(request, "배정이 저장되었습니다.")
                return redirect(f"/app/hq/projects/{project.id}/")
            messages.error(request, "배정 정보를 확인해 주세요.")
        elif action == "toggle_assignment":
            if wbs_locked:
                messages.error(request, "제출 이후에는 배정을 수정할 수 없습니다.")
                return redirect(f"/app/hq/projects/{project.id}/")
            assignment_id = request.POST.get("assignment_id")
            assignment = get_object_or_404(
                ProjectAssignment, id=assignment_id, project=project
            )
            before = {
                "role_in_project": assignment.role_in_project,
                "is_active": assignment.is_active,
            }
            assignment.is_active = not assignment.is_active
            assignment.save(update_fields=["is_active"])
            log_action(
                actor=request.user,
                action=ASSIGNMENT_UPDATE,
                object_type="PROJECT_ASSIGNMENT",
                object_id=assignment.id,
                project=project,
                request=request,
                before=before,
                after={
                    "user_id": assignment.user_id,
                    "role_in_project": assignment.role_in_project,
                    "is_active": assignment.is_active,
                },
            )
            messages.success(request, "배정 상태가 변경되었습니다.")
            return redirect(f"/app/hq/projects/{project.id}/")
        elif action == "save_budget":
            if wbs_locked:
                messages.error(request, "제출 이후 예산은 수정할 수 없습니다.")
                return redirect(f"/app/hq/projects/{project.id}/")
            budget_formset = BudgetFormSet(
                request.POST, queryset=budget_qs, prefix="budget"
            )
            labor_formset = LaborFormSet(
                request.POST, queryset=labor_qs, prefix="labor"
            )
            if budget_formset.is_valid() and labor_formset.is_valid():
                for form in budget_formset:
                    if form.cleaned_data.get("DELETE"):
                        if form.instance.pk:
                            form.instance.delete()
                        continue
                    item = form.save(commit=False)
                    item.project = project
                    item.save()
                for form in labor_formset:
                    if form.cleaned_data.get("DELETE"):
                        if form.instance.pk:
                            form.instance.delete()
                        continue
                    item = form.save(commit=False)
                    item.project = project
                    item.category = BudgetCategory.LABOR
                    item.save()
                messages.success(request, "예산이 저장되었습니다.")
                return redirect(f"/app/hq/projects/{project.id}/")
                messages.error(request, "예산 입력 값을 확인해 주세요.")
        elif action == "save_wbs":
            if wbs_locked:
                messages.error(request, "제출 이후 WBS는 수정할 수 없습니다.")
                return redirect(f"/app/hq/projects/{project.id}/")
            wbs_formset = WBSFormSet(request.POST, queryset=wbs_qs, prefix="wbs")
            if wbs_formset.is_valid():
                for form in wbs_formset:
                    if form.cleaned_data.get("DELETE"):
                        if form.instance.pk:
                            form.instance.delete()
                        continue
                    item = form.save(commit=False)
                    item.project = project
                    item.save()
                messages.success(request, "WBS가 저장되었습니다.")
                return redirect(f"/app/hq/projects/{project.id}/")
            messages.error(request, "WBS 입력 값을 확인해 주세요.")

    return render(
        request,
        "app/hq_project_detail.html",
        {
            "project": project,
            "contract": contract,
            "assignments": assignments,
            "assignment_form": assignment_form,
            "role_filter": role_filter,
            "budget_formset": budget_formset,
            "labor_formset": labor_formset,
            "wbs_formset": wbs_formset,
            "wbs_locked": wbs_locked,
            "role": role,
            "now": timezone.localdate(),
        },
    )
