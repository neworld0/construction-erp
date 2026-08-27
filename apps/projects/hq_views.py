from collections import Counter
from datetime import timedelta
from decimal import Decimal, ROUND_HALF_UP
import logging
from pathlib import Path
import re
import unicodedata
import uuid

from django.conf import settings
from django.contrib import messages
from django.contrib.auth.decorators import login_required
from django.core.exceptions import ValidationError
from django.core.files import File
from django.core.files.uploadedfile import SimpleUploadedFile
from django.db import IntegrityError, transaction
from django.db.models import Sum
from django.forms import modelformset_factory
from django.shortcuts import get_object_or_404, redirect, render
from django.utils.datastructures import MultiValueDict
from django.utils import timezone
from django.utils.dateparse import parse_date
from django.utils.text import get_valid_filename

try:
    from apps.audit.constants import (
        ASSIGNMENT_ADD,
        ASSIGNMENT_UPDATE,
        BASELINE_APPROVE,
        BASELINE_REJECT,
        BASELINE_SUBMIT,
    )
except ImportError:  # Backward-compat if constants aren't defined.
    ASSIGNMENT_ADD = "ASSIGNMENT_ADD"
    ASSIGNMENT_UPDATE = "ASSIGNMENT_UPDATE"
    BASELINE_APPROVE = "BASELINE_APPROVE"
    BASELINE_REJECT = "BASELINE_REJECT"
    BASELINE_SUBMIT = "BASELINE_SUBMIT"
from apps.audit.services.logger import log_action
from apps.core.rbac.models import ProjectAssignment, Role
from apps.core.rbac.permissions import get_current_legal_entity, get_user_legal_entities, get_user_role, require_project_access, require_role
from apps.core.models import ApprovalRequest, ApprovalStatus
from apps.cost.models import CostItem, CostItemAlias
from apps.master.models import MasterTemplate, MasterTemplateCategory, MasterTemplateDomain
from apps.master.cbs_policy import evaluate_cbs_selectability
from apps.evidence.models import Evidence, EvidenceFile
from apps.inventory.services import create_site_warehouse

from .forms import (
    BUDGET_BASELINE_CATEGORY_LABELS,
    BUDGET_BASELINE_CATEGORY_CHOICES,
    BudgetItemForm,
    LaborBudgetItemForm,
    ProjectAssignmentForm,
    ProjectContractForm,
    ProjectOnboardingForm,
    WBSItemForm,
)
from .excel_import import parse_budget_workbook, parse_wbs_workbook
from .models import (
    BudgetCategory,
    BudgetItem,
    Project,
    ProjectContract,
    ProjectContractStatus,
    ProjectOperationalTestDateWindow,
    ProjectCodeSequence,
    ProjectStatus,
    ProjectType,
    WBSItem,
)
from .services.baseline import get_project_baseline_workflow, is_baseline_locked
from .services.wbs_baseline import (
    get_wbs_baseline_badge,
    get_wbs_baseline_history,
)
from .wbs_change import render_wbs_change_form

logger = logging.getLogger(__name__)

PROJECT_NEW_UPLOAD_SESSION_KEY = "project_new_temp_uploads"
PROJECT_NEW_UPLOAD_FIELDS = (
    "contract_file",
    "budget_excel",
    "commencement_excel",
)
PROJECT_NEW_PREVIEW_ACTIONS = {
    "preview_import",
    "parse_all",
    "apply_budget_cbs_mapping",
    "apply_budget_review_adjustments",
}
CONTRACT_BUDGET_IMPORT_MODE = "WORK_ITEM_BUCKET"
BUDGET_IMPORT_REVIEW_MODE = "SOURCE_ROW_BUCKET"
BUDGET_IMPORT_SAVE_MODE = "SOURCE_ROW_BUCKET"
BUDGET_BUCKET_LABOR = "LABOR"
BUDGET_BUCKET_MATERIAL = "MATERIAL"
BUDGET_BUCKET_EXPENSE = "EXPENSE"
BUDGET_BUCKET_LABELS = {
    BUDGET_BUCKET_LABOR: "노무비",
    BUDGET_BUCKET_MATERIAL: "재료비",
    BUDGET_BUCKET_EXPENSE: "경비",
}
PROFIT_MANUAL_MAPPING_WARNING = (
    "이윤은 수동 매핑 및 금액 확인이 필요합니다. "
    "이윤은 도급금액 조정 항목이므로 경비 합계 대사에는 미반영 수동대기 금액으로 표시됩니다."
)
BUDGET_BUCKET_AMOUNT_FIELDS = {
    BUDGET_BUCKET_LABOR: "labor_amount",
    BUDGET_BUCKET_MATERIAL: "material_amount",
    BUDGET_BUCKET_EXPENSE: "expense_amount",
}
BUDGET_BUCKET_CATEGORIES = {
    BUDGET_BUCKET_LABOR: BudgetCategory.LABOR,
    BUDGET_BUCKET_MATERIAL: BudgetCategory.MATERIAL,
    BUDGET_BUCKET_EXPENSE: BudgetCategory.OTHER,
}


def resolve_wbs_sort_order(wbs_code, row_index, provided_sort_order=None):
    """Resolve WBS ordering without requiring HQ users to enter a technical field."""
    if provided_sort_order not in (None, ""):
        return int(provided_sort_order)

    match = re.search(r"\bWBS\s*[-_]\s*(\d+)\b", str(wbs_code or ""), re.IGNORECASE)
    if match:
        return int(match.group(1)) * 10
    return int(row_index) * 10


def _generate_project_code(legal_entity, project_type: str) -> str:
    year = timezone.localdate().year
    type_prefix_map = {
        ProjectType.LANDSCAPE: "LAND",
        ProjectType.CIVIL: "CIV",
        ProjectType.ARCH: "ARCH",
    }
    prefix = type_prefix_map.get(project_type, "P")
    sequence, _ = ProjectCodeSequence.objects.select_for_update().get_or_create(
        legal_entity=legal_entity,
        project_type=project_type,
        year=year,
        defaults={"last_number": 0},
    )
    sequence.last_number += 1
    sequence.save(update_fields=["last_number"])
    return f"{legal_entity.code}-{prefix}-{year}-{sequence.last_number:03d}"


@login_required
def hq_project_list(request):
    require_role(request.user, [Role.HQ, Role.CEO])
    legal_entity = get_current_legal_entity(request)
    if legal_entity is None:
        projects_qs = Project.objects.none()
    else:
        projects_qs = Project.objects.filter(legal_entity=legal_entity).order_by("-created_at")
    recent_cutoff = timezone.now() - timedelta(days=1)
    recent_ids = set(
        projects_qs.filter(created_at__gte=recent_cutoff).values_list("id", flat=True)
    )
    projects = list(projects_qs)
    for project in projects:
        project.baseline_workflow = get_project_baseline_workflow(project)
    return render(
        request,
        "app/hq_projects_list.html",
        {"projects": projects, "recent_ids": recent_ids, "current_legal_entity": legal_entity},
    )


@login_required
def hq_project_new(request):
    require_role(request.user, [Role.HQ, Role.CEO])
    action = request.POST.get("action") if request.method == "POST" else ""
    request_data = request.POST if request.method == "POST" else request.GET
    work_types = request_data.getlist("work_types") or [
        request_data.get("project_type") or ProjectType.LANDSCAPE
    ]
    work_types = [value for value in work_types if value in ProjectType.values]
    project_type = _primary_project_type(work_types)
    wbs_templates, wbs_template_notice = _get_templates_for_work_types(
        work_types, MasterTemplateCategory.WBS
    )
    budget_templates, budget_template_notice = _get_templates_for_work_types(
        work_types, MasterTemplateCategory.BUDGET
    )
    selected_wbs_templates = _resolve_templates_from_post(
        request_data.getlist("wbs_template_ids") or [request_data.get("wbs_template_id")], wbs_templates
    )
    selected_budget_templates = _resolve_templates_from_post(
        request_data.getlist("budget_template_ids") or [request_data.get("budget_template_id")], budget_templates
    )
    if request.method != "POST":
        selected_wbs_templates = selected_wbs_templates or wbs_templates[:1]
        selected_budget_templates = selected_budget_templates or budget_templates[:1]
    selected_wbs_template = selected_wbs_templates[0] if selected_wbs_templates else None
    selected_budget_template = selected_budget_templates[0] if selected_budget_templates else None

    upload_refs = _collect_project_new_upload_refs(request)
    import_context = _build_project_import_context(
        upload_refs,
        actor=request.user,
        request=request,
        log_parse=(request.method == "POST" and action in PROJECT_NEW_PREVIEW_ACTIONS),
        post_data=(request.POST if request.method == "POST" else None),
        action=action,
    )

    budget_template_warnings = []
    if request.method == "POST":
        form_files = _build_project_new_form_files(request, upload_refs)
        project_form = ProjectOnboardingForm(request.POST, actor=request.user)
        contract_form = ProjectContractForm(
            request.POST,
            form_files,
            require_file=(action not in PROJECT_NEW_PREVIEW_ACTIONS),
        )

        if action in PROJECT_NEW_PREVIEW_ACTIONS:
            budget_initial = import_context["budget_form_initial"]
            if not budget_initial:
                budget_initial, budget_template_warnings = _build_budget_initial_from_templates(
                    selected_budget_templates
                )
            wbs_initial = import_context["wbs_form_initial"]
            if not wbs_initial:
                wbs_initial, wbs_items_notice = _build_wbs_initial_from_templates(
                    selected_wbs_templates, project_type
                )
                if wbs_items_notice:
                    wbs_template_notice = (
                        f"{wbs_template_notice} {wbs_items_notice}".strip()
                        if wbs_template_notice
                        else wbs_items_notice
                    )
            budget_formset = _make_budget_formset(initial=budget_initial)
            wbs_formset = _make_wbs_formset(initial=wbs_initial)
        else:
            use_review_rows = bool(
                upload_refs.get("budget_excel") and import_context.get("budget_review_rows")
            )
            if use_review_rows:
                budget_formset = _make_budget_formset(initial=import_context["budget_form_initial"])
            else:
                budget_formset = _make_budget_formset(data=request.POST)
            wbs_formset = _make_wbs_formset(data=request.POST)
            if (
                project_form.is_valid()
                and contract_form.is_valid()
                and (use_review_rows or budget_formset.is_valid())
                and wbs_formset.is_valid()
            ):
                import_warning_count = int(
                    import_context.get("import_warning_count") or 0
                )
                if (
                    import_warning_count > 0
                    and request.POST.get("confirm_import_warnings") != "1"
                ):
                    messages.error(
                        request,
                        "파싱 경고를 확인하고 저장 여부를 체크해 주세요.",
                    )
                else:
                    can_save = True
                    budget_excel_uploaded = bool(upload_refs.get("budget_excel"))
                    if budget_excel_uploaded:
                        unmatched_rows = int(
                            import_context.get("budget_import_unmatched_rows") or 0
                        )
                        matched_rows = int(
                            import_context.get("budget_import_matched_rows") or 0
                        )
                        imported_row_count = int(
                            import_context.get("budget_import_total_rows") or 0
                        )
                        if imported_row_count > 0 and matched_rows <= 0:
                            messages.error(
                                request,
                                "계약내역서 Excel에서 저장 가능한 예산 라인이 없습니다.",
                            )
                            can_save = False
                        elif unmatched_rows > 0:
                            unmatched_details = import_context.get(
                                "budget_import_unmatched_details"
                            ) or []
                            row_numbers = ", ".join(
                                str(item.get("source_row_no") or "-")
                                for item in unmatched_details
                            ) or "-"
                            unmatched_amount = Decimal(
                                str(import_context.get("budget_import_unmatched_amount") or 0)
                            )
                            messages.error(
                                request,
                                "CBS \ubbf8\ub9e4\uce6d \ud589\uc774 \uc788\uc5b4 \uc608\uc0b0 \uae30\uc900\uc120\uc744 \uc800\uc7a5\ud560 \uc218 \uc5c6\uc2b5\ub2c8\ub2e4. "
                                f"\ubbf8\ub9e4\uce6d \ud589: {row_numbers} / \ubbf8\ub9e4\uce6d \uae08\uc561: {unmatched_amount:,.0f}\uc6d0. "
                                "CBS \ub9c8\uc2a4\ud130\ub97c \ub4f1\ub85d\ud558\uac70\ub098 \uc218\ub3d9 \ub9e4\ud551\ud574 \uc8fc\uc138\uc694.",
                            )
                            can_save = False
                        elif (
                            not use_review_rows
                            and int(
                            import_context.get("budget_form_initial_count") or 0
                            ) > int(request.POST.get("budget-TOTAL_FORMS") or 0)
                        ):
                            messages.error(
                                request,
                                "CBS 매핑 적용을 눌러 예산 입력표를 갱신한 뒤 등록해 주세요.",
                            )
                            can_save = False
                    if can_save:
                        if import_context.get("budget_review_errors"):
                            messages.error(
                                request,
                                "예산 상세 조정 항목에 오류가 있어 등록할 수 없습니다.",
                            )
                            can_save = False
                        elif upload_refs.get("budget_excel"):
                            context_gap = import_context.get("budget_summary_total_difference")
                            if (
                                context_gap is not None
                                and context_gap != 0
                                and request.POST.get("confirm_budget_reconciliation_gap") != "1"
                            ):
                                messages.error(
                                    request,
                                    "총괄표 금액과 예산 상세 조정 합계가 일치하지 않습니다. 차이를 확인해 주세요.",
                                )
                                can_save = False
                    if can_save:
                        if use_review_rows:
                            policy_blocked = False
                        else:
                            policy_blocked = _validate_budget_policy(
                                budget_formset,
                                role=Role.HQ,
                                existing_cost_item_ids=set(),
                                request=request,
                                project=None,
                                action="create",
                            )
                        if policy_blocked:
                            messages.error(
                                request,
                                "CBS 선택 정책으로 인해 저장할 수 없습니다.",
                            )
                        else:
                            if use_review_rows:
                                budget_items = _build_budget_form_initial_from_review_rows(
                                    import_context["budget_review_rows"],
                                    aggregate=(BUDGET_IMPORT_SAVE_MODE != "SOURCE_ROW_BUCKET"),
                                )
                                budget_items = [
                                    {
                                        "cost_item": CostItem.objects.get(id=item["cost_item"]),
                                        "category": item["category"],
                                        "name": item["name"],
                                        "planned_amount": item["planned_amount"],
                                        "note": item["note"],
                                    }
                                    for item in budget_items
                                ]
                            else:
                                budget_items = _collect_budget_items(budget_formset)
                            wbs_items, wbs_weight_sum = _collect_wbs_items(
                                wbs_formset
                            )
                            if not budget_items:
                                messages.error(
                                    request,
                                    "예산 라인을 1개 이상 입력해야 합니다.",
                                )
                            elif not wbs_items:
                                messages.error(
                                    request,
                                    "WBS 라인을 1개 이상 입력해야 합니다.",
                                )
                            elif not _is_weight_sum_valid(wbs_weight_sum):
                                messages.error(
                                    request,
                                    "WBS 가중치 합계는 100%여야 합니다.",
                                )
                            else:
                                try:
                                    with transaction.atomic():
                                        project = project_form.save(commit=False)
                                        selected_licenses = list(project_form.cleaned_data["contracting_licenses"])
                                        project.work_types = work_types
                                        project.project_type = project_type
                                        project.contracting_license = selected_licenses[0]
                                        project.contracting_license_snapshot = " | ".join(
                                            f"{item.license_type} / {item.registration_number} / {item.registered_by} / 등록일 {item.registered_on:%Y-%m-%d}"
                                            for item in selected_licenses
                                        )
                                        _resolve_wbs_baseline_dates(wbs_items, project)
                                        if not project.code:
                                            project.code = _generate_project_code(project.legal_entity, project.project_type)
                                        if not project.status:
                                            project.status = ProjectStatus.DRAFT
                                        if selected_wbs_template:
                                            project.wbs_template = selected_wbs_template
                                        if selected_budget_template:
                                            project.budget_template = (
                                                selected_budget_template
                                            )
                                        project.save()
                                        project.contracting_licenses.set(selected_licenses)
                                        create_site_warehouse(
                                            project, actor=request.user
                                        )
    
                                        contract = contract_form.save(commit=False)
                                        contract.project = project
                                        contract.status = (
                                            ProjectContractStatus.APPROVED
                                        )
                                        contract.start_date = (
                                            contract.contract_start_date
                                            or project.start_date
                                        )
                                        contract.end_date = (
                                            contract.contract_end_date
                                            or project.end_date
                                        )
                                        contract.save()
    
                                        evidence = None
                                        contract_file = contract.contract_file
                                        if contract_file:
                                            evidence = Evidence.objects.create(
                                                title=f"{project.name} 계약서",
                                                description="HQ 신규 공사 계약서",
                                                object_type="PROJECT_CONTRACT",
                                                object_id=contract.id,
                                                created_by=request.user,
                                            )
                                            EvidenceFile.objects.create(
                                                evidence=evidence,
                                                file=contract_file,
                                                original_name=getattr(
                                                    contract_file,
                                                    "name",
                                                    "contract",
                                                ),
                                                content_type=getattr(
                                                    contract_file,
                                                    "content_type",
                                                    "application/octet-stream",
                                                ),
                                                created_by=request.user,
                                            )
    
                                        for item in budget_items:
                                            BudgetItem.objects.create(
                                                project=project,
                                                cost_item=item["cost_item"],
                                                category=_canonical_budget_category_for_cost_item(
                                                    item["cost_item"],
                                                    current_category=item["category"],
                                                ),
                                                name=item["name"],
                                                planned_amount=item["planned_amount"],
                                                status=ProjectContractStatus.APPROVED,
                                                note=item["note"],
                                            )
                                            _log_budget_cbs_select(
                                                request,
                                                project,
                                                item["cost_item"],
                                                action="create",
                                            )
    
                                        for item in wbs_items:
                                            WBSItem.objects.create(
                                                project=project,
                                                name=item["name"],
                                                weight=item["weight"],
                                                sort_order=item["sort_order"],
                                                plan_start_date=item[
                                                    "plan_start_date"
                                                ],
                                                plan_end_date=item[
                                                    "plan_end_date"
                                                ],
                                                baseline_version=1,
                                                is_baseline=True,
                                            )
    
                                        _attach_project_import_file(
                                            project,
                                            upload_refs.get("budget_excel"),
                                            title=f"{project.name} 계약예산 원본",
                                            description="HQ 신규 공사 예산 가져오기 원본",
                                            actor=request.user,
                                        )
                                        _attach_project_import_file(
                                            project,
                                            upload_refs.get("commencement_excel"),
                                            title=f"{project.name} 착공계/예정공정표 원본",
                                            description="HQ 신규 공사 WBS 가져오기 원본",
                                            actor=request.user,
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
                                        if evidence is not None:
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
                                            meta={"row_count": len(budget_items)},
                                        )
                                        log_action(
                                            actor=request.user,
                                            action="WBS_BASELINE_CREATE",
                                            object_type="WBS",
                                            object_id=project.id,
                                            project=project,
                                            request=request,
                                            meta={"row_count": len(wbs_items)},
                                        )
                                        _log_project_import_commit_actions(
                                            project=project,
                                            request=request,
                                            import_context=import_context,
                                            upload_refs=upload_refs,
                                            budget_items=budget_items,
                                            wbs_items=wbs_items,
                                        )
                                        if upload_refs.get("budget_excel") or upload_refs.get(
                                            "commencement_excel"
                                        ):
                                            partial_budget_import = False
                                            log_action(
                                                actor=request.user,
                                                action="PROJECT_IMPORT_COMMIT",
                                                object_type="PROJECT_IMPORT",
                                                object_id=project.id,
                                                project=project,
                                                request=request,
                                                meta={
                                                    "budget_rows": len(
                                                        import_context[
                                                            "budget_preview_rows"
                                                        ]
                                                    ),
                                                    "wbs_rows": len(
                                                        import_context[
                                                            "wbs_preview_rows"
                                                        ]
                                                    ),
                                                    "warning_count": import_warning_count,
                                                    "budget_filename": (
                                                        upload_refs.get("budget_excel")
                                                        or {}
                                                    ).get("original_name", ""),
                                                    "wbs_filename": (
                                                        upload_refs.get(
                                                            "commencement_excel"
                                                        )
                                                        or {}
                                                    ).get("original_name", ""),
                                                    "partial_budget_import": partial_budget_import,
                                                    "unmatched_rows": int(
                                                        import_context.get(
                                                            "budget_import_unmatched_rows"
                                                        )
                                                        or 0
                                                    ),
                                                    "matched_rows": int(
                                                        import_context.get(
                                                            "budget_import_matched_rows"
                                                        )
                                                        or 0
                                                    ),
                                                    "form_initial_count": int(
                                                        import_context.get(
                                                            "budget_form_initial_count"
                                                        )
                                                        or 0
                                                    ),
                                                    "alias_created_count": int(
                                                        import_context.get(
                                                            "budget_alias_created_count"
                                                        )
                                                        or 0
                                                    ),
                                                    "alias_existing_count": int(
                                                        import_context.get(
                                                            "budget_alias_existing_count"
                                                        )
                                                        or 0
                                                    ),
                                                    "alias_skipped_count": int(
                                                        import_context.get(
                                                            "budget_alias_skipped_count"
                                                        )
                                                        or 0
                                                    ),
                                                },
                                            )
                                            _cleanup_project_new_uploads(
                                                request, upload_refs
                                            )
    
                                    messages.success(
                                        request, "프로젝트가 등록되었습니다."
                                    )
                                    return redirect(f"/app/hq/projects/{project.id}/")
                                except ValidationError as exc:
                                    messages.error(request, str(exc))
                                except IntegrityError:
                                    logger.exception(
                                        "Failed to save project import budget rows due to integrity error."
                                    )
                                    messages.error(
                                        request,
                                        "예산 라인 저장 중 중복 제약 오류가 발생했습니다. 예산 상세 조정 항목을 확인해 주세요.",
                                    )
    else:
        project_form = ProjectOnboardingForm(
            initial={"status": ProjectStatus.DRAFT, "work_types": work_types}, actor=request.user
        )
        contract_form = ProjectContractForm(require_file=True)
        budget_initial, budget_template_warnings = _build_budget_initial_from_templates(
            selected_budget_templates
        )
        if import_context["budget_form_initial"]:
            budget_initial = import_context["budget_form_initial"]
        elif budget_initial and not budget_template_notice:
            budget_template_notice = (
                "선택한 예산 템플릿이 자동으로 채워졌습니다. 금액을 입력/수정해 주세요."
            )
        budget_formset = _make_budget_formset(initial=budget_initial)

        wbs_initial, wbs_items_notice = _build_wbs_initial_from_templates(
            selected_wbs_templates, project_type
        )
        if import_context["wbs_form_initial"]:
            wbs_initial = import_context["wbs_form_initial"]
        elif wbs_items_notice:
            wbs_template_notice = (
                f"{wbs_template_notice} {wbs_items_notice}".strip()
                if wbs_template_notice
                else wbs_items_notice
            )
        elif selected_wbs_template and not wbs_template_notice:
            wbs_template_notice = (
                "선택한 WBS 템플릿이 자동으로 채워졌습니다. 일정을 입력/수정해 주세요."
            )
        wbs_formset = _make_wbs_formset(initial=wbs_initial)


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
            "budget_review_category_choices": BUDGET_BASELINE_CATEGORY_CHOICES,
            "wbs_template_notice": wbs_template_notice,
            "budget_template_notice": budget_template_notice,
            "budget_template_warnings": budget_template_warnings,
            "wbs_templates": wbs_templates,
            "budget_templates": budget_templates,
            "selected_wbs_template": selected_wbs_template,
            "selected_budget_template": selected_budget_template,
            "selected_wbs_templates": selected_wbs_templates,
            "selected_budget_templates": selected_budget_templates,
            **import_context,
        },
    )


def _make_budget_formset(*, data=None, initial=None):
    if data is not None:
        extra = 0
    elif initial:
        extra = len(initial)
    else:
        extra = 5
    formset_cls = modelformset_factory(
        BudgetItem, form=BudgetItemForm, extra=extra, can_delete=True
    )
    kwargs = {"queryset": BudgetItem.objects.none(), "prefix": "budget"}
    if data is not None:
        kwargs["data"] = data
    elif initial is not None:
        kwargs["initial"] = initial
    return formset_cls(**kwargs)


def _make_wbs_formset(*, data=None, initial=None):
    if data is not None:
        extra = 0
    elif initial:
        extra = len(initial)
    else:
        extra = 4
    formset_cls = modelformset_factory(
        WBSItem, form=WBSItemForm, extra=extra, can_delete=True
    )
    kwargs = {"queryset": WBSItem.objects.none(), "prefix": "wbs"}
    if data is not None:
        kwargs["data"] = data
    elif initial is not None:
        kwargs["initial"] = initial
    return formset_cls(**kwargs)


def _store_project_new_upload(request, field_name, uploaded_file):
    temp_dir = Path(settings.MEDIA_ROOT) / "project_import_temp"
    temp_dir.mkdir(parents=True, exist_ok=True)
    token = uuid.uuid4().hex
    original_name = Path(uploaded_file.name or field_name).name
    safe_name = get_valid_filename(original_name) or f"{field_name}.bin"
    path = temp_dir / f"{token}_{safe_name}"
    with path.open("wb") as handle:
        for chunk in uploaded_file.chunks():
            handle.write(chunk)
    session_map = request.session.get(PROJECT_NEW_UPLOAD_SESSION_KEY, {})
    session_map[token] = {
        "field_name": field_name,
        "path": str(path),
        "original_name": original_name,
        "content_type": getattr(uploaded_file, "content_type", "application/octet-stream"),
    }
    request.session[PROJECT_NEW_UPLOAD_SESSION_KEY] = session_map
    request.session.modified = True
    ref = session_map[token].copy()
    ref["token"] = token
    return ref


def _collect_project_new_upload_refs(request):
    session_map = request.session.get(PROJECT_NEW_UPLOAD_SESSION_KEY, {})
    refs = {}
    for field_name in PROJECT_NEW_UPLOAD_FIELDS:
        upload = request.FILES.get(field_name)
        token = request.POST.get(f"{field_name}_token") if request.method == "POST" else ""
        if upload:
            error = _validate_project_new_upload(field_name, upload)
            if error:
                messages.error(request, error)
                refs[field_name] = None
            else:
                refs[field_name] = _store_project_new_upload(request, field_name, upload)
        elif token and token in session_map:
            refs[field_name] = session_map[token].copy()
            refs[field_name]["token"] = token
        else:
            refs[field_name] = None
    return refs


def _validate_project_new_upload(field_name, upload):
    if field_name not in {"budget_excel", "commencement_excel"}:
        return ""
    filename = (getattr(upload, "name", "") or "").lower()
    if not filename.endswith(".xlsx"):
        label = "계약내역서 Excel" if field_name == "budget_excel" else "착공계 Excel"
        return f"{label}은 .xlsx 파일만 업로드할 수 있습니다."
    return ""


def _build_project_new_form_files(request, upload_refs):
    files = MultiValueDict()
    for key in request.FILES:
        files.setlist(key, request.FILES.getlist(key))
    if "contract_file" not in files and upload_refs.get("contract_file"):
        ref = upload_refs["contract_file"]
        payload = Path(ref["path"]).read_bytes()
        files.setlist(
            "contract_file",
            [
                SimpleUploadedFile(
                    ref["original_name"],
                    payload,
                    content_type=ref.get("content_type") or "application/octet-stream",
                )
            ],
        )
    return files


def _normalize_cost_key(value):
    return "".join(ch for ch in str(value or "").upper() if ch.isalnum())


def _normalize_import_text(value):
    text = unicodedata.normalize("NFKC", str(value or "")).strip()
    return re.sub(r"\s+", " ", text)


def _normalize_import_key(value):
    text = _normalize_import_text(value).lower()
    return "".join(
        ch for ch in text if ch.isalnum() or ("\uac00" <= ch <= "\ud7a3")
    )


def _tokenize_import_text(*values):
    text = " ".join(_normalize_import_text(value) for value in values if value)
    if not text:
        return []
    tokens = re.findall(r"[0-9A-Za-z\uac00-\ud7a3]+", text)
    normalized = []
    seen = set()
    for token in tokens:
        token_key = _normalize_import_key(token)
        if len(token_key) < 2 or token_key in seen:
            continue
        seen.add(token_key)
        normalized.append(token_key)
    return normalized


def _make_budget_import_key(row, index):
    code_key = _normalize_import_key(row.get("code"))
    name_key = _normalize_import_key(row.get("item_name"))
    spec_key = _normalize_import_key(row.get("spec"))
    row_no = row.get("row_no") or row.get("row_number") or index + 1
    return f"{row_no}-{code_key[:24]}-{name_key[:48]}-{spec_key[:24]}-{index}"


def _is_empty_budget_value(value):
    if value is None:
        return True
    if isinstance(value, str):
        return _normalize_import_text(value) in {"", "-", "—", "–"}
    return False


def _is_zero_budget_value(value):
    if value is None:
        return True
    try:
        return Decimal(str(value or 0)) == 0
    except Exception:
        return False


def _is_blank_or_dash(value):
    if value is None:
        return True
    if isinstance(value, str):
        return _normalize_import_text(value) in {"", "-", "—", "–"}
    return False


def _is_blank_or_dash_or_zero(value):
    if _is_blank_or_dash(value):
        return True
    try:
        return Decimal(str(value).strip() or "0") == 0
    except Exception:
        return False


def _has_any_budget_amount(row):
    for key in ("amount", "labor_amount", "material_amount", "expense_amount"):
        if not _is_zero_budget_value(row.get(key)):
            return True
    return False


def _coerce_optional_decimal(value):
    if value in (None, ""):
        return None
    try:
        return Decimal(str(value).replace(",", "").strip())
    except Exception:
        return None


def _looks_like_aggregate_amount_row(row):
    item_name = _normalize_import_text(row.get("item_name"))
    if not item_name:
        return False
    if not _has_any_budget_amount(row):
        return False
    if not _is_blank_or_dash(row.get("quantity")):
        return False
    if not _is_blank_or_dash(row.get("unit")):
        return False
    if not _is_blank_or_dash_or_zero(row.get("unit_price")):
        return False
    return True


def _is_exact_profit_row(item_name):
    return _normalize_import_key(item_name) == _normalize_import_key("이윤")


def _is_forced_expense_row(item_name):
    normalized = _normalize_import_key(item_name)
    if not normalized:
        return False
    forced_exact = {
        _normalize_import_key("간접노무비"),
        _normalize_import_key("산재보험료"),
        _normalize_import_key("고용보험료"),
        _normalize_import_key("건강보험료"),
        _normalize_import_key("연금보험료"),
        _normalize_import_key("노인장기요양보험료"),
        _normalize_import_key("퇴직공제부금비"),
        _normalize_import_key("건설기계대여금지급보증서발급액"),
        _normalize_import_key("건설기계대여금지급보증 발급액"),
        _normalize_import_key("산업안전보건관리비"),
        _normalize_import_key("환경보전비"),
        _normalize_import_key("환경보건비"),
        _normalize_import_key("하도급대금지급보증수수료"),
        _normalize_import_key("일반관리비"),
    }
    if normalized in forced_exact:
        return True
    forced_contains = ("보험료", "수수료", "지급보증", "발급액", "환경보전", "환경보건")
    return any(_normalize_import_key(token) in normalized for token in forced_contains)


def _is_labor_personnel_row(item_name):
    normalized = _normalize_import_key(item_name)
    if not normalized:
        return False
    keywords = ("안전관리책임자", "안전관리자", "현장대리인", "작업자", "인부", "신호수")
    return any(_normalize_import_key(keyword) in normalized for keyword in keywords)


def _find_candidate_by_code(candidates, code):
    code_key = _normalize_cost_key(code)
    for candidate in candidates:
        if candidate["code_key"] == code_key:
            return candidate["item"]
    return None


def _find_first_candidate_by_category(candidates, category):
    for candidate in candidates:
        if candidate["item"].category == category:
            return candidate["item"]
    return None


def _normalize_budget_code(value):
    return _normalize_import_text(value).rstrip(".")


def _budget_code_depth(code):
    normalized = _normalize_budget_code(code)
    if not normalized:
        return None
    return normalized.count("-")


def _is_budget_code_descendant(code, ancestor):
    code_norm = _normalize_budget_code(code)
    ancestor_norm = _normalize_budget_code(ancestor)
    if not code_norm or not ancestor_norm:
        return False
    return code_norm == ancestor_norm or code_norm.startswith(f"{ancestor_norm}-")


def _looks_like_owner_supplied_section_row(row):
    item_name = _normalize_import_text(row.get("item_name"))
    if not item_name:
        return False
    if "관급자재대" in item_name:
        return True
    if not any(token in item_name for token in ("관급자재", "관급")):
        return False
    code = _normalize_budget_code(row.get("code"))
    quantity = row.get("quantity")
    unit = row.get("unit")
    unit_price = row.get("unit_price")
    return _is_blank_or_dash(quantity) and _is_blank_or_dash(unit) and _is_blank_or_dash_or_zero(unit_price)


def _detect_owner_supplied_row_keys(rows):
    owner_supplied_keys = set()
    owner_amount = Decimal("0")
    owner_root_keys = set()
    owner_row_count = 0
    active_root_code = None
    active_root_depth = None

    for index, row in enumerate(rows):
        row_key = row["import_key"]
        item_name = _normalize_import_text(row.get("item_name"))
        code = _normalize_budget_code(row.get("code"))
        row_amount = Decimal(str(row.get("amount") or 0))

        if _looks_like_owner_supplied_section_row(row):
            owner_supplied_keys.add(row_key)
            owner_root_keys.add(row_key)
            owner_row_count += 1
            if row_amount > 0:
                owner_amount += row_amount
            active_root_code = code or f"ROW-{index}"
            active_root_depth = _budget_code_depth(code)
            continue

        if active_root_code:
            if code:
                if active_root_code.startswith("ROW-"):
                    # code-less root falls through only until next coded section
                    active_root_code = None
                    active_root_depth = None
                elif _is_budget_code_descendant(code, active_root_code):
                    owner_supplied_keys.add(row_key)
                    owner_row_count += 1
                    continue
                else:
                    current_depth = _budget_code_depth(code)
                    if current_depth is None or (
                        active_root_depth is not None and current_depth <= active_root_depth
                    ):
                        active_root_code = None
                        active_root_depth = None
                    else:
                        active_root_code = None
                        active_root_depth = None

            if active_root_code and not code:
                owner_supplied_keys.add(row_key)
                owner_row_count += 1
                continue

        if row_key in owner_supplied_keys:
            continue

    return {
        "row_keys": owner_supplied_keys,
        "root_keys": owner_root_keys,
        "amount": owner_amount,
        "row_count": owner_row_count,
    }


def _is_summary_scope_row(item_name, code_text):
    item_key = _normalize_import_key(item_name)
    code_key = _normalize_import_key(code_text)
    summary_terms = {
        _normalize_import_key("도급예정액"),
        _normalize_import_key("도급금액"),
        _normalize_import_key("도급계약금액"),
        _normalize_import_key("계약금액"),
        _normalize_import_key("도급액"),
        _normalize_import_key("도급합계"),
        _normalize_import_key("도급금액합계"),
        _normalize_import_key("도급내역서"),
        _normalize_import_key("총공사비"),
        _normalize_import_key("총원가"),
        _normalize_import_key("순공사원가"),
        _normalize_import_key("공급가액"),
        _normalize_import_key("부가세"),
        _normalize_import_key("소계"),
        _normalize_import_key("합계"),
        _normalize_import_key("총계"),
        _normalize_import_key("누계"),
        _normalize_import_key("내역서"),
        _normalize_import_key("공사명"),
    }
    return item_key in summary_terms or code_key in summary_terms


def _mark_budget_import_parent_rows(rows):
    parent_keys = set()
    codes = [
        _normalize_import_text(row.get("code"))
        for row in rows
    ]
    for index, row in enumerate(rows):
        code = codes[index]
        if not code:
            continue
        has_child = any(
            later_code.startswith(f"{code}-")
            for later_code in codes[index + 1 :]
            if later_code
        )
        if not has_child:
            continue
        quantity = _normalize_import_text(row.get("quantity"))
        unit = _normalize_import_text(row.get("unit"))
        if quantity in {"", "-", "—"} and unit in {"", "-", "—"}:
            parent_keys.add(row["import_key"])
    return parent_keys


def _should_skip_budget_import_row(row, *, parent_row_keys=None):
    parent_row_keys = parent_row_keys or set()
    if row.get("import_key") in parent_row_keys:
        return True, True

    code_text = _normalize_import_text(row.get("code"))
    item_name = _normalize_import_text(row.get("item_name"))
    code_key = _normalize_import_key(code_text)
    item_key = _normalize_import_key(item_name)

    amount = row.get("amount")
    labor = row.get("labor_amount")
    material = row.get("material_amount")
    expense = row.get("expense_amount")
    quantity = row.get("quantity")
    unit = row.get("unit")
    unit_price = row.get("unit_price")

    if not item_name and _is_empty_budget_value(quantity) and _is_empty_budget_value(unit) and _is_empty_budget_value(amount):
        return True, False

    if _looks_like_aggregate_amount_row(
        {
            "item_name": item_name,
            "amount": amount,
            "labor_amount": labor,
            "material_amount": material,
            "expense_amount": expense,
            "quantity": quantity,
            "unit": unit,
            "unit_price": unit_price,
        }
    ):
        return True, True

    has_meaningful_amount = not (
        _is_zero_budget_value(amount)
        and _is_zero_budget_value(labor)
        and _is_zero_budget_value(material)
        and _is_zero_budget_value(expense)
    )
    has_quantity_or_unit = not (
        _is_empty_budget_value(quantity) and _is_empty_budget_value(unit)
    )

    if _is_summary_scope_row(item_name, code_text):
        return True, True

    if item_key in {"공종", "소계", "합계", "총계", "누계"} or code_key in {
        "공종",
        "소계",
        "합계",
        "총계",
        "누계",
    }:
        return True, True

    if not has_meaningful_amount and not has_quantity_or_unit:
        return True, False

    if item_name.startswith("국도") and not has_meaningful_amount:
        return True, True

    section_tokens = (
        "국도",
        "지방도",
        "대교",
        "교량",
        "교차로",
        "IC",
        "상행",
        "하행",
    )
    if (
        not has_meaningful_amount
        and not has_quantity_or_unit
        and item_name
        and any(token in item_name for token in section_tokens)
    ):
        return True, True

    return False, False


def _extract_budget_manual_mapping(post_data):
    manual_mapping = {}
    alias_save_keys = set()
    if not post_data:
        return manual_mapping, alias_save_keys

    for key, value in post_data.items():
        if key.startswith("budget_match__"):
            import_key = key.split("__", 1)[1]
            if value:
                manual_mapping[import_key] = value
        elif key.startswith("budget_alias_save__") and value:
            import_key = key.split("__", 1)[1]
            alias_save_keys.add(import_key)
    return manual_mapping, alias_save_keys


def _extract_budget_review_adjustments(post_data):
    adjustments = {}
    if not post_data:
        return adjustments

    def ensure(review_key):
        return adjustments.setdefault(
            review_key,
            {
                "exclude": False,
                "category": "",
                "cost_item_id": "",
                "name": "",
                "planned_amount": "",
                "note": "",
                "alias_save": False,
            },
        )

    for key, value in post_data.items():
        if "__" not in key:
            continue
        prefix, review_key = key.split("__", 1)
        if prefix == "budget_review_exclude" and value:
            ensure(review_key)["exclude"] = True
        elif prefix == "budget_review_category":
            ensure(review_key)["category"] = value
        elif prefix == "budget_review_cost_item":
            ensure(review_key)["cost_item_id"] = value
        elif prefix == "budget_review_name":
            ensure(review_key)["name"] = value
        elif prefix == "budget_review_amount":
            ensure(review_key)["planned_amount"] = value
        elif prefix == "budget_review_note":
            ensure(review_key)["note"] = value
        elif prefix == "budget_review_alias_save" and value:
            ensure(review_key)["alias_save"] = True
    return adjustments


def _build_import_cost_item_candidates(cost_items):
    usable_items = []
    for item in cost_items:
        policy = evaluate_cbs_selectability(
            item,
            Role.HQ,
            "BUDGET",
            is_existing_usage=False,
        )
        if not policy.selectable:
            continue
        names = [item.name, item.get_display_name()] + [alias.alias for alias in item.aliases.all()]
        normalized_names = []
        seen_name_keys = set()
        for name in names:
            key = _normalize_import_key(name)
            if key and key not in seen_name_keys:
                seen_name_keys.add(key)
                normalized_names.append(key)
        tokens = _tokenize_import_text(*names)
        usable_items.append(
            {
                "item": item,
                "code_key": _normalize_cost_key(item.code),
                "name_keys": normalized_names,
                "tokens": tokens,
            }
        )
    return usable_items


def _build_budget_match_options(cost_items):
    return [
        {
            "id": candidate["item"].id,
            "label": str(candidate["item"]),
        }
        for candidate in _build_import_cost_item_candidates(cost_items)
    ]


def _persist_budget_manual_aliases(rows, manual_mapping, alias_save_keys, cost_items):
    result = {
        "alias_created_count": 0,
        "alias_existing_count": 0,
        "alias_skipped_count": 0,
        "alias_saved_labels": [],
        "alias_skipped_reasons": [],
    }
    if not alias_save_keys:
        return result

    row_map = {row.get("import_key"): row for row in rows}
    selectable_items = {}
    for item in cost_items:
        policy = evaluate_cbs_selectability(
            item,
            Role.HQ,
            "BUDGET",
            is_existing_usage=False,
        )
        if policy.selectable:
            selectable_items[item.id] = item
    for import_key in alias_save_keys:
        cost_item_id = manual_mapping.get(import_key)
        row = row_map.get(import_key)
        if not cost_item_id:
            result["alias_skipped_count"] += 1
            result["alias_skipped_reasons"].append(
                "CBS가 선택되지 않아 alias를 저장하지 않았습니다."
            )
            continue
        if row is None:
            result["alias_skipped_count"] += 1
            result["alias_skipped_reasons"].append(
                "원본 행을 찾지 못해 alias를 저장하지 않았습니다."
            )
            continue
        try:
            cost_item = selectable_items[int(cost_item_id)]
        except (KeyError, TypeError, ValueError):
            result["alias_skipped_count"] += 1
            result["alias_skipped_reasons"].append(
                "선택 가능한 CBS가 아니어서 alias를 저장하지 않았습니다."
            )
            continue
        item_name = _normalize_import_text(row.get("item_name"))
        if not item_name:
            result["alias_skipped_count"] += 1
            result["alias_skipped_reasons"].append(
                "품명이 없어 alias를 저장하지 않았습니다."
            )
            continue
        if _is_exact_profit_row(item_name):
            result["alias_skipped_count"] += 1
            result["alias_skipped_reasons"].append(
                "이윤은 alias 저장 대상이 아닙니다."
            )
            continue
        spec = _normalize_import_text(row.get("spec"))
        aliases = []
        aliases.append(item_name)
        if item_name and spec:
            aliases.append(f"{item_name} {spec}")
        for alias in aliases:
            _, created = CostItemAlias.objects.get_or_create(
                cost_item=cost_item,
                alias=alias,
                defaults={
                    "is_primary": False,
                    "note": "project_import_manual_mapping",
                },
            )
            if created:
                result["alias_created_count"] += 1
                result["alias_saved_labels"].append(f"{alias} → {cost_item.name}")
            else:
                result["alias_existing_count"] += 1
    return result


def _merge_alias_diagnostics(base, extra):
    for key in ("alias_created_count", "alias_existing_count", "alias_skipped_count"):
        base[key] += extra.get(key, 0)
    base["alias_saved_labels"].extend(extra.get("alias_saved_labels", []))
    base["alias_skipped_reasons"].extend(extra.get("alias_skipped_reasons", []))
    return base


def _persist_budget_review_aliases(review_rows, cost_items):
    result = {
        "alias_created_count": 0,
        "alias_existing_count": 0,
        "alias_skipped_count": 0,
        "alias_saved_labels": [],
        "alias_skipped_reasons": [],
    }
    selectable_items = {}
    for item in cost_items:
        policy = evaluate_cbs_selectability(
            item,
            Role.HQ,
            "BUDGET",
            is_existing_usage=False,
        )
        if policy.selectable:
            selectable_items[item.id] = item
    for review_row in review_rows:
        if not review_row.get("alias_save"):
            continue
        if review_row.get("is_excluded"):
            result["alias_skipped_count"] += 1
            result["alias_skipped_reasons"].append("제외된 행은 alias를 저장하지 않았습니다.")
            continue
        if _is_exact_profit_row(review_row.get("source_item_name")):
            result["alias_skipped_count"] += 1
            result["alias_skipped_reasons"].append("이윤은 alias 저장 대상이 아닙니다.")
            continue
        if "관급" in (review_row.get("source_item_name") or ""):
            result["alias_skipped_count"] += 1
            result["alias_skipped_reasons"].append("관급자재 행은 alias를 저장하지 않았습니다.")
            continue
        cost_item = selectable_items.get(review_row.get("cost_item_id"))
        if cost_item is None:
            result["alias_skipped_count"] += 1
            result["alias_skipped_reasons"].append("CBS가 선택되지 않아 alias를 저장하지 않았습니다.")
            continue
        item_name = _normalize_import_text(review_row.get("source_item_name"))
        if not item_name:
            result["alias_skipped_count"] += 1
            result["alias_skipped_reasons"].append("품명이 없어 alias를 저장하지 않았습니다.")
            continue
        spec = _normalize_import_text(review_row.get("source_spec"))
        aliases = [item_name]
        if item_name and spec:
            aliases.append(f"{item_name} {spec}")
        for alias in aliases:
            _, created = CostItemAlias.objects.get_or_create(
                cost_item=cost_item,
                alias=alias,
                defaults={"is_primary": False, "note": "project_import_manual_mapping"},
            )
            if created:
                result["alias_created_count"] += 1
                result["alias_saved_labels"].append(f"{alias} → {cost_item.name}")
            else:
                result["alias_existing_count"] += 1
    return result


def _pick_best_keyword_cost_item(candidates, *, name_keywords=(), token_keywords=(), category_preferences=()):
    filtered = []
    for candidate in candidates:
        haystack = " ".join(candidate["name_keys"])
        score = 0
        for keyword in name_keywords:
            keyword_key = _normalize_import_key(keyword)
            if keyword_key and keyword_key in haystack:
                score += 3
        for keyword in token_keywords:
            keyword_key = _normalize_import_key(keyword)
            if keyword_key and keyword_key in candidate["tokens"]:
                score += 2
        if score <= 0:
            continue
        if candidate["item"].category in category_preferences:
            score += 2
        filtered.append((score, len(candidate["item"].name), candidate["item"].id, candidate["item"]))
    if not filtered:
        return None
    filtered.sort(key=lambda entry: (-entry[0], entry[1], entry[2]))
    top = filtered[0]
    if len(filtered) > 1 and filtered[1][0] == top[0]:
        return None
    return top[3]


def _match_cost_item_for_import_row(row, cost_items, candidates=None):
    if candidates is None:
        candidates = _build_import_cost_item_candidates(cost_items)

    # Contract-statement CBS codes are authoritative when supplied. Excel
    # buckets still control the saved contract-budget category.
    source_cbs_code = _normalize_import_text(row.get("cbs_code"))
    if source_cbs_code:
        source_code_key = _normalize_cost_key(source_cbs_code)
        exact_matches = [
            candidate["item"]
            for candidate in candidates
            if candidate["code_key"] == source_code_key and candidate["item"].is_active
        ]
        if len(exact_matches) == 1:
            row["match_status"] = "EXACT_CODE"
            row["match_reason"] = f"CBS \ucf54\ub4dc \uc77c\uce58: {source_cbs_code}"
            return exact_matches[0]

        fallback_matches = {}
        fallback_method = ""
        for value in (row.get("cbs_name"), row.get("item_name")):
            value_key = _normalize_import_key(value)
            if not value_key:
                continue
            for candidate in candidates:
                if candidate["item"].code == "CIVIL-EXPENSE":
                    continue
                if value_key not in candidate["name_keys"]:
                    continue
                fallback_matches[candidate["item"].id] = candidate["item"]
                if value_key == _normalize_import_key(candidate["item"].name):
                    fallback_method = "NAME_FALLBACK"
                elif not fallback_method:
                    fallback_method = "ALIAS"
        if len(fallback_matches) == 1:
            row["match_status"] = fallback_method or "ALIAS"
            row["match_reason"] = (
                f"CBS \ucf54\ub4dc {source_cbs_code} \ubbf8\ub4f1\ub85d, "
                "\uba85\uce6d/alias \ub300\uccb4 \ub9e4\uce6d"
            )
            return next(iter(fallback_matches.values()))

        row["match_status"] = "UNMATCHED_CBS"
        row["match_reason"] = (
            f"CBS \ubbf8\ub9e4\uce6d (UNMATCHED_CBS): {source_cbs_code}. "
            "CBS \ub9c8\uc2a4\ud130\ub97c \ub4f1\ub85d\ud558\uac70\ub098 \uc218\ub3d9 \ub9e4\ud551\ud574 \uc8fc\uc138\uc694."
        )
        return None

    target_name_key = _normalize_import_key(row.get("item_name"))
    if target_name_key == _normalize_import_key("이윤"):
        row["requires_manual_profit_mapping"] = True
        return None

    candidates = [
        candidate
        for candidate in candidates
        if candidate["code_key"] != _normalize_cost_key("CIVIL-PROFIT")
    ]

    if _is_forced_expense_row(row.get("item_name")):
        return (
            _find_candidate_by_code(candidates, "CIVIL-EXPENSE")
            or _pick_best_keyword_cost_item(
                candidates,
                name_keywords=("경비", "기타"),
                token_keywords=("경비", "기타"),
                category_preferences=(BudgetCategory.OTHER,),
            )
            or _find_first_candidate_by_category(candidates, "other")
        )

    if _is_labor_personnel_row(row.get("item_name")):
        return (
            _find_candidate_by_code(candidates, "LABOR-GENERAL")
            or _find_candidate_by_code(candidates, "CIVIL-LABOR")
            or _find_first_candidate_by_category(candidates, "labor")
        )

    code_key = _normalize_cost_key(row.get("code"))
    if code_key:
        exact_code_matches = [candidate["item"] for candidate in candidates if candidate["code_key"] == code_key]
        if len(exact_code_matches) == 1:
            return exact_code_matches[0]

    target_text_key = _normalize_import_key(
        " ".join(
            str(part or "")
            for part in (row.get("item_name"), row.get("spec"), row.get("code"))
        )
    )
    row_tokens = _tokenize_import_text(row.get("item_name"), row.get("spec"), row.get("code"))

    if target_name_key:
        exact_name_matches = [
            candidate["item"]
            for candidate in candidates
            if target_name_key in candidate["name_keys"]
        ]
        if len(exact_name_matches) == 1:
            return exact_name_matches[0]

    if target_text_key:
        alias_contains_matches = []
        for candidate in candidates:
            if any(
                name_key and (name_key in target_text_key or target_text_key in name_key)
                for name_key in candidate["name_keys"]
            ):
                alias_contains_matches.append(candidate["item"])
        unique_matches = list({item.id: item for item in alias_contains_matches}.values())
        if len(unique_matches) == 1:
            return unique_matches[0]

    keyword_text = " ".join(row_tokens)
    keyword_rules = [
        (
            ("아스콘", "아스팔트", "포장", "덧씌우기", "절삭"),
            ("포장", "아스콘"),
            (BudgetCategory.MATERIAL, BudgetCategory.OTHER, BudgetCategory.SUBCON),
        ),
        (
            ("차선", "도색"),
            ("도색", "안전", "기타"),
            (BudgetCategory.MATERIAL, BudgetCategory.OTHER),
        ),
        (
            ("폐기물", "운반", "처리"),
            ("폐기물", "기타경비", "기타"),
            (BudgetCategory.OTHER, BudgetCategory.SUBCON),
        ),
        (
            ("수수료", "보증수수료", "지급보증", "발급액"),
            ("경비", "기타"),
            (BudgetCategory.OTHER,),
        ),
        (
            ("교통", "안전", "표지", "차단"),
            ("안전", "기타"),
            (BudgetCategory.OTHER, BudgetCategory.MATERIAL),
        ),
        (
            ("철거", "절단", "보수"),
            ("철거", "보수", "기타"),
            (BudgetCategory.OTHER, BudgetCategory.SUBCON),
        ),
        (("노무",), ("노무",), (BudgetCategory.LABOR,)),
        (("재료",), ("재료",), (BudgetCategory.MATERIAL,)),
        (("경비",), ("경비", "기타"), (BudgetCategory.OTHER,)),
    ]
    for triggers, item_keywords, categories in keyword_rules:
        if any(_normalize_import_key(trigger) in keyword_text for trigger in triggers):
            keyword_match = _pick_best_keyword_cost_item(
                candidates,
                name_keywords=item_keywords,
                token_keywords=item_keywords,
                category_preferences=categories,
            )
            if keyword_match is not None:
                return keyword_match

    scored_candidates = []
    for candidate in candidates:
        overlap = set(row_tokens) & set(candidate["tokens"])
        if not overlap:
            continue
        score = 0
        for token in overlap:
            if len(token) >= 4:
                score += 4
            elif len(token) >= 2:
                score += 2
        if target_text_key and any(name_key and name_key in target_text_key for name_key in candidate["name_keys"]):
            score += 3
        if score >= 6:
            scored_candidates.append((score, len(candidate["item"].name), candidate["item"].id, candidate["item"]))
    if scored_candidates:
        scored_candidates.sort(key=lambda entry: (-entry[0], entry[1], entry[2]))
        top = scored_candidates[0]
        if len(scored_candidates) == 1 or top[0] >= scored_candidates[1][0] + 2:
            return top[3]

    return None

def _budget_category_from_import_row(row, cost_item):
    if cost_item is not None:
        mapping = {
            "labor": BudgetCategory.LABOR,
            "material": BudgetCategory.MATERIAL,
            "equip": BudgetCategory.OTHER,
            "subcon": BudgetCategory.SUBCON,
            "overhead": BudgetCategory.OTHER,
            "other": BudgetCategory.OTHER,
        }
        return mapping.get(cost_item.category, BudgetCategory.OTHER)
    labor = row.get("labor_amount") or Decimal("0")
    material = row.get("material_amount") or Decimal("0")
    expense = row.get("expense_amount") or Decimal("0")
    if labor >= material and labor >= expense and labor > 0:
        return BudgetCategory.LABOR
    if material >= labor and material >= expense and material > 0:
        return BudgetCategory.MATERIAL
    return BudgetCategory.OTHER


def _normalize_budget_baseline_category(category):
    if category in {BudgetCategory.EQUIP, BudgetCategory.OVERHEAD}:
        return BudgetCategory.OTHER
    if category in {
        BudgetCategory.MATERIAL,
        BudgetCategory.SUBCON,
        BudgetCategory.LABOR,
        BudgetCategory.OTHER,
    }:
        return category
    return BudgetCategory.OTHER


def _canonical_budget_category_for_cost_item(cost_item, current_category=None):
    normalized_current = _normalize_budget_baseline_category(
        current_category or BudgetCategory.OTHER
    )
    if cost_item is None:
        return normalized_current

    code = (cost_item.code or "").upper()
    if code == "CIVIL-PROFIT":
        return BudgetCategory.OTHER
    if code in {
        "CIVIL-EXPENSE",
        "CIVIL-EQUIPMENT",
        "CIVIL-TRANSPORT",
        "CIVIL-GENERAL-ADMIN",
        "CIVIL-SAFETY-HEALTH",
    }:
        return BudgetCategory.OTHER
    if code in {"CIVIL-LABOR", "LABOR-GENERAL"}:
        return BudgetCategory.LABOR
    if code == "CIVIL-MATERIAL":
        return BudgetCategory.MATERIAL

    if normalized_current == BudgetCategory.SUBCON:
        return BudgetCategory.SUBCON
    if normalized_current == BudgetCategory.MATERIAL:
        return BudgetCategory.MATERIAL
    if normalized_current == BudgetCategory.LABOR:
        return BudgetCategory.LABOR
    if current_category in {BudgetCategory.EQUIP, BudgetCategory.OVERHEAD}:
        return BudgetCategory.OTHER

    if cost_item.category == "labor":
        return BudgetCategory.LABOR
    if cost_item.category == "material":
        return BudgetCategory.MATERIAL
    if cost_item.category == "subcon":
        return BudgetCategory.SUBCON
    if cost_item.category in {"equip", "overhead", "other"}:
        return BudgetCategory.OTHER

    return normalized_current


def _normalize_project_budget_categories(project):
    updated = 0
    rows = BudgetItem.objects.filter(project=project).select_related("cost_item")
    for item in rows:
        desired_category = _canonical_budget_category_for_cost_item(
            item.cost_item,
            current_category=item.category,
        )
        desired_name = item.name
        code = (item.cost_item.code or "").upper()
        if code == "CIVIL-PROFIT":
            desired_name = "이윤"
        elif code == "CIVIL-EXPENSE":
            desired_name = "경비"

        update_fields = []
        if item.category != desired_category:
            item.category = desired_category
            update_fields.append("category")
        if desired_name and item.name != desired_name:
            item.name = desired_name
            update_fields.append("name")
        if update_fields:
            update_fields.append("updated_at")
            item.save(update_fields=update_fields)
            updated += 1
    return updated


def get_cost_items_for_budget_bucket(bucket):
    """Return selectable CBS for a practical contract-cost bucket.

    Intended for future field cost entry flows where the user first chooses
    노무비 / 재료비 / 경비 (and optionally 하도급) and then selects a CBS
    constrained to that bucket.
    """
    queryset = CostItem.objects.filter(is_active=True).order_by("sort_order", "name")
    if bucket == BUDGET_BUCKET_LABOR:
        return queryset.filter(category="labor").exclude(code="CIVIL-PROFIT")
    if bucket == BUDGET_BUCKET_MATERIAL:
        return queryset.filter(category="material")
    if bucket == BudgetCategory.SUBCON:
        return queryset.filter(category="subcon")
    if bucket == BUDGET_BUCKET_EXPENSE:
        return queryset.exclude(category__in=["labor", "material"])
    return queryset.none()


def _is_labor_compatible_cost_item(cost_item):
    return bool(
        cost_item
        and cost_item.category == "labor"
        and (cost_item.code or "").upper() != "CIVIL-PROFIT"
    )


def _is_material_compatible_cost_item(cost_item):
    return bool(cost_item and cost_item.category == "material")


def _is_expense_compatible_cost_item(cost_item):
    return bool(
        cost_item
        and (
            cost_item.category in {"other", "equip", "subcon"}
            or (cost_item.code or "").upper()
            in {
                "CIVIL-EXPENSE",
                "CIVIL-PROFIT",
                "CIVIL-GENERAL-ADMIN",
                "CIVIL-SAFETY-HEALTH",
            }
        )
    )


def _resolve_cost_item_for_budget_bucket(bucket, base_cost_item, candidates, row):
    """Choose a CBS suitable for an official Excel amount bucket.

    The official bucket comes from the Excel columns 노무비 / 재료비 / 경비 and
    controls the saved budget category for contract reconciliation.
    The returned CostItem is only the execution-tracking CBS used for analysis
    and later field cost reporting within that bucket.
    """
    if bucket == BUDGET_BUCKET_LABOR:
        if _is_labor_personnel_row(row.get("item_name")):
            return (
                _find_candidate_by_code(candidates, "LABOR-GENERAL")
                or _find_candidate_by_code(candidates, "CIVIL-LABOR")
                or _find_first_candidate_by_category(candidates, "labor")
            )
        if _is_labor_compatible_cost_item(base_cost_item):
            return base_cost_item
        return (
            _find_candidate_by_code(candidates, "CIVIL-LABOR")
            or _find_candidate_by_code(candidates, "LABOR-GENERAL")
            or _find_first_candidate_by_category(candidates, "labor")
        )
    if bucket == BUDGET_BUCKET_MATERIAL:
        if _is_material_compatible_cost_item(base_cost_item):
            return base_cost_item
        return (
            _find_candidate_by_code(candidates, "CIVIL-MATERIAL")
            or _find_first_candidate_by_category(candidates, "material")
        )
    if bucket == BUDGET_BUCKET_EXPENSE:
        if _is_exact_profit_row(row.get("item_name")) and (
            base_cost_item is None or (base_cost_item.code or "").upper() != "CIVIL-PROFIT"
        ):
            return None
        if _is_exact_profit_row(row.get("item_name")) and base_cost_item is not None:
            return base_cost_item
        if _is_forced_expense_row(row.get("item_name")):
            return (
                _find_candidate_by_code(candidates, "CIVIL-EXPENSE")
                or _pick_best_keyword_cost_item(
                    candidates,
                    name_keywords=("경비", "기타"),
                    token_keywords=("경비", "기타"),
                    category_preferences=(BudgetCategory.OTHER,),
                )
                or _find_first_candidate_by_category(candidates, "other")
            )
        if _is_expense_compatible_cost_item(base_cost_item):
            return base_cost_item
        return (
            _find_candidate_by_code(candidates, "CIVIL-EXPENSE")
            or _find_first_candidate_by_category(candidates, "other")
            or _find_first_candidate_by_category(candidates, "equip")
            or _find_first_candidate_by_category(candidates, "subcon")
        )
    return base_cost_item


def _row_has_bucket_breakdown(row):
    return any(
        Decimal(str(row.get(field_name) or 0)) > 0
        for field_name in ("labor_amount", "material_amount", "expense_amount")
    )


def _make_budget_bucket_note(row, bucket, bucket_amount):
    parts = [
        f"\uc6d0\ubcf8\ud589\ubc88\ud638:{row.get('source_row_no') or row.get('row_no') or row.get('row_number') or '-'}",
        f"WBS\ucf54\ub4dc:{row.get('wbs_code') or '-'}",
        f"WBS\uba85:{row.get('wbs_name') or '-'}",
        f"CBS\ucf54\ub4dc:{row.get('cbs_code') or '-'}",
        f"CBS\uba85:{row.get('cbs_name') or '-'}",
        f"원본:{row.get('sheet_name') or '-'}:{row.get('row_no') or row.get('row_number') or '-'}",
        f"품명:{row.get('item_name') or '-'}",
    ]
    if row.get("spec"):
        parts.append(f"규격:{row['spec']}")
    if row.get("quantity") is not None:
        parts.append(f"수량:{row['quantity']}")
    if row.get("unit"):
        parts.append(f"단위:{row['unit']}")
    if row.get("unit_price") is not None:
        parts.append(f"단가:{row['unit_price']}")
    if row.get("amount") is not None:
        parts.append(f"도급금액:{row['amount']}")
    parts.append(f"버킷:{BUDGET_BUCKET_LABELS[bucket]}")
    parts.append(f"버킷금액:{bucket_amount}")
    return " / ".join(parts)


def _make_budget_review_key(source_import_key, bucket):
    return f"{source_import_key}::{bucket}"


def _build_budget_review_row(row, entry):
    cost_item = entry.get("cost_item")
    cost_item_id = getattr(cost_item, "id", None)
    cost_item_label = str(cost_item) if cost_item_id else ""
    return {
        "review_key": _make_budget_review_key(row["import_key"], entry["bucket"]),
        "source_import_key": row["import_key"],
        "source_row_no": row.get("source_row_no") or row.get("row_no") or row.get("row_number") or "",
        "source_sheet_name": row.get("sheet_name") or "",
        "source_wbs_code": row.get("wbs_code") or "",
        "source_wbs_name": row.get("wbs_name") or "",
        "source_cbs_code": row.get("cbs_code") or "",
        "source_cbs_name": row.get("cbs_name") or "",
        "source_item_name": row.get("item_name") or "",
        "source_spec": row.get("spec") or "",
        "bucket": entry["bucket"],
        "source_bucket": entry["bucket"],
        "category": entry["category"],
        "source_category": entry["category"],
        "category_label": BUDGET_BASELINE_CATEGORY_LABELS.get(entry["category"], entry["category"]),
        "cost_item_id": cost_item_id,
        "cost_item_label": cost_item_label,
        "name": entry["name"],
        "planned_amount": int(entry["planned_amount"] or 0),
        "source_planned_amount": int(entry["planned_amount"] or 0),
        "note": entry["note"],
        "status": "자동 매칭" if cost_item_id else "수동 확인 필요",
        "match_source": entry.get("match_source") or "auto",
        "match_status": row.get("match_status") or "AUTO_MATCH",
        "match_reason": row.get("match_reason") or "",
        "is_excluded": False,
        "warnings": list(entry.get("warnings") or []),
    }


def _validate_budget_review_cost_item(cost_item_id, selectable_items):
    if not cost_item_id:
        return None
    try:
        return selectable_items[int(cost_item_id)]
    except (KeyError, TypeError, ValueError):
        return None


def _apply_budget_review_adjustments(review_rows, adjustments, selectable_items):
    errors = []
    allowed_categories = {
        BudgetCategory.MATERIAL,
        BudgetCategory.SUBCON,
        BudgetCategory.LABOR,
        BudgetCategory.OTHER,
    }
    for row in review_rows:
        adjustment = adjustments.get(row["review_key"])
        if not adjustment:
            continue
        row["is_excluded"] = bool(adjustment.get("exclude"))

        requested_category = adjustment.get("category") or row["category"]
        if requested_category not in allowed_categories:
            errors.append(f"{row['source_item_name'] or '예산 행'}: 비목을 확인해 주세요.")
        else:
            row["category"] = requested_category
            row["category_label"] = BUDGET_BASELINE_CATEGORY_LABELS.get(
                requested_category, requested_category
            )

        requested_cost_item = _validate_budget_review_cost_item(
            adjustment.get("cost_item_id"),
            selectable_items,
        )
        if adjustment.get("cost_item_id") and requested_cost_item is None:
            errors.append(f"{row['source_item_name'] or '예산 행'}: CBS를 확인해 주세요.")
        elif requested_cost_item is not None:
            row["cost_item_id"] = requested_cost_item.id
            row["cost_item_label"] = str(requested_cost_item)
            row["match_source"] = "manual_review"
            row["status"] = "상세 조정"

        requested_name = (adjustment.get("name") or "").strip()
        if requested_name:
            row["name"] = requested_name

        requested_amount = adjustment.get("planned_amount")
        if requested_amount not in ("", None):
            amount = _coerce_optional_decimal(requested_amount)
            if amount is None or amount < 0:
                errors.append(f"{row['source_item_name'] or '예산 행'}: 예산금액을 확인해 주세요.")
            else:
                row["planned_amount"] = int(amount)
                if int(amount) != int(row.get("source_planned_amount") or 0):
                    note = row.get("note") or ""
                    if "사용자 조정금액" not in note:
                        row["note"] = f"{note} / 사용자 조정금액".strip(" /")

        requested_note = (adjustment.get("note") or "").strip()
        if requested_note:
            row["note"] = requested_note
        row["alias_save"] = bool(adjustment.get("alias_save"))
    return errors


def _build_budget_reconciliation_candidates_from_review_rows(review_rows):
    candidates = []
    for row in review_rows:
        source_amount = Decimal(str(row.get("source_planned_amount") or 0))
        current_amount = Decimal(str(row.get("planned_amount") or 0))
        if row.get("is_excluded"):
            candidates.append(
                {
                    "bucket": row["source_bucket"],
                    "bucket_label": BUDGET_BUCKET_LABELS.get(row["source_bucket"], row["source_bucket"]),
                    "item_name": row["source_item_name"],
                    "row_ref": f"{row['source_sheet_name'] or '-'}:{row['source_row_no'] or '-'}",
                    "amount": source_amount,
                    "difference": source_amount,
                    "status": "제외",
                    "cause": "사용자가 상세 조정에서 제외했습니다.",
                }
            )
            continue
        if row.get("cost_item_id") in (None, ""):
            candidates.append(
                {
                    "bucket": row["source_bucket"],
                    "bucket_label": BUDGET_BUCKET_LABELS.get(row["source_bucket"], row["source_bucket"]),
                    "item_name": row["source_item_name"],
                    "row_ref": f"{row['source_sheet_name'] or '-'}:{row['source_row_no'] or '-'}",
                    "amount": current_amount,
                    "difference": current_amount,
                    "status": (
                        "수동 매핑 필요"
                        if row.get("match_source") == "manual_required"
                        else (row.get("status") or "수동 확인 필요")
                    ),
                    "cause": "CBS를 선택해 주세요.",
                }
            )
            continue
        if row["category"] != row["source_category"]:
            amount_difference = abs(source_amount - current_amount)
            candidates.append(
                {
                    "bucket": row["source_bucket"],
                    "bucket_label": BUDGET_BUCKET_LABELS.get(row["source_bucket"], row["source_bucket"]),
                    "item_name": row["source_item_name"],
                    "row_ref": f"{row['source_sheet_name'] or '-'}:{row['source_row_no'] or '-'}",
                    "amount": current_amount,
                    "difference": amount_difference if amount_difference else current_amount,
                    "status": "비목 조정",
                    "cause": f"원본 비목 {BUDGET_BASELINE_CATEGORY_LABELS.get(row['source_category'], row['source_category'])} → 현재 비목 {row['category_label']}",
                }
            )
        elif int(row.get("planned_amount") or 0) != int(row.get("source_planned_amount") or 0):
            candidates.append(
                {
                    "bucket": row["source_bucket"],
                    "bucket_label": BUDGET_BUCKET_LABELS.get(row["source_bucket"], row["source_bucket"]),
                    "item_name": row["source_item_name"],
                    "row_ref": f"{row['source_sheet_name'] or '-'}:{row['source_row_no'] or '-'}",
                    "amount": current_amount,
                    "difference": abs(source_amount - current_amount),
                    "status": "금액 조정",
                    "cause": f"원본 {row['source_planned_amount']} → 현재 {row['planned_amount']}",
                }
            )
    candidates.sort(
        key=lambda item: (Decimal(str(item.get("amount") or 0)), item.get("row_ref") or ""),
        reverse=True,
    )
    return candidates[:20]


def _build_budget_form_initial_from_review_rows(review_rows, *, aggregate=False):
    if aggregate:
        aggregated = {}
        for row in review_rows:
            if row.get("is_excluded") or not row.get("cost_item_id"):
                continue
            key = (
                row["cost_item_id"],
                row["category"],
                row["name"],
            )
            bucket = aggregated.setdefault(
                key,
                {
                    "category": row["category"],
                    "cost_item": row["cost_item_id"],
                    "name": row["name"],
                    "planned_amount": 0,
                    "note_parts": [],
                },
            )
            bucket["planned_amount"] += int(row.get("planned_amount") or 0)
            note = row.get("note") or ""
            if note and note not in bucket["note_parts"]:
                bucket["note_parts"].append(note)
        return [
            {
                "category": item["category"],
                "cost_item": item["cost_item"],
                "name": item["name"],
                "planned_amount": item["planned_amount"],
                "note": " ; ".join(item["note_parts"]),
            }
            for item in aggregated.values()
        ]

    initial = []
    for row in review_rows:
        if row.get("is_excluded") or not row.get("cost_item_id"):
            continue
        initial.append(
            {
                "category": row["category"],
                "cost_item": row["cost_item_id"],
                "name": row["name"],
                "planned_amount": row["planned_amount"],
                "note": row.get("note") or "",
            }
        )
    return initial


def _split_import_row_by_work_item_buckets(row, base_cost_item, candidates):
    """Split one Excel detail row into official contract buckets.

    category is authoritative from the Excel amount column:
    - labor_amount -> LABOR / 노무비
    - material_amount -> MATERIAL / 재료비
    - expense_amount -> OTHER / 경비

    The resolved CostItem is the CBS used for execution tracking inside the
    bucket and must not override the official bucket category.
    """
    if row.get("match_status") == "UNMATCHED_CBS" and base_cost_item is None:
        return []

    entries = []
    for bucket, amount_field in BUDGET_BUCKET_AMOUNT_FIELDS.items():
        category = BUDGET_BUCKET_CATEGORIES[bucket]
        amount = Decimal(str(row.get(amount_field) or 0))
        if amount <= 0:
            continue
        cost_item = _resolve_cost_item_for_budget_bucket(
            bucket,
            base_cost_item,
            candidates,
            row,
        )
        if cost_item is None:
            continue
        if bucket == BUDGET_BUCKET_EXPENSE and _is_exact_profit_row(row.get("item_name")):
            name = f"{row.get('item_name') or cost_item.name} - {BUDGET_BUCKET_LABELS[bucket]}"
        elif bucket == BUDGET_BUCKET_MATERIAL and _is_material_compatible_cost_item(base_cost_item):
            name = f"{row.get('item_name') or cost_item.name} - {BUDGET_BUCKET_LABELS[bucket]}"
        elif bucket == BUDGET_BUCKET_LABOR and _is_labor_personnel_row(row.get('item_name')):
            name = f"{row.get('item_name') or cost_item.name} - {BUDGET_BUCKET_LABELS[bucket]}"
        else:
            name = f"{cost_item.name} - {BUDGET_BUCKET_LABELS[bucket]}"
        entries.append(
            {
                "bucket": bucket,
                "category": category,
                "cost_item": cost_item,
                "name": name,
                "planned_amount": int(amount),
                "source_row": row,
                "note": _make_budget_bucket_note(row, bucket, amount),
            }
        )
    return entries


def _budget_note_from_import_row(row, *, bucket=None, bucket_amount=None):
    parts = []
    if row.get("code"):
        parts.append(f"코드:{row['code']}")
    if row.get("hierarchy"):
        parts.append(f"계층:{row['hierarchy']}")
    if row.get("spec"):
        parts.append(f"규격:{row['spec']}")
    if row.get("quantity") is not None:
        parts.append(f"수량:{row['quantity']}")
    if row.get("unit"):
        parts.append(f"단위:{row['unit']}")
    if row.get("unit_price") is not None:
        parts.append(f"단가:{row['unit_price']}")
    if row.get("labor_amount") is not None:
        parts.append(f"노무비:{row['labor_amount']}")
    if row.get("material_amount") is not None:
        parts.append(f"재료비:{row['material_amount']}")
    if row.get("expense_amount") is not None:
        parts.append(f"경비:{row['expense_amount']}")
    if bucket:
        parts.append(f"버킷:{BUDGET_BUCKET_LABELS.get(bucket, bucket)}")
    if bucket_amount is not None:
        parts.append(f"버킷금액:{bucket_amount}")
    return " / ".join(parts)


def _build_budget_initial_from_import_rows(rows, *, manual_mapping=None, manual_adjustments=None):
    manual_mapping = manual_mapping or {}
    manual_adjustments = manual_adjustments or {}
    cost_items = list(CostItem.objects.prefetch_related("aliases").all().order_by("sort_order", "name"))
    aggregated = {}
    review_rows = []
    warnings = []
    candidates = _build_import_cost_item_candidates(cost_items)
    matched_row_count = 0
    manual_matched_row_count = 0
    unmatched_row_count = 0
    unmatched_details = []
    source_upload_target_row_count = 0
    skipped_row_count = 0
    skipped_section_row_count = 0
    unmatched_labels = []
    imported_total_amount = Decimal("0")
    matched_total_amount = Decimal("0")
    detail_labor_total_amount = Decimal("0")
    detail_material_total_amount = Decimal("0")
    detail_expense_total_amount = Decimal("0")
    manual_required_labor_amount = Decimal("0")
    manual_required_material_amount = Decimal("0")
    manual_required_expense_amount = Decimal("0")
    unmapped_labor_amount = Decimal("0")
    unmapped_material_amount = Decimal("0")
    unmapped_expense_amount = Decimal("0")
    manual_required_row_count = 0
    bucket_reconciliation_candidates = []
    owner_supplied_amount = Decimal("0")
    owner_supplied_row_count = 0
    total_construction_amount = Decimal("0")
    explicit_total_construction_amount = None

    for index, row in enumerate(rows):
        row["import_key"] = row.get("import_key") or _make_budget_import_key(row, index)

    parent_row_keys = _mark_budget_import_parent_rows(rows)
    owner_supplied_info = _detect_owner_supplied_row_keys(rows)
    owner_supplied_row_keys = owner_supplied_info["row_keys"]
    owner_supplied_root_keys = owner_supplied_info["root_keys"]
    owner_supplied_amount = owner_supplied_info["amount"]
    owner_supplied_row_count = owner_supplied_info["row_count"]

    selectable_items = {candidate["item"].id: candidate["item"] for candidate in candidates}

    for row in rows:
        row["is_skipped"] = False
        row["is_parent_summary"] = False
        row["matched_cost_item_id"] = None
        row["match_source"] = ""
        row["match_status"] = ""
        row["match_reason"] = ""
        row["budget_scope"] = "CONTRACT"
        row["skip_reason"] = ""
        row["is_owner_supplied"] = False
        row["requires_manual_profit_mapping"] = False
        row["selected_cost_item_id"] = str(manual_mapping.get(row["import_key"], "") or "")
        row["official_bucket_entries"] = []

        row_amount = Decimal(str(row.get("amount") or 0))
        if _normalize_import_key(row.get("item_name")) == _normalize_import_key("총공사비") and row_amount > 0:
            explicit_total_construction_amount = row_amount

        if row.get("import_key") in owner_supplied_row_keys:
            skipped_row_count += 1
            skipped_section_row_count += 1
            row["is_skipped"] = True
            row["is_parent_summary"] = row.get("import_key") in owner_supplied_root_keys
            row["is_owner_supplied"] = True
            row["budget_scope"] = "OWNER_SUPPLIED"
            row["skip_reason"] = "관급자재 참고항목"
            row["warnings"] = list(row.get("warnings") or [])
            continue

        should_skip, is_section_row = _should_skip_budget_import_row(
            row,
            parent_row_keys=parent_row_keys,
        )
        if should_skip:
            skipped_row_count += 1
            if is_section_row:
                skipped_section_row_count += 1
                row["is_parent_summary"] = True
            row["is_skipped"] = True
            row["skip_reason"] = "자동 제외"
            row["warnings"] = list(row.get("warnings") or [])
            continue

        imported_total_amount += row_amount
        source_upload_target_row_count += 1

        manual_cost_item = None
        manual_cost_item_id = manual_mapping.get(row["import_key"])
        if manual_cost_item_id:
            try:
                manual_cost_item = selectable_items[int(manual_cost_item_id)]
            except (KeyError, TypeError, ValueError):
                manual_cost_item = None
        row_warnings = list(row.get("warnings") or [])

        def add_bucket_candidate(bucket, amount, status, cause):
            if amount is None or Decimal(str(amount or 0)) <= 0:
                return
            bucket_reconciliation_candidates.append(
                {
                    "bucket": bucket,
                    "bucket_label": BUDGET_BUCKET_LABELS[bucket],
                    "item_name": row.get("item_name") or row.get("code") or "예산 행",
                    "row_ref": f"{row.get('sheet_name') or '-'}:{row.get('row_no') or row.get('row_number') or '-'}",
                    "amount": Decimal(str(amount)),
                    "status": status,
                    "cause": cause,
                }
            )

        if (
            manual_cost_item is not None
            and manual_cost_item.code == "CIVIL-PROFIT"
            and not _is_exact_profit_row(row.get("item_name"))
        ):
            row_warnings.append(
                "이윤 CBS는 Excel 항목명이 '이윤'인 행에만 사용할 수 있습니다."
            )
            manual_cost_item = None

        cost_item = manual_cost_item or _match_cost_item_for_import_row(row, cost_items, candidates)
        if manual_cost_item is not None:
            row["match_status"] = "MANUAL"
            row["match_reason"] = "\uc0ac\uc6a9\uc790 \uc218\ub3d9 CBS \ub9e4\ud551"
        if cost_item is None:
            if _row_has_bucket_breakdown(row):
                split_entries = _split_import_row_by_work_item_buckets(
                    row,
                    manual_cost_item,
                    candidates,
                )
                generated_buckets = set()
                if split_entries:
                    matched_row_count += 1
                    row["match_source"] = "manual" if manual_cost_item is not None else "auto"
                    row["matched_cost_item_id"] = split_entries[0]["cost_item"].id
                    if manual_cost_item is not None:
                        manual_matched_row_count += 1
                    matched_total_amount += sum(
                        Decimal(str(entry["planned_amount"] or 0))
                        for entry in split_entries
                    )
                    for entry in split_entries:
                        generated_buckets.add(entry["bucket"])
                        row["official_bucket_entries"].append(
                            {
                                "bucket": entry["bucket"],
                                "bucket_label": BUDGET_BUCKET_LABELS[entry["bucket"]],
                                "amount": Decimal(str(entry["planned_amount"])),
                                "cost_item_id": entry["cost_item"].id,
                            }
                        )
                        if entry["bucket"] == BUDGET_BUCKET_LABOR:
                            detail_labor_total_amount += Decimal(str(entry["planned_amount"]))
                        elif entry["bucket"] == BUDGET_BUCKET_MATERIAL:
                            detail_material_total_amount += Decimal(str(entry["planned_amount"]))
                        else:
                            detail_expense_total_amount += Decimal(str(entry["planned_amount"]))
                        aggregate_key = (
                            entry["cost_item"].id,
                            entry["category"],
                            entry["bucket"],
                            entry["name"],
                        )
                        bucket = aggregated.setdefault(
                            aggregate_key,
                            {
                                "cost_item": entry["cost_item"],
                                "category": entry["category"],
                                "bucket": entry["bucket"],
                                "name_override": (
                                    "경비"
                                    if entry["cost_item"].code == "CIVIL-EXPENSE"
                                    and entry["bucket"] == BUDGET_BUCKET_EXPENSE
                                    and _is_forced_expense_row(row.get("item_name"))
                                    else entry["name"]
                                ),
                                "planned_amount": 0,
                                "rows": [],
                            },
                        )
                        bucket["planned_amount"] += int(entry["planned_amount"] or 0)
                        bucket["rows"].append(entry)
                for bucket, amount_field in BUDGET_BUCKET_AMOUNT_FIELDS.items():
                    bucket_amount = Decimal(str(row.get(amount_field) or 0))
                    if bucket_amount <= 0 or bucket in generated_buckets:
                        continue
                    if bucket == BUDGET_BUCKET_EXPENSE and _is_exact_profit_row(row.get("item_name")):
                        manual_required_expense_amount += bucket_amount
                        manual_required_row_count += 1
                        row["requires_manual_profit_mapping"] = True
                        add_bucket_candidate(
                            bucket,
                            bucket_amount,
                            "수동 매핑 필요",
                            PROFIT_MANUAL_MAPPING_WARNING,
                        )
                        review_rows.append(
                            _build_budget_review_row(
                                row,
                                {
                                    "bucket": bucket,
                                    "category": BUDGET_BUCKET_CATEGORIES[bucket],
                                    "cost_item": None,
                                    "name": f"{row.get('item_name') or '예산 행'} - {BUDGET_BUCKET_LABELS[bucket]}",
                                    "planned_amount": int(bucket_amount),
                                    "note": _make_budget_bucket_note(row, bucket, bucket_amount),
                                    "match_source": "manual_required",
                                    "warnings": [PROFIT_MANUAL_MAPPING_WARNING],
                                },
                            )
                        )
                    else:
                        if bucket == BUDGET_BUCKET_LABOR:
                            unmapped_labor_amount += bucket_amount
                        elif bucket == BUDGET_BUCKET_MATERIAL:
                            unmapped_material_amount += bucket_amount
                        else:
                            unmapped_expense_amount += bucket_amount
                        add_bucket_candidate(
                            bucket,
                            bucket_amount,
                            "매핑 누락",
                            f"{BUDGET_BUCKET_LABELS[bucket]} CBS를 자동 결정하지 못했습니다.",
                        )
                        review_rows.append(
                            _build_budget_review_row(
                                row,
                                {
                                    "bucket": bucket,
                                    "category": BUDGET_BUCKET_CATEGORIES[bucket],
                                    "cost_item": None,
                                    "name": f"{row.get('item_name') or '예산 행'} - {BUDGET_BUCKET_LABELS[bucket]}",
                                    "planned_amount": int(bucket_amount),
                                    "note": _make_budget_bucket_note(row, bucket, bucket_amount),
                                    "match_source": "unmatched",
                                    "warnings": [f"{BUDGET_BUCKET_LABELS[bucket]} CBS를 자동 결정하지 못했습니다."],
                                },
                            )
                        )
                if generated_buckets:
                    if (
                        _is_exact_profit_row(row.get("item_name"))
                        and BUDGET_BUCKET_EXPENSE not in generated_buckets
                    ):
                        row_warnings.append(
                            PROFIT_MANUAL_MAPPING_WARNING
                        )
                    elif len(generated_buckets) < sum(
                        1
                        for field_name in BUDGET_BUCKET_AMOUNT_FIELDS.values()
                        if Decimal(str(row.get(field_name) or 0)) > 0
                    ):
                        row_warnings.append("일부 비목은 수동 확인이 필요합니다.")
                else:
                    if row.get("requires_manual_profit_mapping"):
                        row_warnings.append(
                            PROFIT_MANUAL_MAPPING_WARNING
                        )
                    else:
                        row_warnings.append(
                            row.get("match_reason") or "CBS \uc790\ub3d9 \ub9e4\uce6d\uc774 \ud544\uc694\ud569\ub2c8\ub2e4."
                        )
                    unmatched_row_count += 1
                    unmatched_labels.append(
                        row.get("item_name") or row.get("code") or "예산 행"
                    )
            else:
                if row.get("requires_manual_profit_mapping"):
                    row_warnings.append(
                        PROFIT_MANUAL_MAPPING_WARNING
                    )
                    manual_required_expense_amount += Decimal(str(row.get("expense_amount") or row.get("amount") or 0))
                    manual_required_row_count += 1
                    profit_amount = Decimal(str(row.get("expense_amount") or row.get("amount") or 0))
                    add_bucket_candidate(
                        BUDGET_BUCKET_EXPENSE,
                        profit_amount,
                        "수동 매핑 필요",
                        PROFIT_MANUAL_MAPPING_WARNING,
                    )
                    review_rows.append(
                        _build_budget_review_row(
                            row,
                            {
                                "bucket": BUDGET_BUCKET_EXPENSE,
                                "category": BudgetCategory.OTHER,
                                "cost_item": None,
                                "name": f"{row.get('item_name') or '예산 행'} - {BUDGET_BUCKET_LABELS[BUDGET_BUCKET_EXPENSE]}",
                                "planned_amount": int(profit_amount),
                                "note": _make_budget_bucket_note(row, BUDGET_BUCKET_EXPENSE, profit_amount),
                                "match_source": "manual_required",
                                "warnings": [PROFIT_MANUAL_MAPPING_WARNING],
                            },
                        )
                    )
                else:
                    row_warnings.append(
                        row.get("match_reason") or "CBS \uc790\ub3d9 \ub9e4\uce6d\uc774 \ud544\uc694\ud569\ub2c8\ub2e4."
                    )
                unmatched_row_count += 1
                unmatched_labels.append(
                    row.get("item_name") or row.get("code") or "예산 행"
                )
        else:
            if cost_item.code == "CIVIL-PROFIT" and not _is_exact_profit_row(row.get("item_name")):
                row_warnings.append("이윤 CBS에는 이윤 항목만 포함할 수 있습니다.")
                row["matched_cost_item_id"] = None
                row["selected_cost_item_id"] = str(cost_item.id)
                row["match_source"] = ""
                unmatched_row_count += 1
                unmatched_labels.append(
                    row.get("item_name") or row.get("code") or "예산 행"
                )
                row["warnings"] = row_warnings
                continue
            matched_row_count += 1
            row["matched_cost_item_id"] = cost_item.id
            row["selected_cost_item_id"] = str(cost_item.id)
            row["match_source"] = "manual" if manual_cost_item is not None else "auto"
            if manual_cost_item is not None:
                manual_matched_row_count += 1
            if _row_has_bucket_breakdown(row):
                split_entries = _split_import_row_by_work_item_buckets(
                    row,
                    cost_item,
                    candidates,
                )
                if split_entries:
                    matched_total_amount += sum(
                        Decimal(str(entry["planned_amount"] or 0))
                        for entry in split_entries
                    )
                    for entry in split_entries:
                        row["official_bucket_entries"].append(
                            {
                                "bucket": entry["bucket"],
                                "bucket_label": BUDGET_BUCKET_LABELS[entry["bucket"]],
                                "amount": Decimal(str(entry["planned_amount"])),
                                "cost_item_id": entry["cost_item"].id,
                            }
                        )
                        if entry["bucket"] == BUDGET_BUCKET_LABOR:
                            detail_labor_total_amount += Decimal(str(entry["planned_amount"]))
                        elif entry["bucket"] == BUDGET_BUCKET_MATERIAL:
                            detail_material_total_amount += Decimal(str(entry["planned_amount"]))
                        else:
                            detail_expense_total_amount += Decimal(str(entry["planned_amount"]))
                        aggregate_key = (
                            entry["cost_item"].id,
                            entry["category"],
                            entry["bucket"],
                            entry["name"],
                        )
                        bucket = aggregated.setdefault(
                            aggregate_key,
                            {
                                "cost_item": entry["cost_item"],
                                "category": entry["category"],
                                "bucket": entry["bucket"],
                                "name_override": (
                                    "경비"
                                    if entry["cost_item"].code == "CIVIL-EXPENSE"
                                    and entry["bucket"] == BUDGET_BUCKET_EXPENSE
                                    and _is_forced_expense_row(row.get("item_name"))
                                    else entry["name"]
                                ),
                                "planned_amount": 0,
                                "rows": [],
                            },
                        )
                        bucket["planned_amount"] += int(entry["planned_amount"] or 0)
                        bucket["rows"].append(entry)
                        review_rows.append(
                            _build_budget_review_row(
                                row,
                                {
                                    **entry,
                                    "match_source": row["match_source"],
                                },
                            )
                        )
                    for bucket, amount_field in BUDGET_BUCKET_AMOUNT_FIELDS.items():
                        bucket_amount = Decimal(str(row.get(amount_field) or 0))
                        if bucket_amount <= 0:
                            continue
                        if not any(entry["bucket"] == bucket for entry in split_entries):
                            if bucket == BUDGET_BUCKET_EXPENSE and _is_exact_profit_row(row.get("item_name")):
                                manual_required_expense_amount += bucket_amount
                                manual_required_row_count += 1
                                row["requires_manual_profit_mapping"] = True
                                add_bucket_candidate(
                                    bucket,
                                    bucket_amount,
                                    "수동 매핑 필요",
                                    PROFIT_MANUAL_MAPPING_WARNING,
                                )
                                review_rows.append(
                                    _build_budget_review_row(
                                        row,
                                        {
                                            "bucket": bucket,
                                            "category": BUDGET_BUCKET_CATEGORIES[bucket],
                                            "cost_item": None,
                                            "name": f"{row.get('item_name') or '예산 행'} - {BUDGET_BUCKET_LABELS[bucket]}",
                                            "planned_amount": int(bucket_amount),
                                            "note": _make_budget_bucket_note(row, bucket, bucket_amount),
                                            "match_source": "manual_required",
                                            "warnings": [PROFIT_MANUAL_MAPPING_WARNING],
                                        },
                                    )
                                )
                            else:
                                if bucket == BUDGET_BUCKET_LABOR:
                                    unmapped_labor_amount += bucket_amount
                                elif bucket == BUDGET_BUCKET_MATERIAL:
                                    unmapped_material_amount += bucket_amount
                                else:
                                    unmapped_expense_amount += bucket_amount
                                add_bucket_candidate(
                                    bucket,
                                    bucket_amount,
                                    "매핑 누락",
                                    f"{BUDGET_BUCKET_LABELS[bucket]} CBS를 자동 결정하지 못했습니다.",
                                )
                                review_rows.append(
                                    _build_budget_review_row(
                                        row,
                                        {
                                            "bucket": bucket,
                                            "category": BUDGET_BUCKET_CATEGORIES[bucket],
                                            "cost_item": None,
                                            "name": f"{row.get('item_name') or '예산 행'} - {BUDGET_BUCKET_LABELS[bucket]}",
                                            "planned_amount": int(bucket_amount),
                                            "note": _make_budget_bucket_note(row, bucket, bucket_amount),
                                            "match_source": "unmatched",
                                            "warnings": [f"{BUDGET_BUCKET_LABELS[bucket]} CBS를 자동 결정하지 못했습니다."],
                                        },
                                    )
                                )
                else:
                    row_warnings.append(
                        "노무비/재료비/경비 분해 금액이 없어 기존 CBS 기준으로 처리했습니다."
                    )
            else:
                row_warnings.append(
                    "노무비/재료비/경비 분해 금액이 없어 기존 CBS 기준으로 처리했습니다."
                )
                matched_total_amount += row_amount
                aggregate_key = (cost_item.id, _budget_category_from_import_row(row, cost_item), "SINGLE")
                bucket = aggregated.setdefault(
                    aggregate_key,
                    {
                        "cost_item": cost_item,
                        "category": _budget_category_from_import_row(row, cost_item),
                        "bucket": "SINGLE",
                        "name_override": "경비" if cost_item.code == "CIVIL-EXPENSE" else "",
                        "planned_amount": 0,
                        "rows": [],
                    },
                )
                bucket["planned_amount"] += int(row.get("amount") or 0)
                bucket["rows"].append(
                    {
                        "source_row": row,
                        "bucket": "SINGLE",
                        "planned_amount": int(row.get("amount") or 0),
                        "note": _budget_note_from_import_row(row),
                    }
                )
                review_rows.append(
                    {
                        "review_key": _make_budget_review_key(row["import_key"], "SINGLE"),
                        "source_import_key": row["import_key"],
                        "source_row_no": row.get("row_no") or row.get("row_number") or "",
                        "source_sheet_name": row.get("sheet_name") or "",
                        "source_item_name": row.get("item_name") or "",
                        "source_spec": row.get("spec") or "",
                        "bucket": "SINGLE",
                        "source_bucket": "SINGLE",
                        "category": _budget_category_from_import_row(row, cost_item),
                        "source_category": _budget_category_from_import_row(row, cost_item),
                        "category_label": BUDGET_BASELINE_CATEGORY_LABELS.get(_budget_category_from_import_row(row, cost_item), _budget_category_from_import_row(row, cost_item)),
                        "cost_item_id": cost_item.id,
                        "cost_item_label": str(cost_item),
                        "name": cost_item.name,
                        "planned_amount": int(row.get("amount") or 0),
                        "source_planned_amount": int(row.get("amount") or 0),
                        "note": _budget_note_from_import_row(row),
                        "status": "자동 매칭",
                        "match_source": row["match_source"],
                        "is_excluded": False,
                        "warnings": [],
                    }
                )
        row["warnings"] = row_warnings
        if row.get("match_status") == "UNMATCHED_CBS":
            unmatched_details.append(
                {
                    "source_row_no": row.get("source_row_no") or row.get("row_no") or row.get("row_number") or "",
                    "wbs_code": row.get("wbs_code") or "",
                    "wbs_name": row.get("wbs_name") or "",
                    "cbs_code": row.get("cbs_code") or "",
                    "cbs_name": row.get("cbs_name") or "",
                    "item_name": row.get("item_name") or "",
                    "amount": row_amount,
                    "reason": row.get("match_reason") or "CBS \ubbf8\ub9e4\uce6d",
                    "action": "CBS \ub9c8\uc2a4\ud130 \ub4f1\ub85d \ub610\ub294 \uc218\ub3d9 \ub9e4\ud551",
                }
            )

    total_construction_amount = explicit_total_construction_amount or (
        imported_total_amount + owner_supplied_amount
    )
    review_errors = _apply_budget_review_adjustments(
        review_rows,
        manual_adjustments,
        selectable_items,
    )
    bucket_reconciliation_candidates = _build_budget_reconciliation_candidates_from_review_rows(
        review_rows
    )
    bucket_reconciliation_candidates.sort(
        key=lambda item: (Decimal(str(item.get("amount") or 0)), item.get("row_ref") or ""),
        reverse=True,
    )

    if unmatched_row_count > 30:
        warnings.append(
            f"CBS 미매칭 {unmatched_row_count}건 중 30건만 표시합니다."
        )
    label_counter = Counter(unmatched_labels)
    displayed = 0
    detail_limit = 29 if unmatched_row_count > 30 else 30
    for label in unmatched_labels:
        if displayed >= detail_limit:
            break
        count = label_counter.get(label, 0)
        if count <= 0:
            continue
        if count == 1:
            warnings.append(
                f"CBS 미매칭으로 예산 입력표에서는 제외되었습니다: {label}"
            )
        else:
            warnings.append(
                f"CBS 미매칭으로 예산 입력표에서는 제외되었습니다: {label} 외 {count - 1}건"
            )
        displayed += 1
        label_counter[label] = 0

    initial = _build_budget_form_initial_from_review_rows(
        review_rows,
        aggregate=(BUDGET_IMPORT_SAVE_MODE != "SOURCE_ROW_BUCKET"),
    )

    generated_labor_amount = Decimal("0")
    generated_material_amount = Decimal("0")
    generated_subcontract_amount = Decimal("0")
    generated_expense_amount = Decimal("0")
    manual_required_labor_amount = Decimal("0")
    manual_required_material_amount = Decimal("0")
    manual_required_expense_amount = Decimal("0")
    unmapped_labor_amount = Decimal("0")
    unmapped_material_amount = Decimal("0")
    unmapped_expense_amount = Decimal("0")
    manual_required_row_count = 0
    excluded_amount = Decimal("0")
    for review_row in review_rows:
        amount = Decimal(str(review_row.get("planned_amount") or 0))
        if review_row.get("is_excluded"):
            excluded_amount += amount
            continue
        if not review_row.get("cost_item_id"):
            if review_row.get("match_source") == "manual_required":
                manual_required_row_count += 1
                if review_row["category"] == BudgetCategory.LABOR:
                    manual_required_labor_amount += amount
                elif review_row["category"] == BudgetCategory.MATERIAL:
                    manual_required_material_amount += amount
                else:
                    manual_required_expense_amount += amount
            else:
                if review_row["category"] == BudgetCategory.LABOR:
                    unmapped_labor_amount += amount
                elif review_row["category"] == BudgetCategory.MATERIAL:
                    unmapped_material_amount += amount
                else:
                    unmapped_expense_amount += amount
            continue
        if review_row["category"] == BudgetCategory.LABOR:
            generated_labor_amount += amount
        elif review_row["category"] == BudgetCategory.MATERIAL:
            generated_material_amount += amount
        elif review_row["category"] == BudgetCategory.SUBCON:
            generated_subcontract_amount += amount
        else:
            generated_expense_amount += amount

    stats = {
        "budget_import_total_rows": len(rows),
        "budget_import_source_upload_target_rows": source_upload_target_row_count,
        "budget_import_matched_rows": matched_row_count,
        "budget_import_auto_matched_rows": max(matched_row_count - manual_matched_row_count, 0),
        "budget_import_manual_matched_rows": manual_matched_row_count,
        "budget_import_unmatched_rows": unmatched_row_count,
        "budget_import_unmatched_details": unmatched_details,
        "budget_import_skipped_rows": skipped_row_count,
        "budget_import_skipped_section_rows": skipped_section_row_count,
        "budget_form_initial_count": len(initial),
        "budget_import_total_amount": imported_total_amount,
        "budget_import_contract_scope_amount": imported_total_amount,
        "budget_import_detail_labor_amount": generated_labor_amount,
        "budget_import_detail_material_amount": generated_material_amount,
        "budget_import_detail_expense_amount": generated_expense_amount,
        "budget_import_detail_bucket_total_amount": (
            generated_labor_amount
            + generated_material_amount
            + generated_expense_amount
        ),
        "budget_import_generated_labor_amount": generated_labor_amount,
        "budget_import_generated_material_amount": generated_material_amount,
        "budget_import_generated_subcontract_amount": generated_subcontract_amount,
        "budget_import_generated_expense_amount": generated_expense_amount,
        "budget_import_generated_contract_amount": (
            generated_labor_amount
            + generated_material_amount
            + generated_subcontract_amount
            + generated_expense_amount
        ),
        "budget_import_manual_required_rows": manual_required_row_count,
        "budget_import_manual_required_labor_amount": manual_required_labor_amount,
        "budget_import_manual_required_material_amount": manual_required_material_amount,
        "budget_import_manual_required_expense_amount": manual_required_expense_amount,
        "budget_import_unmapped_labor_amount": unmapped_labor_amount,
        "budget_import_unmapped_material_amount": unmapped_material_amount,
        "budget_import_unmapped_expense_amount": unmapped_expense_amount,
        "budget_import_manual_required_total_amount": (
            manual_required_labor_amount
            + manual_required_material_amount
            + manual_required_expense_amount
        ),
        "budget_import_unmapped_total_amount": (
            unmapped_labor_amount
            + unmapped_material_amount
            + unmapped_expense_amount
        ),
        "budget_import_excluded_amount": excluded_amount,
        "budget_import_owner_supplied_amount": owner_supplied_amount,
        "budget_import_owner_supplied_rows": owner_supplied_row_count,
        "budget_import_total_construction_amount": total_construction_amount,
        "budget_import_matched_amount": matched_total_amount,
        "budget_import_unmatched_amount": imported_total_amount - matched_total_amount,
        "budget_import_match_rate": (
            ((matched_total_amount / imported_total_amount) * Decimal("100"))
            if imported_total_amount > 0
            else Decimal("0")
        ),
        "budget_review_rows": review_rows,
        "budget_review_errors": review_errors,
        "budget_reconciliation_candidates": bucket_reconciliation_candidates[:20],
    }
    if not initial and rows and unmatched_row_count > 0:
        warnings.append(
            "CBS 매칭된 예산 라인이 없습니다. CBS를 수동 선택하거나 CBS alias를 등록해 주세요."
        )
    return initial, warnings, stats

def resolve_wbs_baseline_dates(row, project):
    """Resolve imported WBS dates without allowing an undated baseline."""
    start_date = row.get("plan_start_date")
    end_date = row.get("plan_end_date")
    used_project_fallback = not (start_date and end_date)

    if start_date is None:
        start_date = getattr(project, "start_date", None)
    if end_date is None:
        end_date = getattr(project, "end_date", None)
    if start_date is None or end_date is None:
        raise ValidationError(
            "WBS 기준선 기간을 설정할 수 없습니다. 프로젝트 착공일과 준공예정일을 먼저 입력해 주세요."
        )
    if start_date > end_date:
        raise ValidationError("WBS 기준선 시작일은 종료일보다 늦을 수 없습니다.")

    project_start_date = getattr(project, "start_date", None)
    project_end_date = getattr(project, "end_date", None)
    if project_start_date and project_end_date and (
        start_date < project_start_date or end_date > project_end_date
    ):
        raise ValidationError("WBS 기준선 기간은 프로젝트 기간을 벗어날 수 없습니다.")

    return start_date, end_date, (
        "PROJECT_FALLBACK" if used_project_fallback else "EXCEL"
    )


def _resolve_wbs_baseline_dates(wbs_items, project):
    defaulted_count = 0
    for item in wbs_items:
        start_date, end_date, date_source = resolve_wbs_baseline_dates(item, project)
        item["plan_start_date"] = start_date
        item["plan_end_date"] = end_date
        item["wbs_date_source"] = date_source
        if date_source == "PROJECT_FALLBACK":
            defaulted_count += 1
    return defaulted_count


def _build_wbs_initial_from_import_rows(rows, project=None):
    original_weights = [Decimal(row.get("weight") or 0) for row in rows]
    original_sum = sum(original_weights, Decimal("0"))
    initial = []
    warnings = []
    for idx, row in enumerate(rows, start=1):
        if row.get("warnings"):
            warnings.extend(
                [
                    f"{row.get('name') or row.get('code') or 'WBS 행'}: {warning}"
                    for warning in row["warnings"]
                ]
            )
        quantized_weight = _quantize_wbs_weight(row.get("weight"))
        initial_row = {
            "name": row.get("name") or row.get("code") or "",
            "weight": quantized_weight,
            "sort_order": resolve_wbs_sort_order(
                row.get("code") or row.get("name"),
                idx,
                row.get("sort_order"),
            ),
            "plan_start_date": row.get("plan_start_date"),
            "plan_end_date": row.get("plan_end_date"),
        }
        if project is not None:
            try:
                start_date, end_date, date_source = resolve_wbs_baseline_dates(
                    initial_row, project
                )
            except ValidationError as exc:
                warnings.append(str(exc))
                row["wbs_date_source"] = "UNSET"
                row["wbs_date_source_label"] = "미설정"
            else:
                initial_row["plan_start_date"] = start_date
                initial_row["plan_end_date"] = end_date
                initial_row["wbs_date_source"] = date_source
                row["resolved_plan_start_date"] = start_date
                row["resolved_plan_end_date"] = end_date
                row["wbs_date_source"] = date_source
                row["wbs_date_source_label"] = (
                    "프로젝트 기간 기본값"
                    if date_source == "PROJECT_FALLBACK"
                    else "Excel"
                )
        initial.append(initial_row)
    rounded_sum = sum((Decimal(item["weight"] or 0) for item in initial), Decimal("0"))
    if initial and abs(original_sum - Decimal("100")) <= Decimal("0.1"):
        adjustment = _quantize_wbs_weight(Decimal("100") - rounded_sum)
        if adjustment:
            initial[-1]["weight"] = _quantize_wbs_weight(
                Decimal(initial[-1]["weight"] or 0) + adjustment
            )
    return initial, warnings


def _project_for_wbs_date_preview(post_data):
    if not post_data:
        return None
    start_value = post_data.get("start_date") or ""
    end_value = post_data.get("end_date") or ""
    return Project(
        start_date=parse_date(str(start_value)) if start_value else None,
        end_date=parse_date(str(end_value)) if end_value else None,
    )


def _quantize_wbs_weight(value):
    decimal_places = 2
    try:
        decimal_places = WBSItem._meta.get_field("weight").decimal_places or 2
    except Exception:
        decimal_places = 2
    quant = Decimal("1").scaleb(-decimal_places)
    decimal_value = Decimal(value or 0)
    return decimal_value.quantize(quant, rounding=ROUND_HALF_UP)


def _build_project_import_context(
    upload_refs,
    *,
    actor,
    request,
    log_parse=False,
    post_data=None,
    action="",
):
    selectable_cost_items = list(CostItem.objects.prefetch_related("aliases").all().order_by("sort_order", "name"))
    manual_mapping, alias_save_keys = _extract_budget_manual_mapping(post_data)
    context = {
        "upload_tokens": {
            f"{field_name}_token": (upload_refs[field_name] or {}).get("token", "")
            for field_name in PROJECT_NEW_UPLOAD_FIELDS
        },
        "stored_upload_names": {
            field_name: (upload_refs[field_name] or {}).get("original_name", "")
            for field_name in PROJECT_NEW_UPLOAD_FIELDS
        },
        "budget_preview_rows": [],
        "budget_import_notice": "",
        "budget_import_warnings": [],
        "budget_form_initial": [],
        "budget_review_rows": [],
        "budget_review_errors": [],
        "budget_match_options": _build_budget_match_options(selectable_cost_items),
        "budget_import_total_rows": 0,
        "budget_import_source_upload_target_rows": 0,
        "budget_import_matched_rows": 0,
        "budget_import_auto_matched_rows": 0,
        "budget_import_manual_matched_rows": 0,
        "budget_import_unmatched_rows": 0,
        "budget_import_unmatched_details": [],
        "budget_import_skipped_rows": 0,
        "budget_import_skipped_section_rows": 0,
        "budget_form_initial_count": 0,
        "budget_import_total_amount": Decimal("0"),
        "budget_import_contract_scope_amount": Decimal("0"),
        "budget_import_detail_labor_amount": Decimal("0"),
        "budget_import_detail_material_amount": Decimal("0"),
        "budget_import_detail_expense_amount": Decimal("0"),
        "budget_import_detail_bucket_total_amount": Decimal("0"),
        "budget_import_generated_labor_amount": Decimal("0"),
        "budget_import_generated_material_amount": Decimal("0"),
        "budget_import_generated_subcontract_amount": Decimal("0"),
        "budget_import_generated_expense_amount": Decimal("0"),
        "budget_import_generated_contract_amount": Decimal("0"),
        "budget_import_manual_required_rows": 0,
        "budget_import_manual_required_labor_amount": Decimal("0"),
        "budget_import_manual_required_material_amount": Decimal("0"),
        "budget_import_manual_required_expense_amount": Decimal("0"),
        "budget_import_unmapped_labor_amount": Decimal("0"),
        "budget_import_unmapped_material_amount": Decimal("0"),
        "budget_import_unmapped_expense_amount": Decimal("0"),
        "budget_import_manual_required_total_amount": Decimal("0"),
        "budget_import_unmapped_total_amount": Decimal("0"),
        "budget_reconciliation_candidates": [],
        "budget_import_owner_supplied_amount": Decimal("0"),
        "budget_import_owner_supplied_rows": 0,
        "budget_import_total_construction_amount": Decimal("0"),
        "budget_import_matched_amount": Decimal("0"),
        "budget_import_unmatched_amount": Decimal("0"),
        "budget_import_match_rate": Decimal("0"),
        "budget_summary_sheet_name": "",
        "budget_summary_contract_amount": None,
        "budget_summary_labor_amount": None,
        "budget_summary_material_amount": None,
        "budget_summary_expense_amount": None,
        "budget_summary_warnings": [],
        "budget_summary_contract_label": "",
        "budget_contract_amount_difference": None,
        "budget_summary_labor_difference": None,
        "budget_summary_material_difference": None,
        "budget_summary_expense_difference": None,
        "budget_summary_total_difference": None,
        "budget_import_coverage_warning": "",
        "budget_alias_created_count": 0,
        "budget_alias_existing_count": 0,
        "budget_alias_skipped_count": 0,
        "budget_alias_saved_labels": [],
        "budget_alias_skipped_reasons": [],
        "wbs_preview_rows": [],
        "wbs_import_notice": "",
        "wbs_import_warnings": [],
        "wbs_form_initial": [],
        "wbs_date_defaulted_count": 0,
        "import_warning_count": 0,
    }
    parsed_any = False
    if upload_refs.get("budget_excel"):
        try:
            result = parse_budget_workbook(upload_refs["budget_excel"]["path"])
            parsed_any = True
            for index, row in enumerate(result["rows"]):
                row["import_key"] = row.get("import_key") or _make_budget_import_key(row, index)
            context["budget_preview_rows"] = result["rows"]
            context["budget_import_notice"] = (
                f"{result['sheet_name']} 시트에서 예산 행을 불러왔습니다."
            )
            summary_info = result.get("summary_sheet") or {}
            context["budget_summary_sheet_name"] = summary_info.get("summary_sheet_name") or ""
            context["budget_summary_contract_amount"] = summary_info.get("contract_expected_amount")
            context["budget_summary_labor_amount"] = summary_info.get("contract_labor_amount")
            context["budget_summary_material_amount"] = summary_info.get("contract_material_amount")
            context["budget_summary_expense_amount"] = summary_info.get("contract_expense_amount")
            context["budget_summary_warnings"] = list(summary_info.get("warnings") or [])
            context["budget_summary_contract_label"] = summary_info.get("contract_amount_label") or ""
            (
                context["budget_form_initial"],
                context["budget_import_warnings"],
                budget_stats,
            ) = _build_budget_initial_from_import_rows(
                result["rows"],
                manual_mapping=manual_mapping,
                manual_adjustments=_extract_budget_review_adjustments(post_data),
            )
            context.update(budget_stats)
            context["budget_review_rows"] = budget_stats.get("budget_review_rows", [])
            context["budget_review_errors"] = budget_stats.get("budget_review_errors", [])
            if action in {"apply_budget_cbs_mapping", "apply_budget_review_adjustments", "save_project"}:
                alias_result = _persist_budget_manual_aliases(
                    result["rows"],
                    manual_mapping,
                    alias_save_keys,
                    selectable_cost_items,
                )
                review_alias_result = _persist_budget_review_aliases(
                    context["budget_review_rows"],
                    selectable_cost_items,
                )
                alias_result = _merge_alias_diagnostics(alias_result, review_alias_result)
                context["budget_alias_created_count"] = alias_result["alias_created_count"]
                context["budget_alias_existing_count"] = alias_result["alias_existing_count"]
                context["budget_alias_skipped_count"] = alias_result["alias_skipped_count"]
                context["budget_alias_saved_labels"] = alias_result["alias_saved_labels"]
                context["budget_alias_skipped_reasons"] = alias_result["alias_skipped_reasons"]
                if action in {"apply_budget_cbs_mapping", "apply_budget_review_adjustments"}:
                    if alias_result["alias_created_count"] > 0:
                        messages.success(
                            request,
                            f"CBS alias {alias_result['alias_created_count']}건을 저장했습니다.",
                        )
                    if alias_result["alias_existing_count"] > 0:
                        messages.info(
                            request,
                            f"이미 등록된 alias {alias_result['alias_existing_count']}건을 확인했습니다.",
                        )
                    if alias_result["alias_skipped_count"] > 0:
                        messages.warning(
                            request,
                            f"CBS alias {alias_result['alias_skipped_count']}건은 저장되지 않았습니다. CBS 선택과 품명을 확인해 주세요.",
                        )
            if summary_info.get("owner_supplied_amount") is not None:
                context["budget_import_owner_supplied_amount"] = summary_info.get("owner_supplied_amount")
            if summary_info.get("total_construction_amount") is not None:
                context["budget_import_total_construction_amount"] = summary_info.get("total_construction_amount")
            entered_contract_amount = None
            if post_data is not None:
                entered_contract_amount = _coerce_optional_decimal(post_data.get("contract_amount"))
            summary_contract_amount = context.get("budget_summary_contract_amount")
            summary_labor_amount = context.get("budget_summary_labor_amount")
            summary_material_amount = context.get("budget_summary_material_amount")
            summary_expense_amount = context.get("budget_summary_expense_amount")
            if entered_contract_amount is not None and summary_contract_amount is not None:
                context["budget_contract_amount_difference"] = entered_contract_amount - summary_contract_amount
            if summary_labor_amount is not None:
                context["budget_summary_labor_difference"] = (
                    summary_labor_amount
                    - context["budget_import_generated_labor_amount"]
                    - context["budget_import_manual_required_labor_amount"]
                    - context["budget_import_unmapped_labor_amount"]
                )
            if summary_material_amount is not None:
                context["budget_summary_material_difference"] = (
                    summary_material_amount
                    - context["budget_import_generated_material_amount"]
                    - context["budget_import_manual_required_material_amount"]
                    - context["budget_import_unmapped_material_amount"]
                )
            if summary_expense_amount is not None:
                context["budget_summary_expense_difference"] = (
                    summary_expense_amount
                    - context["budget_import_generated_expense_amount"]
                    - context["budget_import_manual_required_expense_amount"]
                    - context["budget_import_unmapped_expense_amount"]
                )
            if summary_contract_amount is not None:
                context["budget_summary_total_difference"] = (
                    summary_contract_amount
                    - context["budget_import_generated_contract_amount"]
                    - context["budget_import_manual_required_total_amount"]
                    - context["budget_import_unmapped_total_amount"]
                )
            if (
                summary_contract_amount is not None
                and context["budget_summary_total_difference"] != 0
            ):
                context["budget_import_coverage_warning"] = (
                    "상세 내역 합계와 총괄표 도급예정액이 다릅니다. 이윤 또는 단수조정 항목을 수동 조정해 주세요."
                )
            if (
                not context["budget_import_coverage_warning"]
                and context["budget_import_total_amount"] > 0
                and context["budget_import_match_rate"] < Decimal("95")
            ):
                context["budget_import_coverage_warning"] = (
                    "예산 매칭률이 낮습니다. 등록 전 CBS 매핑을 확인해 주세요."
                )
            if (
                context["budget_import_total_amount"] > 0
                and summary_contract_amount is not None
                and context["budget_contract_amount_difference"] is None
            ):
                context["budget_contract_amount_difference"] = Decimal("0")
        except Exception as exc:
            messages.error(request, f"계약 예산 파일을 읽지 못했습니다. {exc}")
    if upload_refs.get("commencement_excel"):
        try:
            result = parse_wbs_workbook(upload_refs["commencement_excel"]["path"])
            parsed_any = True
            context["wbs_preview_rows"] = result["rows"]
            context["wbs_import_notice"] = (
                f"{result['sheet_name']} 시트에서 예정공정표를 불러왔습니다."
            )
            (
                context["wbs_form_initial"],
                context["wbs_import_warnings"],
            ) = _build_wbs_initial_from_import_rows(
                result["rows"],
                project=_project_for_wbs_date_preview(post_data),
            )
            context["wbs_date_defaulted_count"] = sum(
                1
                for row in context["wbs_form_initial"]
                if row.get("wbs_date_source") == "PROJECT_FALLBACK"
            )
        except Exception as exc:
            messages.error(request, f"착공계 파일을 읽지 못했습니다. {exc}")
    context["import_warning_count"] = (
        len(context["budget_import_warnings"])
        + len(context["wbs_import_warnings"])
        + sum(len(row.get("warnings") or []) for row in context["budget_preview_rows"])
        + sum(len(row.get("warnings") or []) for row in context["wbs_preview_rows"])
    )
    if log_parse and parsed_any:
        log_action(
            actor=actor,
            action="PROJECT_IMPORT_PARSE",
            object_type="PROJECT_IMPORT",
            object_id=0,
            request=request,
            meta={
                "budget_rows": len(context["budget_preview_rows"]),
                "wbs_rows": len(context["wbs_preview_rows"]),
                "source_upload_target_row_count": int(
                    context.get("budget_import_source_upload_target_rows") or 0
                ),
                "matched_row_count": int(context.get("budget_import_matched_rows") or 0),
                "unmatched_cbs_row_count": int(
                    context.get("budget_import_unmatched_rows") or 0
                ),
                "unmatched_amount": str(context.get("budget_import_unmatched_amount") or 0),
                "unmatched_source_rows": [
                    item.get("source_row_no")
                    for item in context.get("budget_import_unmatched_details") or []
                ],
                "warning_count": context["import_warning_count"],
            },
        )
    return context



def _attach_project_import_file(project, ref, *, title, description, actor):
    if not ref:
        return None
    evidence = Evidence.objects.create(
        title=title,
        description=description,
        object_type="PROJECT",
        object_id=project.id,
        created_by=actor,
    )
    with Path(ref["path"]).open("rb") as handle:
        EvidenceFile.objects.create(
            evidence=evidence,
            file=File(handle, name=ref["original_name"]),
            original_name=ref["original_name"],
            content_type=ref.get("content_type") or "application/octet-stream",
            created_by=actor,
        )
    return evidence


def _log_project_import_commit_actions(
    *,
    project,
    request,
    import_context,
    upload_refs,
    budget_items,
    wbs_items,
):
    budget_ref = upload_refs.get("budget_excel")
    if budget_ref and import_context.get("budget_preview_rows"):
        log_action(
            actor=request.user,
            action="PROJECT_BUDGET_IMPORT_COMMIT",
            object_type="PROJECT_IMPORT",
            object_id=project.id,
            project=project,
            request=request,
            meta={
                "committed_row_count": len(budget_items),
                "preview_row_count": len(import_context["budget_preview_rows"]),
                "source_upload_target_row_count": int(
                    import_context.get("budget_import_source_upload_target_rows") or 0
                ),
                "matched_row_count": int(import_context.get("budget_import_matched_rows") or 0),
                "unmatched_row_count": int(import_context.get("budget_import_unmatched_rows") or 0),
                "unmatched_amount": str(
                    import_context.get("budget_import_unmatched_amount") or 0
                ),
                "unmatched_source_rows": [
                    item.get("source_row_no")
                    for item in import_context.get("budget_import_unmatched_details") or []
                ],
                "partial_budget_import": False,
                "warning_count": (
                    len(import_context.get("budget_import_warnings") or [])
                    + sum(
                        len(row.get("warnings") or [])
                        for row in import_context.get("budget_preview_rows") or []
                    )
                ),
                "filename": budget_ref.get("original_name", ""),
            },
        )
    wbs_ref = upload_refs.get("commencement_excel")
    if wbs_ref and import_context.get("wbs_preview_rows"):
        log_action(
            actor=request.user,
            action="PROJECT_WBS_IMPORT_COMMIT",
            object_type="PROJECT_IMPORT",
            object_id=project.id,
            project=project,
            request=request,
            meta={
                "committed_row_count": len(wbs_items),
                "preview_row_count": len(import_context["wbs_preview_rows"]),
                "wbs_date_defaulted_count": sum(
                    1
                    for item in wbs_items
                    if item.get("wbs_date_source") == "PROJECT_FALLBACK"
                ),
                "wbs_date_sources": sorted(
                    {item.get("wbs_date_source") for item in wbs_items if item.get("wbs_date_source")}
                ),
                "project_start_date": str(project.start_date or ""),
                "project_end_date": str(project.end_date or ""),
                "warning_count": (
                    len(import_context.get("wbs_import_warnings") or [])
                    + sum(
                        len(row.get("warnings") or [])
                        for row in import_context.get("wbs_preview_rows") or []
                    )
                ),
                "filename": wbs_ref.get("original_name", ""),
            },
        )


def _cleanup_project_new_uploads(request, upload_refs):
    session_map = request.session.get(PROJECT_NEW_UPLOAD_SESSION_KEY, {})
    for ref in upload_refs.values():
        if not ref:
            continue
        token = ref.get("token")
        path = ref.get("path")
        if path:
            try:
                Path(path).unlink(missing_ok=True)
            except Exception:
                logger.warning("Failed to delete temp upload %s", path, exc_info=True)
        if token and token in session_map:
            session_map.pop(token, None)
    request.session[PROJECT_NEW_UPLOAD_SESSION_KEY] = session_map
    request.session.modified = True


def _default_wbs_rows(project_type):
    template = [
        ("착공 준비", Decimal("5")),
        ("현장 정리 및 가설", Decimal("5")),
        ("기초 및 토공", Decimal("12")),
        ("배수 및 기반 정비", Decimal("10")),
        ("경계 및 포장 보수", Decimal("10")),
        ("환경 및 경사면 정리", Decimal("8")),
        ("식재 기반 및 토양개량", Decimal("8")),
        ("교목 식재", Decimal("12")),
        ("관목 및 초화 식재", Decimal("10")),
        ("잔디 및 지피 식재", Decimal("8")),
        ("시설물 설치", Decimal("7")),
        ("마감 및 준공 서류", Decimal("5")),
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


def _primary_project_type(work_types):
    """Keep a deterministic legacy primary type for codes and older reports."""
    for project_type in (ProjectType.CIVIL, ProjectType.LANDSCAPE, ProjectType.ARCH):
        if project_type in work_types:
            return project_type
    return ProjectType.LANDSCAPE


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
                "현재 선택한 공종의 템플릿이 없어 조경 기본 템플릿이 적용되었습니다. 필요한 경우 수정해 주세요.",
            )
    return [], "선택 가능한 템플릿이 없어 기본 입력 행으로 표시합니다."


def _get_templates_for_work_types(work_types, category):
    domains = [_project_domain(project_type) for project_type in work_types]
    templates = list(
        MasterTemplate.objects.filter(domain__in=domains, category=category, is_active=True)
        .order_by("domain", "-version", "id")
    )
    if templates:
        return templates, "선택한 계약 공종의 템플릿만 표시합니다. 복합 공종은 여러 템플릿을 함께 선택할 수 있습니다."
    return [], "선택한 공종에 사용할 수 있는 템플릿이 없어 기본 입력 행으로 표시합니다."


def _resolve_template_from_post(template_id, templates):
    if not template_id:
        return None
    for template in templates:
        if str(template.id) == str(template_id):
            return template
    return None


def _resolve_templates_from_post(template_ids, templates):
    requested_ids = {str(template_id) for template_id in template_ids if template_id}
    return [template for template in templates if str(template.id) in requested_ids]


def _build_wbs_initial_from_template(template, project_type):
    if not template:
        return _default_wbs_rows(project_type), ""
    items = list(template.wbs_items.all().order_by("order", "id"))
    if not items:
        return (
            _default_wbs_rows(project_type),
            "선택한 WBS 템플릿에 항목이 없어 기본 WBS 행을 적용했습니다.",
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


def _build_wbs_initial_from_templates(templates, project_type):
    if not templates:
        return _default_wbs_rows(project_type), ""
    rows = []
    warnings = []
    for template in templates:
        template_rows, warning = _build_wbs_initial_from_template(template, project_type)
        rows.extend(template_rows)
        if warning:
            warnings.append(warning)
    total_weight = sum((Decimal(str(row.get("weight") or 0)) for row in rows), Decimal("0"))
    if total_weight > 0:
        normalized_total = Decimal("0")
        for index, row in enumerate(rows):
            if index == len(rows) - 1:
                row["weight"] = Decimal("100") - normalized_total
            else:
                row["weight"] = (Decimal(str(row.get("weight") or 0)) * Decimal("100") / total_weight).quantize(Decimal("0.01"))
                normalized_total += row["weight"]
            row["sort_order"] = index + 1
    return rows, " ".join(warnings)


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


def _build_budget_initial_from_templates(templates):
    if not templates:
        return _default_landscape_budget_rows()
    rows = []
    warnings = []
    for template in templates:
        template_rows, template_warnings = _build_budget_initial_from_template(template)
        rows.extend(template_rows)
        warnings.extend(template_warnings)
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
        category_value = form.cleaned_data.get("category")
        amount_value = int(planned_amount)
        name_value = form.cleaned_data.get("name") or cost_item.name
        note_value = form.cleaned_data.get("note") or ""
        key = (cost_item.id, category_value, name_value)
        owner_supplied_markers = ("관급", "관급자재", "아스콘(관급)")
        if any(marker in note_value for marker in owner_supplied_markers):
            continue
        if key not in items_by_cost_item:
            items_by_cost_item[key] = {
                "cost_item": cost_item,
                "category": category_value,
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
        ("착공/가설/안전시설", ["가설", "안전", "정리"]),
        ("현장정리/폐기물처리", ["현장정리", "폐기물", "반출"]),
        ("토공(정지/절토/성토)", ["토공", "정지", "절토", "성토"]),
        ("배수/관수 기반", ["배수", "관수", "배관", "맨홀"]),
        ("경계석/블록/포장", ["경계석", "보도블록", "포장"]),
        ("경사면/석축/계단", ["석축", "계단", "경사면"]),
        ("토양개량/식재기반", ["토양개량", "식재기반", "상토"]),
        ("교목(수목)", ["교목", "수목", "수목식재"]),
        ("관목", ["관목", "관목식재"]),
        ("초화류/지피", ["초화", "지피", "초화류"]),
        ("잔디", ["잔디", "잔디식재"]),
        ("비료/멀칭/지주보호", ["비료", "멀칭", "지주", "보호"]),
        ("시설물 설치/도장/데크", ["설치", "도장", "데크", "시설물"]),
        ("조명/전기", ["조명", "전기", "분전"]),
        ("인건비/현장관리 작업", ["인건비", "노무", "작업", "현장관리"]),
        ("준공정리/서류", ["준공", "정리", "서류"]),
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
    for row_index, form in enumerate(formset, start=1):
        if not form.cleaned_data:
            continue
        if form.cleaned_data.get("DELETE"):
            continue
        name = (form.cleaned_data.get("name") or "").strip()
        if not name:
            continue
        weight = form.cleaned_data.get("weight") or Decimal("0")
        weight_sum += Decimal(weight)
        provided_sort_order = form.cleaned_data.get("sort_order")
        if provided_sort_order in (None, "") and form.instance.pk:
            provided_sort_order = form.instance.sort_order
        items.append(
            {
                "name": name,
                "weight": weight,
                "sort_order": resolve_wbs_sort_order(
                    name,
                    row_index,
                    provided_sort_order,
                ),
                "plan_start_date": form.cleaned_data.get("plan_start_date"),
                "plan_end_date": form.cleaned_data.get("plan_end_date"),
            }
        )
    return items, weight_sum


def _is_weight_sum_valid(total):
    return abs(Decimal("100") - Decimal(total)) <= Decimal("0.1")


def _get_project_budget_totals(project):
    all_budget_qs = BudgetItem.objects.filter(project=project)
    budget_qs = all_budget_qs.exclude(category=BudgetCategory.LABOR)
    labor_qs = all_budget_qs.filter(category=BudgetCategory.LABOR).exclude(
        cost_item__code="CIVIL-PROFIT"
    )
    material_qs = all_budget_qs.filter(category=BudgetCategory.MATERIAL)
    subcontract_qs = all_budget_qs.filter(category=BudgetCategory.SUBCON)
    expense_qs = all_budget_qs.exclude(
        category__in=[
            BudgetCategory.MATERIAL,
            BudgetCategory.SUBCON,
            BudgetCategory.LABOR,
        ]
    )

    budget_total_amount = (
        budget_qs.aggregate(total=Sum("planned_amount")).get("total") or Decimal("0")
    )
    labor_budget_total_amount = (
        labor_qs.aggregate(total=Sum("planned_amount")).get("total") or Decimal("0")
    )
    budget_grand_total_amount = budget_total_amount + labor_budget_total_amount
    material_budget_total_amount = (
        material_qs.aggregate(total=Sum("planned_amount")).get("total") or Decimal("0")
    )
    subcontract_budget_total_amount = (
        subcontract_qs.aggregate(total=Sum("planned_amount")).get("total")
        or Decimal("0")
    )
    expense_budget_total_amount = (
        expense_qs.aggregate(total=Sum("planned_amount")).get("total") or Decimal("0")
    )
    contract = ProjectContract.objects.filter(project=project).first()
    contract_budget_difference = None
    if contract and contract.contract_amount is not None:
        contract_budget_difference = (
            contract.contract_amount - budget_grand_total_amount
        )
    budget_category_breakdown = {
        "expense": expense_budget_total_amount,
        "material": material_budget_total_amount,
        "subcon": subcontract_budget_total_amount,
        "labor": labor_budget_total_amount,
    }
    return {
        "budget_qs": budget_qs,
        "labor_qs": labor_qs,
        "budget_total_amount": budget_total_amount,
        "labor_budget_total_amount": labor_budget_total_amount,
        "material_budget_total_amount": material_budget_total_amount,
        "subcontract_budget_total_amount": subcontract_budget_total_amount,
        "expense_budget_total_amount": expense_budget_total_amount,
        "budget_grand_total_amount": budget_grand_total_amount,
        "contract_budget_difference": contract_budget_difference,
        "budget_category_breakdown": budget_category_breakdown,
    }


def _collect_formset_errors(formset, label):
    errors = []
    for err in formset.non_form_errors():
        errors.append(f"{label}: {err}")
    for index, form in enumerate(formset.forms, start=1):
        for field_name, field_errors in form.errors.items():
            field_label = form.fields.get(field_name).label if field_name in form.fields else field_name
            if field_name == "__all__":
                field_label = "행 전체"
            elif not field_label:
                field_label = field_name
            for err in field_errors:
                errors.append(f"{label} {index}행 {field_label}: {err}")
    return errors


def _is_effectively_empty_budget_form(cleaned_data):
    if not cleaned_data:
        return True
    meaningful_fields = ("cost_item", "name", "planned_amount", "note")
    for field_name in meaningful_fields:
        value = cleaned_data.get(field_name)
        if value not in (None, "", 0, Decimal("0")):
            return False
    return not cleaned_data.get("id")


def hq_project_detail(request, project_id):
    require_role(request.user, [Role.HQ, Role.CEO])
    project = get_object_or_404(Project, id=project_id)
    require_project_access(request.user, project.id)
    if project.legal_entity_id != getattr(get_current_legal_entity(request), "id", None):
        raise PermissionDenied("선택한 운영 법인의 프로젝트만 조회할 수 있습니다.")
    baseline_workflow = get_project_baseline_workflow(project)
    contract = ProjectContract.objects.filter(project=project).first()
    role = get_user_role(request.user)
    _normalize_project_budget_categories(project)

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
    totals = _get_project_budget_totals(project)
    budget_qs = totals["budget_qs"]
    labor_qs = totals["labor_qs"]
    budget_total_amount = totals["budget_total_amount"]
    labor_budget_total_amount = totals["labor_budget_total_amount"]
    material_budget_total_amount = totals["material_budget_total_amount"]
    subcontract_budget_total_amount = totals["subcontract_budget_total_amount"]
    expense_budget_total_amount = totals["expense_budget_total_amount"]
    budget_grand_total_amount = totals["budget_grand_total_amount"]
    contract_budget_difference = totals["contract_budget_difference"]
    budget_category_breakdown = totals["budget_category_breakdown"]
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
    budget_form_errors = []
    labor_form_errors = []

    if request.method == "POST":
        action = request.POST.get("action")
        if action == "update_billing_approval_policy":
            if role != Role.HQ:
                messages.error(request, "HQ만 기성 보고서 결재 정책을 변경할 수 있습니다.")
                return redirect(f"/app/hq/projects/{project.id}/")
            before = project.requires_ceo_billing_approval
            project.requires_ceo_billing_approval = request.POST.get("requires_ceo_billing_approval") == "on"
            project.save(update_fields=["requires_ceo_billing_approval", "updated_at"])
            log_action(actor=request.user, action="PROJECT_BILLING_APPROVAL_POLICY_UPDATED", object_type="PROJECT", object_id=project.id, project=project, request=request, before={"requires_ceo_billing_approval": before}, after={"requires_ceo_billing_approval": project.requires_ceo_billing_approval})
            messages.success(request, "기성 보고서 CEO 결재 정책을 저장했습니다.")
            return redirect(f"/app/hq/projects/{project.id}/")
        if action == "submit_baseline":
            if role != Role.HQ:
                messages.error(request, "HQ만 프로젝트 기준선을 제출할 수 있습니다.")
                return redirect(f"/app/hq/projects/{project.id}/")
            if (
                project.status != ProjectStatus.DRAFT
                and not baseline_workflow.can_hq_resubmit
            ):
                messages.error(request, "제출은 임시저장 상태의 프로젝트에서만 가능합니다.")
                return redirect(f"/app/hq/projects/{project.id}/")
            latest_approval = (
                ApprovalRequest.objects.filter(
                    object_type="PROJECT_BASELINE",
                    object_id=project.id,
                )
                .order_by("-updated_at", "-id")
                .first()
            )
            is_resubmit = bool(
                baseline_workflow.can_hq_resubmit
                and latest_approval
                and latest_approval.status == ApprovalStatus.REJECTED
            )
            if contract is None or not contract.contract_file:
                messages.error(request, "계약 파일을 먼저 등록해 주세요.")
                return redirect(f"/app/hq/projects/{project.id}/")
            if contract.contract_amount is None or contract.contract_amount <= 0:
                messages.error(request, "계약 금액은 0보다 커야 합니다.")
                return redirect(f"/app/hq/projects/{project.id}/")
            if project.start_date and project.end_date and project.start_date > project.end_date:
                messages.error(request, "공사 시작일은 종료일보다 늦을 수 없습니다.")
                return redirect(f"/app/hq/projects/{project.id}/")
            if not WBSItem.objects.filter(project=project).exists():
                messages.warning(request, "WBS가 없습니다. 제출은 가능하지만 일정을 먼저 확인해 주세요.")
            if not BudgetItem.objects.filter(project=project).exists():
                messages.warning(request, "예산 라인이 없습니다. 제출은 가능하지만 내용을 먼저 확인해 주세요.")
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
                action="BASELINE_RESUBMIT" if is_resubmit else BASELINE_SUBMIT,
                object_type="PROJECT",
                object_id=project.id,
                project=project,
                request=request,
                before={"status": ProjectStatus.DRAFT},
                after={"status": project.status},
                meta={
                    "is_resubmit": is_resubmit,
                    "previous_approval_id": latest_approval.id if latest_approval else None,
                    "previous_approval_status": (
                        latest_approval.status if latest_approval else ""
                    ),
                },
            )
            messages.success(
                request,
                "기준선 재제출이 완료되었습니다." if is_resubmit else "기준선 제출이 완료되었습니다.",
            )
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
            messages.success(request, "기준선 승인이 완료되었습니다.")
            return redirect(f"/app/hq/projects/{project.id}/")
        if action == "reject_baseline":
            if role != Role.CEO:
                messages.error(request, "CEO만 반려할 수 있습니다.")
                return redirect(f"/app/hq/projects/{project.id}/")
            if project.status != ProjectStatus.SUBMITTED:
                messages.error(request, "제출된 프로젝트만 반려할 수 있습니다.")
                return redirect(f"/app/hq/projects/{project.id}/")
            reject_reason = (request.POST.get("reject_reason") or "").strip()
            before_status = project.status
            project.status = ProjectStatus.DRAFT
            project.save(update_fields=["status", "updated_at"])
            approval_defaults = {
                "status": ApprovalStatus.REJECTED,
            }
            approval_fields = {field.name for field in ApprovalRequest._meta.fields}
            if "reject_reason" in approval_fields:
                approval_defaults["reject_reason"] = reject_reason
            ApprovalRequest.objects.update_or_create(
                object_type="PROJECT_BASELINE",
                object_id=project.id,
                defaults=approval_defaults,
            )
            log_action(
                actor=request.user,
                action=BASELINE_REJECT,
                object_type="PROJECT",
                object_id=project.id,
                project=project,
                request=request,
                before={"status": before_status},
                after={"status": project.status},
                meta={"reason": reject_reason},
            )
            messages.success(request, "프로젝트 기준선이 반려되어 수정 가능한 상태로 돌아갔습니다.")
            return redirect(f"/app/hq/projects/{project.id}/")
        if action == "add_assignment":
            if wbs_locked:
                messages.error(request, "프로젝트가 잠겨 있어 배정을 수정할 수 없습니다.")
                return redirect(f"/app/hq/projects/{project.id}/")
            assignment_form = ProjectAssignmentForm(request.POST)
            if assignment_form.is_valid():
                user = assignment_form.cleaned_data["user"]
                is_active = assignment_form.cleaned_data["is_active"]
                assignment_type = assignment_form.cleaned_data["assignment_type"]
                employee = getattr(user, "office_employee_profile", None)
                if (
                    employee is not None
                    and employee.employment_legal_entity_id != project.legal_entity_id
                    and assignment_type != ProjectAssignment.AssignmentType.OPERATIONS_SUPPORT
                ):
                    assignment_form.add_error(
                        "assignment_type",
                        "타 법인 소속 본사 직원은 ‘운영지원’으로만 배정할 수 있습니다.",
                    )
                    messages.error(request, "타 법인 소속 본사 직원은 운영지원으로 배정해 주세요.")
                    return redirect(f"/app/hq/projects/{project.id}/")
                assignment, created = ProjectAssignment.objects.get_or_create(
                    project=project,
                    user=user,
                    defaults={"is_active": is_active, "assignment_type": assignment_type},
                )
                before = None
                audit_action = ASSIGNMENT_ADD
                if not created:
                    before = {
                        "is_active": assignment.is_active,
                        "assignment_type": assignment.assignment_type,
                    }
                    assignment.is_active = is_active
                    assignment.assignment_type = assignment_type
                    assignment.save(update_fields=["is_active", "assignment_type"])
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
                        "assignment_type": assignment.assignment_type,
                    },
                )
                messages.success(request, "프로젝트 배정을 저장했습니다.")
                return redirect(f"/app/hq/projects/{project.id}/")
            messages.error(request, "프로젝트 배정 입력값을 확인해 주세요.")
        elif action == "toggle_assignment":
            if wbs_locked:
                messages.error(request, "프로젝트가 잠겨 있어 배정을 수정할 수 없습니다.")
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
            messages.success(request, "프로젝트 배정 상태를 변경했습니다.")
            return redirect(f"/app/hq/projects/{project.id}/")
        elif action == "save_budget":
            if wbs_locked:
                messages.error(request, "프로젝트가 잠겨 있어 예산을 수정할 수 없습니다.")
                return redirect(f"/app/hq/projects/{project.id}/")
            budget_formset = BudgetFormSet(
                request.POST, queryset=budget_qs, prefix="budget"
            )
            labor_formset = LaborFormSet(
                request.POST, queryset=labor_qs, prefix="labor"
            )
            budget_valid = budget_formset.is_valid()
            labor_valid = labor_formset.is_valid()
            budget_form_errors = _collect_formset_errors(
                budget_formset, "일반 예산"
            )
            labor_form_errors = _collect_formset_errors(
                labor_formset, "노무 예산"
            )
            if budget_valid and labor_valid:
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
                    messages.error(request, "CBS 선택 정책으로 인해 저장할 수 없습니다.")
                    return render(
                        request,
                        "app/hq_project_detail.html",
                        {
                            "project": project,
                            "baseline_workflow": baseline_workflow,
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
                            "budget_total_amount": budget_total_amount,
                            "labor_budget_total_amount": labor_budget_total_amount,
                            "material_budget_total_amount": material_budget_total_amount,
                            "subcontract_budget_total_amount": subcontract_budget_total_amount,
                            "expense_budget_total_amount": expense_budget_total_amount,
                            "budget_grand_total_amount": budget_grand_total_amount,
                            "contract_budget_difference": contract_budget_difference,
                            "budget_category_breakdown": budget_category_breakdown,
                            "role": role,
                            "now": timezone.localdate(),
                        },
                    )
                with transaction.atomic():
                    for form in budget_formset:
                        if form.cleaned_data.get("DELETE"):
                            if form.instance.pk:
                                form.instance.delete()
                            continue
                        if _is_effectively_empty_budget_form(form.cleaned_data):
                            continue
                        item = form.save(commit=False)
                        item.project = project
                        item.category = _canonical_budget_category_for_cost_item(
                            item.cost_item,
                            current_category=item.category,
                        )
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
                        if _is_effectively_empty_budget_form(form.cleaned_data):
                            continue
                        item = form.save(commit=False)
                        item.project = project
                        item.category = _canonical_budget_category_for_cost_item(
                            item.cost_item,
                            current_category=BudgetCategory.LABOR,
                        )
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
                messages.success(request, "예산 기준선을 저장했습니다.")
                return redirect(f"/app/hq/projects/{project.id}/")
            messages.error(
                request,
                "예산 기준선 저장에 실패했습니다. 오류 항목을 확인해 주세요.",
            )
            logger.warning(
                "Budget save validation failed for project %s: budget=%s labor=%s",
                project.id,
                budget_form_errors,
                labor_form_errors,
            )
            wbs_formset = WBSFormSet(queryset=wbs_qs, prefix="wbs")
            for form in wbs_formset:
                form.fields["parent"].queryset = wbs_qs
            totals = _get_project_budget_totals(project)
            budget_total_amount = totals["budget_total_amount"]
            labor_budget_total_amount = totals["labor_budget_total_amount"]
            material_budget_total_amount = totals["material_budget_total_amount"]
            subcontract_budget_total_amount = totals["subcontract_budget_total_amount"]
            expense_budget_total_amount = totals["expense_budget_total_amount"]
            budget_grand_total_amount = totals["budget_grand_total_amount"]
            contract_budget_difference = totals["contract_budget_difference"]
            budget_category_breakdown = totals["budget_category_breakdown"]
        elif action == "save_wbs":
            if wbs_locked:
                messages.error(request, "제출 이후 WBS는 수정할 수 없습니다.")
                return redirect(f"/app/hq/projects/{project.id}/")
            wbs_formset = WBSFormSet(request.POST, queryset=wbs_qs, prefix="wbs")
            for form in wbs_formset:
                form.fields["parent"].queryset = wbs_qs
            if wbs_formset.is_valid():
                for row_index, form in enumerate(wbs_formset, start=1):
                    if form.cleaned_data.get("DELETE"):
                        if form.instance.pk:
                            form.instance.delete()
                        continue
                    item = form.save(commit=False)
                    item.project = project
                    provided_sort_order = form.cleaned_data.get("sort_order")
                    if provided_sort_order in (None, "") and form.instance.pk:
                        provided_sort_order = form.instance.sort_order
                    item.sort_order = resolve_wbs_sort_order(
                        item.name,
                        row_index,
                        provided_sort_order,
                    )
                    item.save()
                messages.success(request, "WBS 기준선을 저장했습니다.")
                return redirect(f"/app/hq/projects/{project.id}/")
            messages.error(request, "WBS 입력값을 확인해 주세요.")

    return render(
        request,
        "app/hq_project_detail.html",
        {
            "project": project,
        "baseline_workflow": baseline_workflow,
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
        "budget_total_amount": budget_total_amount,
        "labor_budget_total_amount": labor_budget_total_amount,
        "material_budget_total_amount": material_budget_total_amount,
        "subcontract_budget_total_amount": subcontract_budget_total_amount,
        "expense_budget_total_amount": expense_budget_total_amount,
        "budget_grand_total_amount": budget_grand_total_amount,
        "contract_budget_difference": contract_budget_difference,
        "budget_category_breakdown": budget_category_breakdown,
        "budget_form_errors": budget_form_errors,
        "labor_form_errors": labor_form_errors,
        "role": role,
        "now": timezone.localdate(),
    },
)


@login_required
def hq_wbs_change_new(request, project_id):
    require_role(request.user, [Role.HQ])
    project = get_object_or_404(Project, id=project_id)
    require_project_access(request.user, project.id)
    if project.legal_entity_id != getattr(get_current_legal_entity(request), "id", None):
        raise PermissionDenied("선택한 운영 법인의 WBS만 변경할 수 있습니다.")
    role = get_user_role(request.user)
    return render_wbs_change_form(
        request,
        project,
        role,
        template_name="app/common/wbs_change_form.html",
        back_url=f"/app/hq/projects/{project.id}/",
    )


@login_required
def hq_project_operational_test_date_window(request, project_id):
    require_role(request.user, [Role.HQ])
    project = get_object_or_404(Project, id=project_id)
    require_project_access(request.user, project.id)
    if project.legal_entity_id != getattr(get_current_legal_entity(request), "id", None):
        raise PermissionDenied("선택한 운영 법인의 프로젝트만 설정할 수 있습니다.")
    window = ProjectOperationalTestDateWindow.objects.filter(project=project).first()
    if request.method == "POST":
        try:
            start_date = parse_date(request.POST.get("start_date") or "")
            end_date = parse_date(request.POST.get("end_date") or "")
            expires_on = parse_date(request.POST.get("expires_on") or "")
            reason = (request.POST.get("reason") or "").strip()
            if not start_date or not end_date or not expires_on or not reason:
                raise ValidationError("허용 시작일·종료일·자동 해제일과 테스트 사유를 모두 입력해 주세요.")
            candidate = window or ProjectOperationalTestDateWindow(project=project, configured_by=request.user)
            candidate.start_date, candidate.end_date, candidate.expires_on = start_date, end_date, expires_on
            candidate.reason = reason
            candidate.is_enabled = request.POST.get("is_enabled") == "1"
            candidate.configured_by = request.user
            candidate.full_clean()
            candidate.save()
            log_action(actor=request.user, action="PROJECT_TEST_DATE_WINDOW_CONFIGURED", object_type="ProjectOperationalTestDateWindow", object_id=candidate.id, project=project, request=request, after={"is_enabled": candidate.is_enabled, "start_date": str(start_date), "end_date": str(end_date), "expires_on": str(expires_on), "reason": reason})
            messages.success(request, "프로젝트 운영 테스트 날짜 허용 기간을 저장했습니다.")
            return redirect(f"/app/hq/projects/{project.id}/operational-test-date-window/")
        except ValidationError as exc:
            messages.error(request, str(exc))
    return render(request, "app/hq/project_operational_test_date_window.html", {"project": project, "window": window, "today": timezone.localdate()})
