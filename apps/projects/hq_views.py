from datetime import timedelta
from decimal import Decimal
import logging

from django.contrib import messages
from django.contrib.auth.decorators import login_required
from django.db import transaction
from django.forms import modelformset_factory
from django.shortcuts import get_object_or_404, redirect, render
from django.utils import timezone

try:
    from apps.audit.constants import (
        ASSIGNMENT_ADD,
        ASSIGNMENT_UPDATE,
        BASELINE_APPROVE,
        BASELINE_SUBMIT,
    )
except ImportError:  # Backward-compat if constants aren't defined.
    ASSIGNMENT_ADD = "ASSIGNMENT_ADD"
    ASSIGNMENT_UPDATE = "ASSIGNMENT_UPDATE"
    BASELINE_APPROVE = "BASELINE_APPROVE"
    BASELINE_SUBMIT = "BASELINE_SUBMIT"
from apps.audit.services.logger import log_action
from apps.core.rbac.models import ProjectAssignment, Role
from apps.core.rbac.permissions import get_user_role, require_role
from apps.core.models import ApprovalRequest, ApprovalStatus
from apps.cost.models import CostItem
from apps.master.models import MasterTemplate, MasterTemplateCategory, MasterTemplateDomain
from apps.master.cbs_policy import evaluate_cbs_selectability
from apps.evidence.models import Evidence, EvidenceFile
from apps.inventory.services import create_site_warehouse

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
    ProjectContractStatus,
    ProjectStatus,
    ProjectType,
    WBSItem,
)
from .services.baseline import is_baseline_locked
from .services.wbs_baseline import (
    get_wbs_baseline_badge,
    get_wbs_baseline_history,
)
from .wbs_change import render_wbs_change_form

logger = logging.getLogger(__name__)


@login_required
def hq_project_list(request):
    require_role(request.user, [Role.HQ, Role.CEO])
    projects = Project.objects.all().order_by("-created_at")
    recent_cutoff = timezone.now() - timedelta(days=1)
    recent_ids = set(
        projects.filter(created_at__gte=recent_cutoff).values_list("id", flat=True)
    )
    return render(
        request,
        "app/hq_projects_list.html",
        {"projects": projects, "recent_ids": recent_ids},
    )


@login_required
def hq_project_new(request):
    require_role(request.user, [Role.HQ])
    BudgetFormSet = modelformset_factory(
        BudgetItem, form=BudgetItemForm, extra=5, can_delete=True
    )
    WBSFormSet = modelformset_factory(
        WBSItem, form=WBSItemForm, extra=0, can_delete=True
    )
    budget_template_notice = ""
    budget_template_warnings = []

    wbs_templates = []
    budget_templates = []
    wbs_template_notice = ""
    budget_template_notice = ""
    selected_wbs_template = None
    selected_budget_template = None
    project_type = ProjectType.LANDSCAPE

    if request.method == "POST":
        project_form = ProjectOnboardingForm(request.POST)
        contract_form = ProjectContractForm(request.POST, request.FILES)
        budget_formset = BudgetFormSet(
            request.POST, queryset=BudgetItem.objects.none(), prefix="budget"
        )
        wbs_formset = WBSFormSet(
            request.POST, queryset=WBSItem.objects.none(), prefix="wbs"
        )
        project_type = project_form.data.get("project_type") or ProjectType.LANDSCAPE
        domain = _project_domain(project_type)
        wbs_templates, wbs_template_notice = _get_templates_with_fallback(
            domain, MasterTemplateCategory.WBS
        )
        budget_templates, budget_template_notice = _get_templates_with_fallback(
            domain, MasterTemplateCategory.BUDGET
        )
        selected_wbs_template = _resolve_template_from_post(
            request.POST.get("wbs_template_id"), wbs_templates
        )
        selected_budget_template = _resolve_template_from_post(
            request.POST.get("budget_template_id"), budget_templates
        )
        if selected_budget_template and not budget_template_notice:
            budget_template_notice = "선택한 예산 템플릿이 자동으로 채워졌습니다. 금액을 입력/수정하세요."

        for form in budget_formset:
            form.fields["cost_item"].queryset = CostItem.objects.all().order_by(
                "sort_order", "name"
            )

        if (
            project_form.is_valid()
            and contract_form.is_valid()
            and budget_formset.is_valid()
            and wbs_formset.is_valid()
        ):
            policy_blocked = _validate_budget_policy(
                budget_formset,
                role=Role.HQ,
                existing_cost_item_ids=set(),
                request=request,
                project=None,
                action="create",
            )
            if policy_blocked:
                messages.error(request, "CBS 선택 정책으로 인해 저장할 수 없습니다.")
                return render(
                    request,
                    "app/hq/project_new.html",
                    {
                        "project_form": project_form,
                        "contract_form": contract_form,
                        "budget_formset": budget_formset,
                        "wbs_formset": wbs_formset,
                        "wbs_template_notice": wbs_template_notice,
                        "budget_template_notice": budget_template_notice,
                        "budget_template_warnings": budget_template_warnings,
                        "wbs_templates": wbs_templates,
                        "budget_templates": budget_templates,
                        "selected_wbs_template": selected_wbs_template,
                        "selected_budget_template": selected_budget_template,
                    },
                )
            budget_items = _collect_budget_items(budget_formset)
            wbs_items, wbs_weight_sum = _collect_wbs_items(wbs_formset)

            if not budget_items:
                messages.error(request, "예산 라인은 1개 이상 입력해야 합니다.")
            elif not wbs_items:
                messages.error(request, "WBS 라인은 1개 이상 입력해야 합니다.")
            elif not _is_weight_sum_valid(wbs_weight_sum):
                messages.error(request, "WBS 가중치 합계는 100%여야 합니다.")
            else:
                with transaction.atomic():
                    project = project_form.save(commit=False)
                    if not project.status:
                        project.status = ProjectStatus.DRAFT
                    if selected_wbs_template:
                        project.wbs_template = selected_wbs_template
                    if selected_budget_template:
                        project.budget_template = selected_budget_template
                    project.save()
                    create_site_warehouse(project, actor=request.user)

                    contract = contract_form.save(commit=False)
                    contract.project = project
                    contract.status = ProjectContractStatus.APPROVED
                    contract.start_date = contract.contract_start_date or project.start_date
                    contract.end_date = contract.contract_end_date or project.end_date
                    contract.save()

                    evidence = Evidence.objects.create(
                        title=f"{project.name} 계약서",
                        description="HQ 신규 공사 계약서",
                        object_type="PROJECT_CONTRACT",
                        object_id=contract.id,
                        created_by=request.user,
                    )
                    contract_file = contract.contract_file
                    EvidenceFile.objects.create(
                        evidence=evidence,
                        file=contract_file,
                        original_name=getattr(contract_file, "name", "contract"),
                        content_type=getattr(contract_file, "content_type", "application/octet-stream"),
                        created_by=request.user,
                    )

                    for item in budget_items:
                        BudgetItem.objects.update_or_create(
                            project=project,
                            cost_item=item["cost_item"],
                            defaults={
                                "category": item["category"],
                                "name": item["name"],
                                "planned_amount": item["planned_amount"],
                                "status": ProjectContractStatus.APPROVED,
                                "note": item["note"],
                            },
                        )
                        _log_budget_cbs_select(
                            request,
                            project,
                            item["cost_item"],
                            action="create",
                        )

                    for idx, item in enumerate(wbs_items, start=1):
                        WBSItem.objects.create(
                            project=project,
                            name=item["name"],
                            weight=item["weight"],
                            sort_order=idx,
                            plan_start_date=item["plan_start_date"],
                            plan_end_date=item["plan_end_date"],
                            baseline_version=1,
                            is_baseline=True,
                        )

                    log_action(
                        actor=request.user,
                        action="PROJECT_CREATE",
                        object_type="PROJECT",
                        object_id=project.id,
                        project=project,
                        request=request,
                    )
                    log_action(
                        actor=request.user,
                        action="CONTRACT_CREATE",
                        object_type="PROJECT_CONTRACT",
                        object_id=contract.id,
                        project=project,
                        request=request,
                    )
                    log_action(
                        actor=request.user,
                        action="CONTRACT_EVIDENCE_ATTACH",
                        object_type="EVIDENCE",
                        object_id=evidence.id,
                        project=project,
                        request=request,
                    )
                    log_action(
                        actor=request.user,
                        action="BUDGET_BASELINE_CREATE",
                        object_type="BUDGET",
                        object_id=project.id,
                        project=project,
                        request=request,
                    )
                    log_action(
                        actor=request.user,
                        action="WBS_BASELINE_CREATE",
                        object_type="WBS",
                        object_id=project.id,
                        project=project,
                        request=request,
                    )

                messages.success(request, "프로젝트가 등록되었습니다.")
                return redirect(f"/app/hq/projects/{project.id}/")
    else:
        project_type = request.GET.get("project_type") or ProjectType.LANDSCAPE
        project_form = ProjectOnboardingForm(
            initial={"status": ProjectStatus.DRAFT, "project_type": project_type}
        )
        contract_form = ProjectContractForm()
        domain = _project_domain(project_type)
        wbs_templates, wbs_template_notice = _get_templates_with_fallback(
            domain, MasterTemplateCategory.WBS
        )
        budget_templates, budget_template_notice = _get_templates_with_fallback(
            domain, MasterTemplateCategory.BUDGET
        )
        selected_wbs_template = _resolve_template_from_post(
            request.GET.get("wbs_template_id"), wbs_templates
        ) or (wbs_templates[0] if wbs_templates else None)
        selected_budget_template = _resolve_template_from_post(
            request.GET.get("budget_template_id"), budget_templates
        ) or (budget_templates[0] if budget_templates else None)
        budget_initial, budget_template_warnings = _build_budget_initial_from_template(
            selected_budget_template
        )
        if budget_initial:
            BudgetFormSet = modelformset_factory(
                BudgetItem, form=BudgetItemForm, extra=len(budget_initial), can_delete=True
            )
            budget_formset = BudgetFormSet(
                queryset=BudgetItem.objects.none(),
                prefix="budget",
                initial=budget_initial,
            )
            if not budget_template_notice:
                budget_template_notice = (
                    "선택한 예산 템플릿이 자동으로 채워졌습니다. 금액을 입력/수정하세요."
                )
        else:
            budget_formset = BudgetFormSet(
                queryset=BudgetItem.objects.none(),
                prefix="budget",
            )
        wbs_initial, wbs_items_notice = _build_wbs_initial_from_template(
            selected_wbs_template, project_type
        )
        if wbs_items_notice:
            wbs_template_notice = (
                f"{wbs_template_notice} {wbs_items_notice}".strip()
                if wbs_template_notice
                else wbs_items_notice
            )
        elif selected_wbs_template and not wbs_template_notice:
            wbs_template_notice = "선택한 WBS 템플릿이 자동으로 채워졌습니다. 필요 시 수정하세요."
        if wbs_initial:
            WBSFormSet = modelformset_factory(
                WBSItem, form=WBSItemForm, extra=len(wbs_initial), can_delete=True
            )
            wbs_formset = WBSFormSet(
                queryset=WBSItem.objects.none(),
                prefix="wbs",
                initial=wbs_initial,
            )
        else:
            WBSFormSet = modelformset_factory(
                WBSItem, form=WBSItemForm, extra=4, can_delete=True
            )
            wbs_formset = WBSFormSet(
                queryset=WBSItem.objects.none(),
                prefix="wbs",
            )
        for form in budget_formset:
            form.fields["cost_item"].queryset = CostItem.objects.all().order_by(
                "sort_order", "name"
            )

    return render(
        request,
        "app/hq/project_new.html",
        {
        "project_form": project_form,
        "contract_form": contract_form,
        "budget_formset": budget_formset,
        "wbs_formset": wbs_formset,
        "wbs_template_notice": wbs_template_notice,
        "budget_template_notice": budget_template_notice,
        "budget_template_warnings": budget_template_warnings,
        "wbs_templates": wbs_templates,
        "budget_templates": budget_templates,
        "selected_wbs_template": selected_wbs_template,
        "selected_budget_template": selected_budget_template,
    },
    )


def _default_wbs_rows(project_type):
    template = [
        ("착공 준비/가설", Decimal("5")),
        ("현장 정리/가설 울타리", Decimal("5")),
        ("토공/기초 정지(성토·절토)", Decimal("12")),
        ("배수/관수 기반(배관·맨홀)", Decimal("10")),
        ("경계석/보도블록/포장", Decimal("10")),
        ("옹벽/계단/경사면 정리", Decimal("8")),
        ("식재 기반토/토양개량", Decimal("8")),
        ("교목 식재", Decimal("12")),
        ("관목·초화류 식재", Decimal("10")),
        ("잔디/지피 식재", Decimal("8")),
        ("시설물(벤치·휀스·조명 등)", Decimal("7")),
        ("마감/정리/준공서류", Decimal("5")),
    ]
    return [
        {
            "name": name,
            "weight": weight,
            "sort_order": idx + 1,
        }
        for idx, (name, weight) in enumerate(template)
    ]


def _project_domain(project_type):
    mapping = {
        ProjectType.LANDSCAPE: MasterTemplateDomain.LANDSCAPE,
        ProjectType.CIVIL: MasterTemplateDomain.CIVIL,
        ProjectType.ARCH: MasterTemplateDomain.BUILDING,
    }
    return mapping.get(project_type, MasterTemplateDomain.LANDSCAPE)


def _get_active_templates(domain, category):
    return list(
        MasterTemplate.objects.filter(domain=domain, category=category, is_active=True)
        .order_by("-version", "id")
    )


def _get_templates_with_fallback(domain, category):
    templates = _get_active_templates(domain, category)
    if templates:
        return templates, ""
    if domain != MasterTemplateDomain.LANDSCAPE:
        fallback = _get_active_templates(MasterTemplateDomain.LANDSCAPE, category)
        if fallback:
            return (
                fallback,
                "현재는 조경 기본 템플릿이 적용되었습니다. 필요 시 수정하세요.",
            )
    return [], "템플릿이 없어 기본 입력 행으로 표시됩니다."


def _resolve_template_from_post(template_id, templates):
    if not template_id:
        return None
    for template in templates:
        if str(template.id) == str(template_id):
            return template
    return None


def _build_wbs_initial_from_template(template, project_type):
    if not template:
        return _default_wbs_rows(project_type), ""
    items = list(template.wbs_items.all().order_by("order", "id"))
    if not items:
        return (
            _default_wbs_rows(project_type),
            "선택한 WBS 템플릿에 항목이 없어 기본 템플릿을 적용했습니다.",
        )
    rows = []
    for item in items:
        rows.append(
            {
                "name": item.task_name,
                "weight": item.weight,
                "sort_order": item.order,
            }
        )
    return rows, ""


def _build_budget_initial_from_template(template):
    if not template:
        return _default_landscape_budget_rows()
    rows = []
    warnings = []
    for item in template.budget_items.all().order_by("order", "id"):
        row = {"note": item.label}
        if item.cost_item_id:
            policy = evaluate_cbs_selectability(
                item.cost_item,
                Role.HQ,
                "BUDGET",
                is_existing_usage=False,
            )
            if policy.selectable:
                row["cost_item"] = item.cost_item_id
                row["name"] = item.cost_item.get_display_name()
                if policy.severity == "WARN":
                    warnings.append(f"{item.label}: {policy.message}")
            else:
                warnings.append(f"{item.label}: {policy.message}")
        else:
            warnings.append(f"CBS 자동 매칭 실패: {item.label}")
        rows.append(row)
    return rows, warnings


def _validate_budget_policy(formset, role, *, existing_cost_item_ids, request, project, action):
    blocked = False
    for form in formset:
        if not form.cleaned_data:
            continue
        if form.cleaned_data.get("DELETE"):
            continue
        cost_item = form.cleaned_data.get("cost_item")
        if not cost_item:
            continue
        is_existing = (
            form.instance.pk
            and form.instance.cost_item_id == cost_item.id
            and cost_item.id in existing_cost_item_ids
        )
        policy = evaluate_cbs_selectability(
            cost_item,
            role,
            "BUDGET",
            is_existing_usage=is_existing,
        )
        if not policy.selectable:
            form.add_error("cost_item", policy.message)
            blocked = True
            _log_budget_cbs_blocked(
                request,
                project,
                cost_item,
                policy,
                action=action,
            )
    return blocked


def _log_budget_cbs_select(request, project, cost_item, *, action, is_existing_usage=False):
    policy = evaluate_cbs_selectability(
        cost_item,
        Role.HQ,
        "BUDGET",
        is_existing_usage=is_existing_usage,
    )
    meta = {
        "project_id": getattr(project, "id", None),
        "cost_item_id": cost_item.id,
        "active": policy.active,
        "locked": policy.locked,
        "pending_change": policy.pending,
        "actor_role": Role.HQ,
        "action": action,
        "severity": policy.severity,
    }
    try:
        log_action(
            actor=request.user,
            action="BUDGET_CBS_SELECT",
            object_type="BUDGET_ITEM",
            object_id=cost_item.id,
            project=project,
            meta=meta,
            request=request,
        )
    except Exception:
        logger.warning("AuditLog failed for BUDGET_CBS_SELECT.", exc_info=True)


def _log_budget_cbs_blocked(request, project, cost_item, policy, *, action):
    meta = {
        "project_id": getattr(project, "id", None),
        "cost_item_id": cost_item.id,
        "active": policy.active,
        "locked": policy.locked,
        "pending_change": policy.pending,
        "actor_role": Role.HQ,
        "action": action,
        "severity": policy.severity,
        "reason_code": policy.reason_code,
    }
    try:
        log_action(
            actor=request.user,
            action="BUDGET_CBS_BLOCKED",
            object_type="BUDGET_ITEM",
            object_id=cost_item.id,
            project=project,
            meta=meta,
            request=request,
        )
    except Exception:
        logger.warning("AuditLog failed for BUDGET_CBS_BLOCKED.", exc_info=True)


def _collect_budget_items(formset):
    items_by_cost_item = {}
    for form in formset:
        if not form.cleaned_data:
            continue
        if form.cleaned_data.get("DELETE"):
            continue
        cost_item = form.cleaned_data.get("cost_item")
        planned_amount = form.cleaned_data.get("planned_amount")
        if not cost_item or planned_amount in (None, ""):
            continue
        key = cost_item.id
        amount_value = int(planned_amount)
        name_value = form.cleaned_data.get("name") or cost_item.name
        note_value = form.cleaned_data.get("note") or ""
        if key not in items_by_cost_item:
            items_by_cost_item[key] = {
                "cost_item": cost_item,
                "category": form.cleaned_data.get("category"),
                "name": name_value,
                "planned_amount": amount_value,
                "note": note_value,
            }
        else:
            items_by_cost_item[key]["planned_amount"] += amount_value
            if note_value and note_value not in items_by_cost_item[key]["note"]:
                if items_by_cost_item[key]["note"]:
                    items_by_cost_item[key]["note"] += "; " + note_value
                else:
                    items_by_cost_item[key]["note"] = note_value
    return list(items_by_cost_item.values())


def _default_landscape_budget_rows():
    template = [
        ("착공/가설/안전시설", ["가설", "안전", "울타리"]),
        ("현장정리/폐기물 처리", ["현장정리", "폐기물", "반출"]),
        ("토공(정지/성토/절토)", ["토공", "정지", "성토", "절토"]),
        ("배수/관수 배관", ["배수", "관수", "배관", "맨홀"]),
        ("경계석/블록/포장", ["경계석", "보도블록", "포장"]),
        ("경사면/옹벽/계단", ["옹벽", "계단", "경사면"]),
        ("토양개량/식재기반토", ["토양개량", "식재기반", "상토"]),
        ("교목(수목)", ["교목", "수목", "수목식재"]),
        ("관목", ["관목", "관목식재"]),
        ("초화류/지피", ["초화", "지피", "초화류"]),
        ("잔디", ["잔디", "잔디식재"]),
        ("비료/멀칭/지주/보호재", ["비료", "멀칭", "지주", "보호재"]),
        ("시설물(벤치/휀스/데크 등)", ["벤치", "휀스", "데크", "시설물"]),
        ("조명/전기", ["조명", "전기", "분전"]),
        ("인건비-현장관리/작업자", ["인건비", "노무", "작업자", "현장관리"]),
        ("준공/정리/서류", ["준공", "정리", "서류"]),
    ]
    items = list(CostItem.objects.all().values("id", "name", "is_active"))
    rows = []
    warnings = []
    for label, keywords in template:
        matches = [
            item for item in items if any(keyword in item["name"] for keyword in keywords)
        ]
        matches_active = [item for item in matches if item.get("is_active")]
        pick = None
        if matches_active:
            pick = sorted(matches_active, key=lambda x: len(x["name"]))[0]
        elif matches:
            pick = sorted(matches, key=lambda x: len(x["name"]))[0]
        row = {"note": label}
        if pick:
            row["cost_item"] = pick["id"]
        else:
            warnings.append(f"CBS 자동 매칭 실패: {label}")
        rows.append(row)
    return rows, warnings


def _collect_wbs_items(formset):
    items = []
    weight_sum = Decimal("0")
    for form in formset:
        if not form.cleaned_data:
            continue
        if form.cleaned_data.get("DELETE"):
            continue
        name = (form.cleaned_data.get("name") or "").strip()
        if not name:
            continue
        weight = form.cleaned_data.get("weight") or Decimal("0")
        weight_sum += Decimal(weight)
        items.append(
            {
                "name": name,
                "weight": weight,
                "plan_start_date": form.cleaned_data.get("plan_start_date"),
                "plan_end_date": form.cleaned_data.get("plan_end_date"),
            }
        )
    return items, weight_sum


def _is_weight_sum_valid(total):
    return abs(Decimal("100") - Decimal(total)) <= Decimal("0.1")


def hq_project_detail(request, project_id):
    require_role(request.user, [Role.HQ, Role.CEO])
    project = get_object_or_404(Project, id=project_id)
    contract = ProjectContract.objects.filter(project=project).first()
    role = get_user_role(request.user)

    role_filter = request.GET.get("role") or ""
    assignments = (
        ProjectAssignment.objects.filter(project=project)
        .select_related("user")
        .order_by("-is_active", "user__username")
    )
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
    wbs_badge = get_wbs_baseline_badge(project)
    wbs_history = get_wbs_baseline_history(project)
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
                messages.error(request, "?쒖텧???꾨줈?앺듃???ㅼ떆 ?쒖텧?????놁뒿?덈떎.")
                return redirect(f"/app/hq/projects/{project.id}/")
            if contract is None or not contract.contract_file:
                messages.error(request, "怨꾩빟 ?뚯씪??泥⑤???二쇱꽭??")
                return redirect(f"/app/hq/projects/{project.id}/")
            if contract.contract_amount is None or contract.contract_amount <= 0:
                messages.error(request, "怨꾩빟 湲덉븸? 0蹂대떎 而ㅼ빞 ?⑸땲??")
                return redirect(f"/app/hq/projects/{project.id}/")
            if project.start_date and project.end_date and project.start_date > project.end_date:
                messages.error(request, "?쒖옉?쇱? 醫낅즺?쇰낫????쓣 ???놁뒿?덈떎.")
                return redirect(f"/app/hq/projects/{project.id}/")
            if not WBSItem.objects.filter(project=project).exists():
                messages.warning(request, "WBS媛 ?놁뒿?덈떎. 沅뚯옣 ??ぉ?낅땲??")
            if not BudgetItem.objects.filter(project=project).exists():
                messages.warning(request, "?덉궛 ??ぉ???놁뒿?덈떎. 沅뚯옣 ??ぉ?낅땲??")
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
            messages.success(request, "?꾨줈?앺듃媛 ?쒖텧?섏뿀?듬땲??")
            return redirect(f"/app/hq/projects/{project.id}/")
        if action == "approve_baseline":
            if role != Role.CEO:
                messages.error(request, "CEO留??뱀씤?????덉뒿?덈떎.")
                return redirect(f"/app/hq/projects/{project.id}/")
            if project.status != ProjectStatus.SUBMITTED:
                messages.error(request, "?쒖텧???꾨줈?앺듃留??뱀씤?????덉뒿?덈떎.")
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
            messages.success(request, "?꾨줈?앺듃媛 ?뱀씤?섏뿀?듬땲??")
            return redirect(f"/app/hq/projects/{project.id}/")
        if action == "add_assignment":
            if wbs_locked:
                messages.error(request, "?쒖텧 ?댄썑?먮뒗 諛곗젙???섏젙?????놁뒿?덈떎.")
                return redirect(f"/app/hq/projects/{project.id}/")
            assignment_form = ProjectAssignmentForm(request.POST)
            if assignment_form.is_valid():
                user = assignment_form.cleaned_data["user"]
                is_active = assignment_form.cleaned_data["is_active"]
                assignment, created = ProjectAssignment.objects.get_or_create(
                    project=project,
                    user=user,
                    defaults={"is_active": is_active},
                )
                before = None
                audit_action = ASSIGNMENT_ADD
                if not created:
                    before = {
                        "is_active": assignment.is_active,
                    }
                    assignment.is_active = is_active
                    assignment.save(update_fields=["is_active"])
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
                        "is_active": assignment.is_active,
                    },
                )
                messages.success(request, "諛곗젙????λ릺?덉뒿?덈떎.")
                return redirect(f"/app/hq/projects/{project.id}/")
            messages.error(request, "諛곗젙 ?뺣낫瑜??뺤씤??二쇱꽭??")
        elif action == "toggle_assignment":
            if wbs_locked:
                messages.error(request, "?쒖텧 ?댄썑?먮뒗 諛곗젙???섏젙?????놁뒿?덈떎.")
                return redirect(f"/app/hq/projects/{project.id}/")
            assignment_id = request.POST.get("assignment_id")
            assignment = get_object_or_404(
                ProjectAssignment, id=assignment_id, project=project
            )
            before = {
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
                    "is_active": assignment.is_active,
                },
            )
            messages.success(request, "諛곗젙 ?곹깭媛 蹂寃쎈릺?덉뒿?덈떎.")
            return redirect(f"/app/hq/projects/{project.id}/")
        elif action == "save_budget":
            if wbs_locked:
                messages.error(request, "?쒖텧 ?댄썑 ?덉궛? ?섏젙?????놁뒿?덈떎.")
                return redirect(f"/app/hq/projects/{project.id}/")
            budget_formset = BudgetFormSet(
                request.POST, queryset=budget_qs, prefix="budget"
            )
            labor_formset = LaborFormSet(
                request.POST, queryset=labor_qs, prefix="labor"
            )
            if budget_formset.is_valid() and labor_formset.is_valid():
                existing_cost_item_ids = set(
                    budget_qs.values_list("cost_item_id", flat=True)
                ) | set(labor_qs.values_list("cost_item_id", flat=True))
                policy_blocked = _validate_budget_policy(
                    budget_formset,
                    role=Role.HQ,
                    existing_cost_item_ids=existing_cost_item_ids,
                    request=request,
                    project=project,
                    action="update",
                )
                policy_blocked = _validate_budget_policy(
                    labor_formset,
                    role=Role.HQ,
                    existing_cost_item_ids=existing_cost_item_ids,
                    request=request,
                    project=project,
                    action="update",
                ) or policy_blocked
                if policy_blocked:
                    messages.error(request, "CBS ?? ???? ?? ??? ? ????.")
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
                            "wbs_badge": wbs_badge,
                            "wbs_history": wbs_history,
                            "wbs_locked": wbs_locked,
                            "role": role,
                            "now": timezone.localdate(),
                        },
                    )
                for form in budget_formset:
                    if form.cleaned_data.get("DELETE"):
                        if form.instance.pk:
                            form.instance.delete()
                        continue
                    item = form.save(commit=False)
                    item.project = project
                    item.save()
                    is_existing_usage = (
                        form.instance.pk
                        and form.instance.cost_item_id == item.cost_item_id
                        and item.cost_item_id in existing_cost_item_ids
                    )
                    _log_budget_cbs_select(
                        request,
                        project,
                        item.cost_item,
                        action="update",
                        is_existing_usage=is_existing_usage,
                    )
                for form in labor_formset:
                    if form.cleaned_data.get("DELETE"):
                        if form.instance.pk:
                            form.instance.delete()
                        continue
                    item = form.save(commit=False)
                    item.project = project
                    item.category = BudgetCategory.LABOR
                    item.save()
                    is_existing_usage = (
                        form.instance.pk
                        and form.instance.cost_item_id == item.cost_item_id
                        and item.cost_item_id in existing_cost_item_ids
                    )
                    _log_budget_cbs_select(
                        request,
                        project,
                        item.cost_item,
                        action="update",
                        is_existing_usage=is_existing_usage,
                    )
                messages.success(request, "??? ???????.")
                return redirect(f"/app/hq/projects/{project.id}/")
                messages.error(request, "?? ?? ?? ??? ???.")
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
                messages.success(request, "WBS媛 ??λ릺?덉뒿?덈떎.")
                return redirect(f"/app/hq/projects/{project.id}/")
            messages.error(request, "WBS ?낅젰 媛믪쓣 ?뺤씤??二쇱꽭??")

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
        "wbs_badge": wbs_badge,
        "wbs_history": wbs_history,
        "wbs_locked": wbs_locked,
        "role": role,
        "now": timezone.localdate(),
    },
)


@login_required
def hq_wbs_change_new(request, project_id):
    require_role(request.user, [Role.HQ])
    project = get_object_or_404(Project, id=project_id)
    role = get_user_role(request.user)
    return render_wbs_change_form(
        request,
        project,
        role,
        template_name="app/common/wbs_change_form.html",
        back_url=f"/app/hq/projects/{project.id}/",
    )

