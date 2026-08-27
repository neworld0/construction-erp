import os
from datetime import date, datetime, time
from django.db import connections
from django.db.models import Q
from django.db.utils import OperationalError
from django.utils import timezone

from django.conf import settings
from django.contrib import messages
from django.contrib.auth import authenticate, login, logout
from django.core.exceptions import PermissionDenied
from django.db import transaction
from django.http import FileResponse, Http404, JsonResponse
from django.shortcuts import get_object_or_404, redirect, render
from django.contrib.auth.decorators import login_required
from django_otp.plugins.otp_static.models import StaticDevice
from django_otp.plugins.otp_totp.models import TOTPDevice
from rest_framework import status
from rest_framework.permissions import IsAuthenticated
from rest_framework.response import Response
from rest_framework.views import APIView
from rest_framework.generics import ListAPIView
from two_factor.views import LoginView

from .models import ApprovalRequest, ApprovalStatus
from .rbac.forms import LegalEntityCreditRatingEvidenceUploadForm, LegalEntityCreditRatingForm, LegalEntityLicenseConstructionPerformanceEvidenceUploadForm, LegalEntityLicenseConstructionPerformanceForm, LegalEntityLicenseForm
from .rbac.models import LegalEntity, LegalEntityAccessScope, LegalEntityCreditRating, LegalEntityCreditRatingEvidence, LegalEntityLicense, LegalEntityLicenseConstructionPerformance, LegalEntityLicenseConstructionPerformanceEvidence, Role, UserLegalEntityMembership, UserProfile
from .rbac.permissions import (
    can_access_legal_entity,
    get_current_legal_entity,
    get_user_role,
    require_project_access,
    require_role,
)
from .serializers import (
    ApprovalDecisionSerializer,
    ApprovalRequestSerializer,
    ApprovalSubmitSerializer,
)
from apps.contracts.models import ContractChange, ContractChangeStatus
from apps.closing.models import ClosingPeriod
from apps.closing.guards import guard_write
from apps.cost.models import CostActual, CostActualLine, CostActualStatus
from apps.evidence.models import Evidence, EvidenceFile
from apps.evidence.services.policy import check_evidence_required
from apps.field.models import DailyReport, DailyReportLine, DailyReportStatus
from apps.inventory.models import IssueStatus, IssueToWork, MaterialRequestStatus, ProjectMaterialRequest
from apps.labor.models import Timesheet
from apps.finance.models import ExpenseExecution, ExpenseExecutionStatus
from apps.reports.models import FieldReport, FieldReportStatus
from apps.risk.dashboard_visibility import get_operational_dashboard_risk_queryset
from apps.audit.models import AuditLog
from apps.audit.services.logger import log_action
from .risk_cards import build_risk_cards
from .todo import build_hq_todos, get_risk_counts
from apps.schedule.models import DailyProgress, PlanChangeRequest, PlanChangeStatus


@login_required
def switch_current_legal_entity(request):
    """Set a navigation scope only after checking the user's membership."""
    if request.method != "POST":
        raise PermissionDenied("법인 전환은 POST 요청으로만 처리할 수 있습니다.")
    requested_scope = (request.POST.get("entity_scope") or "").upper()
    if requested_scope == "GROUP":
        entity_codes = set(
            UserLegalEntityMembership.objects.filter(
                user=request.user, is_active=True, legal_entity__is_active=True
            ).values_list("legal_entity__code", flat=True)
        )
        if not {"ASAN", "MISAN"}.issubset(entity_codes):
            raise PermissionDenied("아미산 그룹합산을 조회할 권한이 없습니다.")
        request.session["current_entity_scope"] = "GROUP"
        entity_name = "아미산(그룹합산)"
    else:
        legal_entity_queryset = LegalEntity.objects.filter(is_active=True)
        if requested_scope:
            legal_entity = get_object_or_404(legal_entity_queryset, code=requested_scope)
        else:
            legal_entity = get_object_or_404(
                legal_entity_queryset, id=request.POST.get("legal_entity_id")
            )
        if not can_access_legal_entity(request.user, legal_entity):
            raise PermissionDenied("해당 법인으로 전환할 권한이 없습니다.")
        request.session["current_legal_entity_id"] = legal_entity.id
        request.session["current_entity_scope"] = legal_entity.code
        entity_name = legal_entity.legal_name
    next_url = (request.POST.get("next") or "/app/hq/").strip()
    if not next_url.startswith("/app/") or next_url.startswith("//"):
        next_url = "/app/hq/"
    messages.success(request, f"운영 법인을 {entity_name}(으)로 전환했습니다.")
    return redirect(next_url)


@login_required
def ceo_legal_entity_access_list(request):
    """CEO-only grant screen; an HQ cannot elevate their own entity access."""
    require_role(request.user, [Role.CEO], request=request)
    entities = list(LegalEntity.objects.filter(is_active=True).order_by("code"))
    hq_profiles = UserProfile.objects.filter(role=Role.HQ).select_related("user").order_by("user__username")
    entity_ids = {entity.id for entity in entities}

    if request.method == "POST":
        profile = get_object_or_404(hq_profiles, user_id=request.POST.get("user_id"))
        selected_ids = {int(value) for value in request.POST.getlist("legal_entity_ids") if value.isdigit()}
        if not selected_ids or not selected_ids.issubset(entity_ids):
            messages.error(request, "관장할 법인을 한 곳 이상 선택해 주세요.")
        else:
            selected_entities = [entity for entity in entities if entity.id in selected_ids]
            scope = LegalEntityAccessScope.GROUP_HQ if len(selected_entities) > 1 else LegalEntityAccessScope.ENTITY_HQ
            with transaction.atomic():
                before = list(
                    UserLegalEntityMembership.objects.filter(user=profile.user, legal_entity__in=entities)
                    .values("legal_entity__code", "access_scope", "is_active")
                )
                UserLegalEntityMembership.objects.filter(user=profile.user, legal_entity__in=entities).exclude(
                    legal_entity_id__in=selected_ids
                ).update(is_active=False)
                for entity in selected_entities:
                    membership, _ = UserLegalEntityMembership.objects.get_or_create(
                        user=profile.user,
                        legal_entity=entity,
                        defaults={"access_scope": scope, "is_active": True},
                    )
                    if membership.access_scope != scope or not membership.is_active:
                        membership.access_scope = scope
                        membership.is_active = True
                        membership.save(update_fields=["access_scope", "is_active", "updated_at"])
            log_action(
                actor=request.user,
                action="LEGAL_ENTITY_HQ_ACCESS_UPDATE",
                object_type="UserLegalEntityMembership",
                object_id=profile.user_id,
                request=request,
                before={"memberships": before},
                after={"user": profile.user.username, "entities": [entity.code for entity in selected_entities], "scope": scope},
            )
            messages.success(request, "HQ 법인 관장 권한을 저장했습니다.")
            return redirect("/app/hq/legal-entity-access/")

    memberships = {
        membership.user_id: membership
        for membership in UserLegalEntityMembership.objects.filter(
            user__profile__role=Role.HQ,
            legal_entity__in=entities,
            is_active=True,
        ).select_related("legal_entity")
    }
    return render(
        request,
        "app/hq/legal_entity_access_list.html",
        {"entities": entities, "hq_profiles": hq_profiles, "memberships": memberships},
    )


@login_required
def hq_legal_entity_license_list(request, form_section=None):
    """Maintain legal-entity licence evidence within the selected entity boundary."""
    require_role(request.user, [Role.HQ, Role.CEO], request=request)
    legal_entity = get_current_legal_entity(request)
    if legal_entity is None:
        raise PermissionDenied("선택 가능한 운영 법인이 없습니다.")
    if form_section not in {None, "license", "credit_rating", "performance"}:
        raise Http404("지원하지 않는 법인·면허 관리 화면입니다.")

    action = request.POST.get("action", "license") if request.method == "POST" else "license"
    if request.method == "POST" and action in {"performance", "performance_evidence", "credit_rating", "credit_rating_evidence"}:
        require_role(request.user, [Role.HQ], request=request)
    edit_id = request.POST.get("license_id") if request.method == "POST" else request.GET.get("edit")
    performance_edit_id = (
        request.POST.get("performance_id") if request.method == "POST" else request.GET.get("performance_edit")
    )
    license_obj = None
    if edit_id:
        license_obj = get_object_or_404(LegalEntityLicense, id=edit_id, legal_entity=legal_entity)
    performance_obj = None
    if performance_edit_id:
        performance_obj = get_object_or_404(
            LegalEntityLicenseConstructionPerformance.objects.select_related("license"),
            id=performance_edit_id,
            license__legal_entity=legal_entity,
        )
    credit_rating_id = request.POST.get("credit_rating_id") if request.method == "POST" else request.GET.get("credit_edit")
    credit_rating_obj = None
    if credit_rating_id:
        credit_rating_obj = get_object_or_404(
            LegalEntityCreditRating,
            id=credit_rating_id,
            legal_entity=legal_entity,
        )

    performance_form = LegalEntityLicenseConstructionPerformanceForm(
        request.POST if request.method == "POST" and action == "performance" else None,
        request.FILES if request.method == "POST" and action == "performance" else None,
        instance=performance_obj,
        legal_entity=legal_entity,
    )
    evidence_upload_form = LegalEntityLicenseConstructionPerformanceEvidenceUploadForm(
        request.POST if request.method == "POST" and action == "performance_evidence" else None,
        request.FILES if request.method == "POST" and action == "performance_evidence" else None,
    )
    credit_rating_form = LegalEntityCreditRatingForm(
        request.POST if request.method == "POST" and action == "credit_rating" else None,
        request.FILES if request.method == "POST" and action == "credit_rating" else None,
        instance=credit_rating_obj,
    )
    credit_evidence_upload_form = LegalEntityCreditRatingEvidenceUploadForm(
        request.POST if request.method == "POST" and action == "credit_rating_evidence" else None,
        request.FILES if request.method == "POST" and action == "credit_rating_evidence" else None,
    )
    credit_evidence_rating_id = request.POST.get("credit_rating_id") if request.method == "POST" else None
    credit_evidence_rating = None
    if credit_evidence_rating_id and action == "credit_rating_evidence":
        credit_evidence_rating = get_object_or_404(
            LegalEntityCreditRating,
            id=credit_evidence_rating_id,
            legal_entity=legal_entity,
        )
    if request.method == "POST" and action == "credit_rating":
        credit_rating_before = (
            {
                "rating_agency": credit_rating_obj.rating_agency,
                "rating_grade": credit_rating_obj.rating_grade,
                "assessed_on": credit_rating_obj.assessed_on.isoformat(),
                "valid_until": credit_rating_obj.valid_until.isoformat() if credit_rating_obj.valid_until else None,
            }
            if credit_rating_obj is not None
            else None
        )
        if credit_rating_form.is_valid():
            with transaction.atomic():
                credit_rating_obj = credit_rating_form.save(commit=False)
                credit_rating_obj.legal_entity = legal_entity
                credit_rating_obj.created_by = credit_rating_obj.created_by or request.user
                credit_rating_obj.full_clean()
                credit_rating_obj.save()
                log_action(
                    actor=request.user,
                    action="LEGAL_ENTITY_CREDIT_RATING_UPDATED" if credit_rating_before else "LEGAL_ENTITY_CREDIT_RATING_CREATED",
                    object_type="LegalEntityCreditRating",
                    object_id=credit_rating_obj.id,
                    request=request,
                    before=credit_rating_before,
                    after={
                        "legal_entity": legal_entity.code,
                        "rating_agency": credit_rating_obj.rating_agency,
                        "rating_grade": credit_rating_obj.rating_grade,
                        "assessed_on": credit_rating_obj.assessed_on.isoformat(),
                        "valid_until": credit_rating_obj.valid_until.isoformat() if credit_rating_obj.valid_until else None,
                    },
                )
                file_obj = credit_rating_form.cleaned_data.get("evidence_file")
                if file_obj:
                    evidence = LegalEntityCreditRatingEvidence.objects.create(
                        credit_rating=credit_rating_obj,
                        file=file_obj,
                        original_name=file_obj.name,
                        content_type=getattr(file_obj, "content_type", "") or "application/octet-stream",
                        uploaded_by=request.user,
                    )
                    log_action(
                        actor=request.user,
                        action="LEGAL_ENTITY_CREDIT_RATING_EVIDENCE_ADDED",
                        object_type="LegalEntityCreditRating",
                        object_id=credit_rating_obj.id,
                        request=request,
                        after={"evidence_id": evidence.id},
                        meta={
                            "legal_entity": legal_entity.code,
                            "original_name": evidence.original_name,
                            "size_bytes": evidence.size_bytes,
                            "content_type": evidence.content_type,
                            "sha256": evidence.sha256,
                        },
                    )
            messages.success(request, "신용평가등급을 저장했습니다.")
            return redirect("/app/hq/legal-entity/licenses/")
        messages.error(request, "신용평가등급 입력값을 확인해 주세요.")

    if request.method == "POST" and action == "credit_rating_evidence":
        if credit_evidence_rating is None:
            messages.error(request, "증빙을 첨부할 신용평가등급을 확인해 주세요.")
        elif credit_evidence_upload_form.is_valid():
            file_obj = credit_evidence_upload_form.cleaned_data["file"]
            with transaction.atomic():
                evidence = LegalEntityCreditRatingEvidence.objects.create(
                    credit_rating=credit_evidence_rating,
                    file=file_obj,
                    original_name=file_obj.name,
                    content_type=getattr(file_obj, "content_type", "") or "application/octet-stream",
                    uploaded_by=request.user,
                )
                log_action(
                    actor=request.user,
                    action="LEGAL_ENTITY_CREDIT_RATING_EVIDENCE_ADDED",
                    object_type="LegalEntityCreditRating",
                    object_id=credit_evidence_rating.id,
                    request=request,
                    after={"evidence_id": evidence.id},
                    meta={
                        "legal_entity": legal_entity.code,
                        "original_name": evidence.original_name,
                        "size_bytes": evidence.size_bytes,
                        "content_type": evidence.content_type,
                        "sha256": evidence.sha256,
                    },
                )
            messages.success(request, "신용평가서 파일을 첨부했습니다.")
            return redirect("/app/hq/legal-entity/licenses/")
        else:
            messages.error(request, "신용평가서 파일을 확인해 주세요.")

    if request.method == "POST" and action == "performance_evidence":
        if performance_obj is None:
            messages.error(request, "증빙을 첨부할 시공 실적을 확인해 주세요.")
        elif evidence_upload_form.is_valid():
            file_obj = evidence_upload_form.cleaned_data["file"]
            with transaction.atomic():
                evidence = LegalEntityLicenseConstructionPerformanceEvidence.objects.create(
                    performance=performance_obj,
                    file=file_obj,
                    original_name=file_obj.name,
                    content_type=getattr(file_obj, "content_type", "") or "application/octet-stream",
                    uploaded_by=request.user,
                )
                log_action(
                    actor=request.user,
                    action="LEGAL_ENTITY_LICENSE_PERFORMANCE_EVIDENCE_ADDED",
                    object_type="LegalEntityLicenseConstructionPerformance",
                    object_id=performance_obj.id,
                    request=request,
                    after={"evidence_id": evidence.id},
                    meta={
                        "legal_entity": legal_entity.code,
                        "original_name": evidence.original_name,
                        "size_bytes": evidence.size_bytes,
                        "content_type": evidence.content_type,
                        "sha256": evidence.sha256,
                    },
                )
            messages.success(request, "실적증명서 파일을 첨부했습니다.")
            return redirect("/app/hq/legal-entity/licenses/")
        else:
            messages.error(request, "실적증명서 파일을 확인해 주세요.")

    if request.method == "POST" and action == "performance":
        performance_before = (
            {
                "license_id": performance_obj.license_id,
                "work_category": performance_obj.work_category,
                "as_of_date": performance_obj.as_of_date.isoformat(),
                "three_year_amount": str(performance_obj.three_year_amount),
                "five_year_amount": str(performance_obj.five_year_amount),
            }
            if performance_obj is not None
            else None
        )
        if performance_form.is_valid():
            with transaction.atomic():
                performance_obj = performance_form.save(commit=False)
                performance_obj.created_by = performance_obj.created_by or request.user
                performance_obj.full_clean()
                performance_obj.save()
                log_action(
                    actor=request.user,
                    action=(
                        "LEGAL_ENTITY_LICENSE_PERFORMANCE_UPDATED"
                        if performance_before
                        else "LEGAL_ENTITY_LICENSE_PERFORMANCE_CREATED"
                    ),
                    object_type="LegalEntityLicenseConstructionPerformance",
                    object_id=performance_obj.id,
                    request=request,
                    before=performance_before,
                    after={
                        "legal_entity": legal_entity.code,
                        "license_id": performance_obj.license_id,
                        "work_category": performance_obj.work_category,
                        "external_category_code": performance_obj.external_category_code,
                        "as_of_date": performance_obj.as_of_date.isoformat(),
                        "three_year_amount": str(performance_obj.three_year_amount),
                        "five_year_amount": str(performance_obj.five_year_amount),
                        "source": performance_obj.source,
                    },
                )
                file_obj = performance_form.cleaned_data.get("evidence_file")
                if file_obj:
                    evidence = LegalEntityLicenseConstructionPerformanceEvidence.objects.create(
                        performance=performance_obj,
                        file=file_obj,
                        original_name=file_obj.name,
                        content_type=getattr(file_obj, "content_type", "") or "application/octet-stream",
                        uploaded_by=request.user,
                    )
                    log_action(
                        actor=request.user,
                        action="LEGAL_ENTITY_LICENSE_PERFORMANCE_EVIDENCE_ADDED",
                        object_type="LegalEntityLicenseConstructionPerformance",
                        object_id=performance_obj.id,
                        request=request,
                        after={"evidence_id": evidence.id},
                        meta={
                            "legal_entity": legal_entity.code,
                            "original_name": evidence.original_name,
                            "size_bytes": evidence.size_bytes,
                            "content_type": evidence.content_type,
                            "sha256": evidence.sha256,
                        },
                    )
            messages.success(request, "공종별 시공 실적을 저장했습니다.")
            return redirect("/app/hq/legal-entity/licenses/")
        messages.error(request, "시공 실적 입력값을 확인해 주세요.")

    before_snapshot = (
        {
            "license_type": license_obj.license_type,
            "registration_number": license_obj.registration_number,
            "is_active": license_obj.is_active,
        }
        if license_obj is not None
        else None
    )

    form = LegalEntityLicenseForm(instance=license_obj)
    if request.method == "POST" and action == "license":
        form = LegalEntityLicenseForm(request.POST, instance=license_obj)
        if form.is_valid():
            with transaction.atomic():
                license_obj = form.save(commit=False)
                license_obj.legal_entity = legal_entity
                license_obj.full_clean()
                license_obj.save()
                log_action(
                    actor=request.user,
                    action="LEGAL_ENTITY_LICENSE_UPDATED" if before_snapshot else "LEGAL_ENTITY_LICENSE_CREATED",
                    object_type="LegalEntityLicense",
                    object_id=license_obj.id,
                    request=request,
                    before=before_snapshot,
                    after={
                        "legal_entity": legal_entity.code,
                        "license_type": license_obj.license_type,
                        "registration_number": license_obj.registration_number,
                        "is_active": license_obj.is_active,
                    },
                )
            messages.success(request, "법인 면허 정보를 저장했습니다.")
            return redirect("/app/hq/legal-entity/licenses/")
        messages.error(request, "면허 정보를 확인해 주세요.")
    licenses = LegalEntityLicense.objects.filter(legal_entity=legal_entity).order_by("license_type", "registration_number")
    performances = LegalEntityLicenseConstructionPerformance.objects.filter(
        license__legal_entity=legal_entity
    ).select_related("license", "created_by").prefetch_related("evidences__uploaded_by")
    credit_ratings = LegalEntityCreditRating.objects.filter(legal_entity=legal_entity).select_related("created_by").prefetch_related("evidences__uploaded_by")
    return render(
        request,
        "app/hq/legal_entity_license_list.html",
        {
            "current_legal_entity": legal_entity,
            "licenses": licenses,
            "form": form,
            "editing_license": license_obj,
            "performances": performances,
            "performance_form": performance_form,
            "editing_performance": performance_obj,
            "evidence_upload_form": evidence_upload_form,
            "credit_ratings": credit_ratings,
            "credit_rating_form": credit_rating_form,
            "editing_credit_rating": credit_rating_obj,
            "credit_evidence_upload_form": credit_evidence_upload_form,
            "form_section": form_section,
        },
    )


@login_required
def hq_legal_entity_license_performance_evidence_download(request, evidence_id):
    """Download a performance certificate only within the current legal entity."""
    require_role(request.user, [Role.HQ, Role.CEO], request=request)
    legal_entity = get_current_legal_entity(request)
    if legal_entity is None:
        raise PermissionDenied("선택 가능한 운영 법인이 없습니다.")
    evidence = get_object_or_404(
        LegalEntityLicenseConstructionPerformanceEvidence.objects.select_related(
            "performance__license__legal_entity"
        ),
        id=evidence_id,
        performance__license__legal_entity=legal_entity,
    )
    log_action(
        actor=request.user,
        action="LEGAL_ENTITY_LICENSE_PERFORMANCE_EVIDENCE_DOWNLOADED",
        object_type="LegalEntityLicenseConstructionPerformance",
        object_id=evidence.performance_id,
        request=request,
        meta={"evidence_id": evidence.id, "original_name": evidence.original_name},
    )
    return FileResponse(
        evidence.file.open("rb"),
        as_attachment=True,
        filename=evidence.original_name,
        content_type=evidence.content_type or "application/octet-stream",
    )


@login_required
def hq_legal_entity_credit_rating_evidence_download(request, evidence_id):
    """Download a credit-rating source file only within the current legal entity."""
    require_role(request.user, [Role.HQ, Role.CEO], request=request)
    legal_entity = get_current_legal_entity(request)
    if legal_entity is None:
        raise PermissionDenied("선택 가능한 운영 법인이 없습니다.")
    evidence = get_object_or_404(
        LegalEntityCreditRatingEvidence.objects.select_related("credit_rating__legal_entity"),
        id=evidence_id,
        credit_rating__legal_entity=legal_entity,
    )
    log_action(
        actor=request.user,
        action="LEGAL_ENTITY_CREDIT_RATING_EVIDENCE_DOWNLOADED",
        object_type="LegalEntityCreditRating",
        object_id=evidence.credit_rating_id,
        request=request,
        meta={"evidence_id": evidence.id, "original_name": evidence.original_name},
    )
    return FileResponse(
        evidence.file.open("rb"),
        as_attachment=True,
        filename=evidence.original_name,
        content_type=evidence.content_type or "application/octet-stream",
    )


DASHBOARD_RECENT_APPROVAL_ACTIONS = (
    "APPROVAL_APPROVE",
    "APPROVAL_REJECT",
    "CONTRACT_SUBMIT",
    "CONTRACT_REJECT",
    "PLAN_CHANGE_SUBMIT",
    "PLAN_CHANGE_REJECT",
    "MONTH_CLOSED",
    "CLOSING_REQUEST_APPROVE",
    "CLOSING_REQUEST_REJECT",
)


def get_dashboard_recent_approval_actions(limit: int = 3, *, legal_entity=None):
    """Return operational approval history only for active projects in scope.

    AuditLog is deliberately preserved across local project resets. Projectless
    audit rows therefore remain in the ledger but are not current HQ work.
    """
    actions = AuditLog.objects.filter(
        action__in=DASHBOARD_RECENT_APPROVAL_ACTIONS,
        project__is_active=True,
    )
    if legal_entity is not None:
        # Approval history is operational evidence of a project.  Do not show
        # projectless audit rows in an entity hub because their owner cannot be
        # safely determined from the audit row alone.
        actions = actions.filter(project__legal_entity=legal_entity)
    return list(actions.select_related("actor", "project").order_by("-created_at")[:limit])


def _resolve_env_name() -> str:
    env_name = getattr(settings, "ENV_NAME", "")
    if env_name:
        return str(env_name)

    settings_module = os.getenv("DJANGO_SETTINGS_MODULE", "")
    if "local" in settings_module:
        return "local"
    if "prod" in settings_module:
        return "prod"
    return "unknown"


def health_view(request):
    return JsonResponse(
        {
            "status": "ok",
            "env": _resolve_env_name(),
            "version": "0.1.0",
        }
    )


def healthz_view(request):
    db_status = "ok"
    status_code = 200
    try:
        with connections["default"].cursor() as cursor:
            cursor.execute("SELECT 1")
            cursor.fetchone()
    except OperationalError:
        db_status = "fail"
        status_code = 503
    return JsonResponse(
        {
            "status": "ok" if db_status == "ok" else "fail",
            "service": "construction-erp",
            "time": timezone.now().isoformat(),
            "db": db_status,
        },
        status=status_code,
    )


def login_view(request):
    next_url = request.GET.get("next") or request.POST.get("next") or "/app/"
    context = {"next": next_url, "error": ""}
    if request.method == "POST":
        username = (request.POST.get("username") or "").strip()
        password = request.POST.get("password") or ""
        user = authenticate(request, username=username, password=password)
        if user is None:
            context["error"] = "Invalid username or password."
        else:
            login(request, user)
            return redirect(next_url)
    return render(request, "auth/login.html", context)


def _is_2fa_required(user) -> bool:
    role = get_user_role(user)
    if role not in (Role.CEO, Role.HQ, Role.FIELD):
        return False
    if role == Role.FIELD and not getattr(settings, "FIELD_2FA_REQUIRED", False):
        return False
    return True


def _user_has_otp_device(user) -> bool:
    return (
        TOTPDevice.objects.filter(user=user, confirmed=True).exists()
        or StaticDevice.objects.filter(user=user).exists()
    )


class ERPLoginView(LoginView):
    template_name = "auth/login.html"

    def dispatch(self, request, *args, **kwargs):
        next_url = request.GET.get("next") or request.POST.get("next") or "/app/"
        user = request.user
        if user.is_authenticated:
            if getattr(user, "is_verified", lambda: False)():
                return redirect(next_url)
            if not _is_2fa_required(user):
                return redirect(next_url)
            if not _user_has_otp_device(user):
                return redirect(f"/account/two_factor/setup/?next={next_url}")
        return super().dispatch(request, *args, **kwargs)

    def get_context_data(self, **kwargs):
        context = super().get_context_data(**kwargs)
        context["next_url"] = self.request.GET.get("next") or "/app/"
        return context


def logout_view(request):
    if request.method != "POST":
        return JsonResponse({"detail": "Method not allowed."}, status=405)
    logout(request)
    return redirect("/")


@login_required
def app_entry(request):
    role = get_user_role(request.user)
    if role == "ceo":
        return redirect("/app/ceo/")
    if role == "hq":
        return redirect("/app/hq/")
    return redirect("/app/field/")


@login_required
def hq_app_view(request):
    require_role(request.user, [Role.HQ, Role.CEO])
    legal_entity = get_current_legal_entity(request)
    if legal_entity is None:
        raise PermissionDenied("선택 가능한 운영 법인이 없습니다.")

    # The FIELD "진행률" tab is backed by DailyProgress.  DailyReport is a
    # cost-input source record and has no independent HQ/CEO approval action;
    # showing submitted DailyReports here created phantom approval work after
    # the linked CostActual had already been approved.
    pending_reports = list(
        DailyProgress.objects.filter(project__legal_entity=legal_entity, status="submitted")
        .select_related("project", "task", "reporter")
        .order_by("-report_date", "-updated_at")[:10]
    )
    pending_costs = list(
        CostActual.objects.filter(project__legal_entity=legal_entity, status=CostActualStatus.SUBMITTED)
        .select_related("project")
        .order_by("-report_date")[:10]
    )
    pending_plan_changes = list(
        PlanChangeRequest.objects.filter(project__legal_entity=legal_entity, status=PlanChangeStatus.SUBMITTED)
        .select_related("project", "base_plan")
        .order_by("-requested_at")[:10]
    )
    pending_contract_changes = list(
        ContractChange.objects.filter(project__legal_entity=legal_entity, status=ContractChangeStatus.SUBMITTED)
        .select_related("project")
        .order_by("-submitted_at")[:10]
    )
    pending_material_requests = list(
        ProjectMaterialRequest.objects.filter(project__legal_entity=legal_entity, status=MaterialRequestStatus.SUBMITTED)
        .select_related("project", "requested_by").order_by("requested_at")[:10]
    )
    expense_executions = list(
        ExpenseExecution.objects.filter(
            status__in=[ExpenseExecutionStatus.READY, ExpenseExecutionStatus.SCHEDULED],
            cost_actual__project__is_active=True,
            cost_actual__project__legal_entity=legal_entity,
        )
        .select_related("cost_actual__project")
        .order_by("scheduled_date", "-created_at")[:10]
    )

    risk_open = list(
        get_operational_dashboard_risk_queryset().filter(project__legal_entity=legal_entity).order_by("-created_at")[:10]
    )
    risk_cards = build_risk_cards(risk_open, limit=5)
    risk_counts = get_risk_counts(legal_entity=legal_entity)
    todos = build_hq_todos(risk_counts, legal_entity=legal_entity)

    recent_actions = get_dashboard_recent_approval_actions(legal_entity=legal_entity)

    evidence_missing = []
    for change in pending_contract_changes:
        ok, reason = check_evidence_required(
            "CONTRACT_CHANGE", change.id, when_status="SUBMIT"
        )
        if not ok:
            evidence_missing.append(
                {
                    "object_type": "CONTRACT_CHANGE",
                    "object_id": change.id,
                    "project": change.project,
                    "reason": reason,
                }
            )

    for plan in pending_plan_changes:
        ok, reason = check_evidence_required(
            "PLAN_CHANGE_REQUEST", plan.id, when_status="SUBMIT"
        )
        if not ok:
            evidence_missing.append(
                {
                    "object_type": "PLAN_CHANGE_REQUEST",
                    "object_id": plan.id,
                    "project": plan.project,
                    "reason": reason,
                }
            )

    context = {
        "pending_reports": pending_reports,
        "pending_costs": pending_costs,
        "pending_plan_changes": pending_plan_changes,
        "pending_contract_changes": pending_contract_changes,
        "pending_material_requests": pending_material_requests,
        "expense_executions": expense_executions,
        "risk_cards": risk_cards["cards"],
        "risk_summary": risk_cards["summary"],
        "todo_items": todos["items"],
        "todo_all_clear": todos["all_clear"],
        "recent_actions": recent_actions,
        "evidence_missing": evidence_missing,
        "admin_change_url": admin_change_url,
        "role": get_user_role(request.user),
        "cbs_url": "/app/hq/master/cbs/",
        "quick_links": [
            {"label": "\uae30\uc131\u00b7\uc900\uacf5 \ubcf4\uace0\uc11c", "url": "/app/hq/billing/reports/"},
            {"label": "\uc2b9\uc778\ud568 \uc5f4\uae30", "url": "/app/hq/inbox/"},
            {"label": "\uc6d4 \ub9c8\uac10 \uad00\ub9ac", "url": "/app/hq/closing/"},
            {"label": "\ud504\ub85c\uc81d\ud2b8 \ubaa9\ub85d", "url": "/app/hq/projects/"},
            {"label": "\ube44\uc6a9 \uc9d1\ud589 \uad00\ub9ac", "url": "/app/hq/finance/expense-executions/?status=open"},
        ],
    }
    return render(request, "app/hq_home.html", context)




def _maybe_redirect_ceo_to_ceo_path(request):
    """Keep CEO navigation inside /app/ceo/* even when /app/hq/* URLs are opened."""
    role = get_user_role(request.user)
    if role in (Role.CEO, "ceo", "CEO") and request.path.startswith("/app/hq/"):
        ceo_path = request.path.replace("/app/hq/", "/app/ceo/", 1)
        query_string = request.META.get("QUERY_STRING")
        if query_string:
            ceo_path = f"{ceo_path}?{query_string}"
        return redirect(ceo_path)
    return None

@login_required
def hq_inbox_view(request):
    require_role(request.user, [Role.HQ, Role.CEO])
    ceo_redirect = _maybe_redirect_ceo_to_ceo_path(request)
    if ceo_redirect is not None:
        return ceo_redirect
    role = get_user_role(request.user)
    legal_entity = get_current_legal_entity(request)
    if legal_entity is None:
        raise PermissionDenied("선택 가능한 운영 법인이 없습니다.")
    is_ceo_role = role in (Role.CEO, "ceo", "CEO") or request.path.startswith("/app/ceo/")
    app_prefix = _app_prefix_for_request(request)
    scope = (request.GET.get("scope") or "pending").strip().lower()
    if scope not in {"pending", "approved"}:
        scope = "pending"
    approved_kind = (request.GET.get("kind") or "all").strip().lower()
    if approved_kind not in {"all", "progress", "report", "cost", "material"}:
        approved_kind = "all"

    approval_status = (
        ApprovalStatus.APPROVED if scope == "approved" else ApprovalStatus.SUBMITTED
    )
    approval_order = (
        ("-approved_at", "-updated_at", "-created_at")
        if scope == "approved"
        else ("-submitted_at", "-created_at")
    )

    approvals = list(
        ApprovalRequest.objects.filter(status=approval_status)
        .select_related("submitted_by")
        .order_by(*approval_order)[:200]
    )
    approval_by_id = {approval.id: approval for approval in approvals}

    approvals_for_seen = list(
        ApprovalRequest.objects.filter(
            status__in=[
                ApprovalStatus.SUBMITTED,
                ApprovalStatus.APPROVED,
                ApprovalStatus.REJECTED,
            ]
        ).only("id", "object_type", "object_id", "status")
    )
    approval_by_id_for_seen = {approval.id: approval for approval in approvals_for_seen}

    def _normalize_object_type(object_type):
        normalized = (object_type or "").upper().strip()
        aliases = {
            "COST": "COST_ACTUAL",
            "COSTACTUAL": "COST_ACTUAL",
            "DAILYPROGRESS": "DAILY_PROGRESS",
            "FIELDREPORT": "FIELD_REPORT",
            "DAILYREPORT": "DAILY_REPORT",
        }
        return aliases.get(normalized, normalized)

    def _resolved_approval_object(approval_obj):
        object_type = _normalize_object_type(getattr(approval_obj, "object_type", ""))
        object_id = getattr(approval_obj, "object_id", None)
        visited = set()
        # Some rows point to another approval row. Unwrap to the final business object.
        while object_type == "APPROVAL_REQUEST" and object_id and object_id not in visited:
            visited.add(object_id)
            nested = approval_by_id.get(object_id)
            if nested is None:
                nested = ApprovalRequest.objects.filter(id=object_id).first()
                if nested is not None:
                    approval_by_id[nested.id] = nested
            if nested is None:
                break
            object_type = _normalize_object_type(nested.object_type or "")
            object_id = nested.object_id
        return object_type, object_id

    pending_field_reports = []
    pending_costs = []
    pending_plan_changes = []
    pending_contract_changes = []
    if scope == "pending":
        pending_field_reports = list(
            FieldReport.objects.filter(project__legal_entity=legal_entity, status=FieldReportStatus.SUBMITTED)
            .select_related("project", "created_by")
            .order_by("-submitted_at", "-updated_at")[:100]
        )
        pending_costs = list(
            CostActual.objects.filter(project__legal_entity=legal_entity, status=CostActualStatus.SUBMITTED)
            .select_related("project")
            .order_by("-report_date")[:100]
        )
        pending_plan_changes = list(
            PlanChangeRequest.objects.filter(project__legal_entity=legal_entity, status=PlanChangeStatus.SUBMITTED)
            .select_related("project")
            .order_by("-requested_at")[:100]
        )
        pending_contract_changes = list(
            ContractChange.objects.filter(project__legal_entity=legal_entity, status=ContractChangeStatus.SUBMITTED)
            .select_related("project")
            .order_by("-submitted_at")[:100]
        )

    direct_items = []
    for report in pending_field_reports:
        direct_items.append(
            {
                "type": "기존 현장보고",
                "project": report.project.name if report.project_id else "-",
                "submitted_at": report.submitted_at or report.updated_at,
                "submitted_by": report.created_by.username if report.created_by_id else "-",
                "detail_url": f"{app_prefix}/field-reports/{report.id}/",
                "object_type": "FIELD_REPORT",
                "object_id": report.id,
            }
        )
    for cost in pending_costs:
        direct_items.append(
            {
                "type": "원가",
                "project": cost.project.name if cost.project_id else "-",
                "submitted_at": cost.report_date,
                "submitted_by": "-",
                "detail_url": f"{app_prefix}/costs/{cost.id}/",
                "object_type": "COST_ACTUAL",
                "object_id": cost.id,
            }
        )
    for change in pending_plan_changes:
        direct_items.append(
            {
                "type": "변경요청(계획)",
                "project": change.project.name if change.project_id else "-",
                "submitted_at": change.requested_at,
                "submitted_by": "-",
                "detail_url": f"{app_prefix}/plan-change-requests/{change.id}/",
                "object_type": "PLAN_CHANGE_REQUEST",
                "object_id": change.id,
            }
        )
    for change in pending_contract_changes:
        direct_items.append(
            {
                "type": "변경요청(계약)",
                "project": change.project.name if change.project_id else "-",
                "submitted_at": change.submitted_at,
                "submitted_by": "-",
                "detail_url": f"{app_prefix}/contract-changes/{change.id}/",
                "object_type": "CONTRACT_CHANGE",
                "object_id": change.id,
            }
        )

    direct_items_by_key = {}
    for item in direct_items:
        key = (item.get("object_type"), item.get("object_id"))
        if key[0] and key[1]:
            direct_items_by_key[key] = item

    items = []
    seen_keys = set()
    for approval in approvals:
        approval_object_type, approval_object_id = _resolved_approval_object(approval)
        # DailyReport is retained as a CostActual source record for legacy
        # compatibility.  It must not appear as a separate approval work item.
        if approval_object_type == "DAILY_REPORT":
            continue
        key = (approval_object_type, approval_object_id)
        if key[0] and key[1] and key in seen_keys:
            # Keep only the newest approval row per business object.
            continue
        seen_keys.add(key)
        object_detail_url = _resolve_object_detail_url(
            approval_object_type,
            approval_object_id,
            app_prefix,
        )
        direct_item = direct_items_by_key.get(key)
        project_name = "-"
        if direct_item is not None:
            project_name = direct_item.get("project") or "-"
        if project_name == "-":
            project_name = _resolve_object_project_name(
                approval_object_type,
                approval_object_id,
            )
        items.append(
            {
                "type": _approval_object_label_ko(approval_object_type),
                "project": project_name or "-",
                "submitted_at": (
                    approval.approved_at or approval.updated_at or approval.created_at
                    if scope == "approved"
                    else approval.submitted_at or approval.created_at
                ),
                "submitted_by": approval.submitted_by.username
                if approval.submitted_by_id
                else "-",
                "detail_url": (
                    object_detail_url
                    if scope == "approved" and object_detail_url
                    else f"{app_prefix}/approvals/{approval.id}/"
                ),
                "object_type": approval_object_type,
                "object_id": approval_object_id,
            }
        )

    seen_keys_any_status = set()
    for approval in approvals_for_seen:
        resolved_type, resolved_id = _resolved_approval_object(approval)
        if resolved_type and resolved_id:
            seen_keys_any_status.add((resolved_type, resolved_id))

    # CEO inbox is action-oriented: show only approval queue rows to avoid mixed-source duplicates.
    if scope == "pending" and not is_ceo_role:
        for key, direct_item in direct_items_by_key.items():
            if key in seen_keys_any_status:
                continue
            items.append(direct_item)

    def _item_in_current_entity(item):
        object_type = (item.get("object_type") or "").upper()
        object_id = item.get("object_id")
        if not object_id:
            return False
        project_models = {
            "COST_ACTUAL": CostActual,
            "DAILY_REPORT": DailyReport,
            "DAILY_PROGRESS": DailyProgress,
            "FIELD_REPORT": FieldReport,
            "CONTRACT_CHANGE": ContractChange,
            "PLAN_CHANGE_REQUEST": PlanChangeRequest,
            "TIMESHEET": Timesheet,
        }
        model = project_models.get(object_type)
        if model is not None:
            return model.objects.filter(id=object_id, project__legal_entity=legal_entity).exists()
        if object_type == "CLOSING_PERIOD":
            return ClosingPeriod.objects.filter(id=object_id, legal_entity=legal_entity).exists()
        return False

    items = [item for item in items if _item_in_current_entity(item)]

    attachments_map = {}
    evidence_query = Q()
    for item in items:
        object_type = item.get("object_type")
        object_id = item.get("object_id")
        if object_type and object_id:
            evidence_query |= Q(object_type=object_type, object_id=object_id)
    if evidence_query:
        evidences = Evidence.objects.filter(evidence_query).prefetch_related("files")
        for evidence in evidences:
            key = (evidence.object_type, evidence.object_id)
            attachments_map.setdefault(key, []).extend(
                list(evidence.files.all().order_by("-created_at"))
            )
    for item in items:
        key = (item.get("object_type"), item.get("object_id"))
        item["attachments"] = attachments_map.get(key, [])
        submitted_at = item.get("submitted_at")
        if isinstance(submitted_at, datetime):
            item["submitted_at_display"] = timezone.localtime(submitted_at).strftime(
                "%Y-%m-%d %H:%M"
            )
        elif isinstance(submitted_at, date):
            item["submitted_at_display"] = submitted_at.strftime("%Y-%m-%d")
        else:
            item["submitted_at_display"] = "-"

    def _submitted_sort_value(value):
        if value is None:
            return timezone.now()
        if isinstance(value, datetime):
            return value
        if isinstance(value, date):
            return timezone.make_aware(datetime.combine(value, time.min))
        return timezone.now()

    items.sort(
        key=lambda item: _submitted_sort_value(item.get("submitted_at")), reverse=True
    )

    approved_material_items = []
    if scope == "approved":
        material_issues = IssueToWork.objects.filter(
            project__legal_entity=legal_entity,
            status=IssueStatus.APPROVED,
        ).select_related("project", "created_by", "cost_actual")
        material_project_id = request.GET.get("project_id")
        if str(material_project_id).isdigit():
            material_issues = material_issues.filter(project_id=material_project_id)
        try:
            material_as_of_date = date.fromisoformat(request.GET.get("as_of_date") or "")
        except ValueError:
            material_as_of_date = None
        if material_as_of_date:
            material_issues = material_issues.filter(issue_date__lte=material_as_of_date)
        material_issues = material_issues.order_by("-approved_at", "-issue_date", "-id")[:200]
        for issue in material_issues:
            approved_material_items.append(
                {
                    "type": f"자재투입 · {issue.issue_no}",
                    "project": issue.project.name,
                    "submitted_at": issue.approved_at or issue.updated_at or issue.issue_date,
                    "submitted_by": issue.created_by.username if issue.created_by_id else "-",
                    # The linked cost detail preserves the approved monetary evidence;
                    # the list itself is the material-issue source confirmation.
                    "detail_url": f"{app_prefix}/costs/{issue.cost_actual_id}/" if issue.cost_actual_id else "",
                    "object_type": "ISSUE_TO_WORK",
                    "object_id": issue.id,
                    "source_number": issue.issue_no,
                }
            )

    approved_kind_to_types = {
        "progress": {"DAILY_PROGRESS"},
        "report": {"FIELD_REPORT"},
        "cost": {"COST_ACTUAL"},
        "material": {"ISSUE_TO_WORK"},
    }
    approved_counts = {"all": len(items), "progress": 0, "report": 0, "cost": 0, "material": len(approved_material_items)}
    if scope == "approved":
        for item in items:
            object_type = (item.get("object_type") or "").upper()
            if object_type in approved_kind_to_types["progress"]:
                approved_counts["progress"] += 1
            if object_type in approved_kind_to_types["report"]:
                approved_counts["report"] += 1
            if object_type in approved_kind_to_types["cost"]:
                approved_counts["cost"] += 1
        if approved_kind == "material":
            items = approved_material_items
        elif approved_kind != "all":
            allowed_types = approved_kind_to_types.get(approved_kind, set())
            items = [
                item
                for item in items
                if (item.get("object_type") or "").upper() in allowed_types
            ]

    is_ceo = is_ceo_role
    context = {
        "items": items[:200],
        "role": role,
        "dashboard_home_url": "/app/ceo/" if is_ceo else "/app/hq/",
        "dashboard_home_label": "CEO 대시보드" if is_ceo else "HQ 대시보드",
        "scope": scope,
        "inbox_title": "승인 완료 목록" if scope == "approved" else "승인 대기 목록",
        "inbox_subtitle": (
            "승인 완료 항목을 확인합니다."
            if scope == "approved"
            else "승인 대기 항목을 빠르게 확인합니다."
        ),
        "inbox_empty_message": (
            "승인 완료 항목이 없습니다."
            if scope == "approved"
            else "승인 대기 항목이 없습니다."
        ),
        "inbox_time_label": "승인일시" if scope == "approved" else "제출일시",
        "approved_kind": approved_kind,
        "approved_counts": approved_counts,
    }
    return render(request, "app/hq_inbox.html", context)


@login_required
def hq_risk_list_view(request):
    require_role(request.user, [Role.HQ, Role.CEO])
    legal_entity = get_current_legal_entity(request)
    if legal_entity is None:
        raise PermissionDenied("선택 가능한 운영 법인이 없습니다.")
    findings = list(
        get_operational_dashboard_risk_queryset()
        .filter(project__legal_entity=legal_entity)
        .order_by("-created_at")[:200]
    )
    cards = build_risk_cards(findings, limit=200)
    context = {
        "risk_cards": cards["cards"],
        "risk_summary": cards["summary"],
        "role": get_user_role(request.user),
    }
    return render(request, "app/hq_risk_list.html", context)


@login_required
def hq_missing_list_view(request):
    require_role(request.user, [Role.HQ, Role.CEO])
    today = timezone.localdate()
    legal_entity = get_current_legal_entity(request)
    if legal_entity is None:
        raise PermissionDenied("선택 가능한 운영 법인이 없습니다.")
    pending_reports = list(
        DailyReport.objects.filter(
            project__legal_entity=legal_entity, status=DailyReportStatus.DRAFT, report_date=today
        )
        .select_related("project", "reporter")
        .order_by("-updated_at")[:200]
    )
    pending_costs = list(
        CostActual.objects.filter(project__legal_entity=legal_entity, status=CostActualStatus.DRAFT, report_date=today)
        .select_related("project")
        .order_by("-updated_at")[:200]
    )
    pending_progress = list(
        DailyProgress.objects.filter(project__legal_entity=legal_entity, status="draft", report_date=today)
        .select_related("project", "task", "reporter")
        .order_by("-updated_at")[:200]
    )
    context = {
        "today": today,
        "pending_reports": pending_reports,
        "pending_costs": pending_costs,
        "pending_progress": pending_progress,
        "role": get_user_role(request.user),
    }
    return render(request, "app/hq_missing_list.html", context)


@login_required
def hq_daily_report_detail(request, report_id: int):
    require_role(request.user, [Role.HQ, Role.CEO])
    ceo_redirect = _maybe_redirect_ceo_to_ceo_path(request)
    if ceo_redirect is not None:
        return ceo_redirect
    report = get_object_or_404(
        DailyReport.objects.select_related("project", "reporter"),
        id=report_id,
    )
    lines = list(
        DailyReportLine.objects.filter(report=report)
        .select_related("cost_item")
        .order_by("id")
    )
    inbox_nav = _inbox_nav_for_status(request, str(report.status).upper())
    context = {
        "report": report,
        "lines": lines,
        "attachments": _get_attachments_for_object("DAILY_REPORT", report.id),
        "role": get_user_role(request.user),
        "current_legal_entity": legal_entity,
        "current_legal_entity": legal_entity,
        "inbox_url": inbox_nav["url"],
        "inbox_label": inbox_nav["label"],
    }
    return render(request, "app/hq/daily_report_detail.html", context)


@login_required
def hq_cost_actual_detail(request, cost_actual_id: int):
    require_role(request.user, [Role.HQ, Role.CEO])
    ceo_redirect = _maybe_redirect_ceo_to_ceo_path(request)
    if ceo_redirect is not None:
        return ceo_redirect
    cost_actual = get_object_or_404(
        CostActual.objects.select_related("project", "approved_by"),
        id=cost_actual_id,
    )
    lines = list(
        CostActualLine.objects.filter(cost_actual=cost_actual)
        .select_related("cost_item")
        .order_by("id")
    )
    inbox_nav = _inbox_nav_for_status(request, str(cost_actual.status).upper())
    labels = {
        "page_title": "원가 상세",
        "inbox": inbox_nav["label"],
        "approve": "승인",
        "reject": "반려",
        "reject_prompt": "반려 사유를 입력하세요.",
        "reject_prompt_empty": "반려 사유를 입력하세요.",
        "basic": "기본 정보",
        "status": "상태",
        "total": "합계",
        "created_at": "작성일시",
        "approved_by": "승인자",
        "lines": "원가 내역",
        "item": "원가 항목",
        "description": "설명",
        "quantity": "수량",
        "unit_price": "단가",
        "amount": "금액",
        "empty": "내역이 없습니다.",
        "attachment_object": "원가",
        "attachment_help": "승인 상세에서는 첨부를 조회할 수 있습니다.",
    }
    role = get_user_role(request.user)
    is_ceo = role in (Role.CEO, "ceo", "CEO")
    approval_request = (
        ApprovalRequest.objects.filter(
            status=ApprovalStatus.SUBMITTED,
            object_type="COST_ACTUAL",
            object_id=cost_actual.id,
        )
        .order_by("-submitted_at", "-created_at")
        .first()
    )
    can_ceo_approve = (
        is_ceo
        and approval_request is not None
        and str(cost_actual.status).upper() == "SUBMITTED"
    )
    context = {
        "cost_actual": cost_actual,
        "lines": lines,
        "attachments": _get_attachments_for_object("COST_ACTUAL", cost_actual.id),
        "role": role,
        "inbox_url": inbox_nav["url"],
        "labels": labels,
        "can_ceo_approve": can_ceo_approve,
        "ceo_approve_url": "/app/ceo/approvals/approve/",
        "ceo_approval_request_id": approval_request.id if approval_request else None,
        "return_url": request.get_full_path(),
        "can_correct_report_date": role == Role.HQ and str(cost_actual.status).upper()
        in {"DRAFT", "SUBMITTED", "REJECTED"},
        "correction_max_date": timezone.localdate().isoformat(),
    }
    return render(request, "app/hq/cost_actual_detail.html", context)


@login_required
def hq_cost_actual_correct_report_date(request, cost_actual_id: int):
    """Correct an unapproved cost occurrence date with a complete audit trail.

    Submitted costs are returned to FIELD rework because a date change changes
    the approval basis. Approved or closed records must use Adjustment policy.
    """
    require_role(request.user, [Role.HQ])
    if request.method != "POST":
        raise Http404

    cost_actual = get_object_or_404(
        CostActual.objects.select_related("project", "source_daily_report"),
        id=cost_actual_id,
    )
    back_url = f"/app/hq/costs/{cost_actual.id}/"
    try:
        corrected_date = date.fromisoformat((request.POST.get("report_date") or "").strip())
    except ValueError:
        messages.error(request, "정정할 원가 발생일을 선택해 주세요.")
        return redirect(back_url)

    reason = (request.POST.get("reason") or "").strip()
    if not reason:
        messages.error(request, "날짜 정정 사유를 입력해 주세요.")
        return redirect(back_url)
    if corrected_date > timezone.localdate():
        messages.error(request, "미래 날짜로는 원가 발생일을 정정할 수 없습니다.")
        return redirect(back_url)
    if corrected_date == cost_actual.report_date:
        messages.error(request, "기존 원가 발생일과 다른 날짜를 선택해 주세요.")
        return redirect(back_url)
    if str(cost_actual.status).upper() in {"APPROVED", "CLOSED"}:
        messages.error(request, "승인 완료 또는 마감 원가는 직접 날짜 정정할 수 없습니다. 정정 절차를 이용해 주세요.")
        return redirect(back_url)

    try:
        with transaction.atomic():
            cost_actual = (
                CostActual.objects.select_for_update()
                .select_related("project")
                .get(id=cost_actual_id)
            )
            if str(cost_actual.status).upper() in {"APPROVED", "CLOSED"}:
                raise PermissionDenied("승인 완료 또는 마감 원가는 직접 날짜 정정할 수 없습니다.")
            guard_write(
                project=cost_actual.project,
                target_date=cost_actual.report_date,
                message_context="원가 날짜 정정입니다.",
                exc=PermissionDenied,
            )
            guard_write(
                project=cost_actual.project,
                target_date=corrected_date,
                message_context="원가 날짜 정정입니다.",
                exc=PermissionDenied,
            )

            old_date = cost_actual.report_date
            old_status = cost_actual.status
            # source_daily_report is nullable. PostgreSQL rejects FOR UPDATE
            # against a nullable outer-joined relation, so acquire its lock in
            # a separate query after locking the owning CostActual row.
            source_report = None
            if cost_actual.source_daily_report_id:
                source_report = DailyReport.objects.select_for_update().filter(
                    id=cost_actual.source_daily_report_id
                ).first()
            cost_actual.report_date = corrected_date
            update_fields = ["report_date", "updated_at"]
            if str(cost_actual.status).upper() == "SUBMITTED":
                cost_actual.status = CostActualStatus.REJECTED
                update_fields.append("status")
            cost_actual.save(update_fields=update_fields)

            if source_report is not None:
                source_report.report_date = corrected_date
                report_update_fields = ["report_date", "updated_at"]
                if str(source_report.status).upper() == "SUBMITTED":
                    source_report.status = DailyReportStatus.REJECTED
                    report_update_fields.append("status")
                source_report.save(update_fields=report_update_fields)

            if str(old_status).upper() == "SUBMITTED":
                approval = (
                    ApprovalRequest.objects.select_for_update()
                    .filter(
                        object_type="COST_ACTUAL",
                        object_id=cost_actual.id,
                        status=ApprovalStatus.SUBMITTED,
                    )
                    .order_by("-submitted_at", "-created_at")
                    .first()
                )
                if approval is not None:
                    approval.status = ApprovalStatus.REJECTED
                    approval.reject_reason = f"HQ 날짜 정정: {old_date} → {corrected_date}. {reason}"
                    approval.save(update_fields=["status", "reject_reason", "updated_at"])

            log_action(
                actor=request.user,
                action="COST_ACTUAL_REPORT_DATE_CORRECT",
                object_type="COST_ACTUAL",
                object_id=cost_actual.id,
                project=cost_actual.project,
                request=request,
                before={"report_date": str(old_date), "status": old_status},
                after={"report_date": str(corrected_date), "status": cost_actual.status},
                meta={"reason": reason, "source_report_id": cost_actual.source_daily_report_id},
            )
    except PermissionDenied as exc:
        messages.error(request, str(exc))
        return redirect(back_url)

    if str(old_status).upper() == "SUBMITTED":
        messages.success(request, "원가 발생일을 정정하고 FIELD 재제출 상태로 전환했습니다.")
    else:
        messages.success(request, "원가 발생일을 정정했습니다.")
    return redirect(back_url)


@login_required
def hq_daily_progress_detail(request, progress_id: int):
    require_role(request.user, [Role.HQ, Role.CEO])
    ceo_redirect = _maybe_redirect_ceo_to_ceo_path(request)
    if ceo_redirect is not None:
        return ceo_redirect
    progress = get_object_or_404(
        DailyProgress.objects.select_related("project", "task", "reporter"),
        id=progress_id,
    )
    progress_evidence = (
        Evidence.objects.filter(
            object_type="DAILY_PROGRESS",
            object_id=progress.id,
        )
        .prefetch_related("files")
        .order_by("-created_at")
        .first()
    )
    evidence_files = []
    if progress_evidence is not None:
        evidence_files = list(progress_evidence.files.order_by("-created_at"))

    role = get_user_role(request.user)
    is_ceo = role in (Role.CEO, "ceo", "CEO")
    approval_request = (
        ApprovalRequest.objects.filter(
            status=ApprovalStatus.SUBMITTED,
            object_type="DAILY_PROGRESS",
            object_id=progress.id,
        )
        .order_by("-submitted_at", "-created_at")
        .first()
    )
    can_ceo_approve = (
        is_ceo
        and approval_request is not None
        and str(progress.status).upper() == "SUBMITTED"
    )

    inbox_nav = _inbox_nav_for_status(request, str(progress.status).upper())
    context = {
        "progress": progress,
        "progress_evidence": progress_evidence,
        "evidence_files": evidence_files,
        "role": role,
        "inbox_url": inbox_nav["url"],
        "inbox_label": inbox_nav["label"],
        "can_ceo_approve": can_ceo_approve,
        "ceo_approve_url": "/app/ceo/approvals/approve/",
        "ceo_approval_request_id": approval_request.id if approval_request else None,
        "return_url": request.get_full_path(),
    }
    return render(request, "app/hq/daily_progress_detail.html", context)


@login_required
def hq_field_report_detail(request, field_report_id: int):
    require_role(request.user, [Role.HQ, Role.CEO])
    ceo_redirect = _maybe_redirect_ceo_to_ceo_path(request)
    if ceo_redirect is not None:
        return ceo_redirect
    report = get_object_or_404(
        FieldReport.objects.select_related("project", "created_by"),
        id=field_report_id,
    )
    role = get_user_role(request.user)
    is_ceo = role in (Role.CEO, "ceo", "CEO")
    approval_request = (
        ApprovalRequest.objects.filter(
            status=ApprovalStatus.SUBMITTED,
            object_type="FIELD_REPORT",
            object_id=report.id,
        )
        .order_by("-submitted_at", "-created_at")
        .first()
    )
    can_ceo_approve = (
        is_ceo
        and approval_request is not None
        and str(report.status).upper() == "SUBMITTED"
    )
    report_files = list(report.files.order_by("-uploaded_at", "-id"))
    evidence_files = _get_attachments_for_object("FIELD_REPORT", report.id)
    merged_files = []
    seen_file_ids = set()
    for file_obj in report_files + evidence_files:
        file_id = getattr(file_obj, "id", None)
        if file_id and file_id in seen_file_ids:
            continue
        if file_id:
            seen_file_ids.add(file_id)
        merged_files.append(file_obj)
    inbox_nav = _inbox_nav_for_status(request, str(report.status).upper())
    context = {
        "report": report,
        "attachments": merged_files,
        "role": role,
        "inbox_url": inbox_nav["url"],
        "inbox_label": inbox_nav["label"],
        "can_ceo_approve": can_ceo_approve,
        "ceo_approve_url": "/app/ceo/approvals/approve/",
        "ceo_approval_request_id": approval_request.id if approval_request else None,
        "return_url": request.get_full_path(),
    }
    return render(request, "app/hq/field_report_detail.html", context)


@login_required
def hq_approval_detail(request, approval_id: int):
    require_role(request.user, [Role.HQ, Role.CEO])
    ceo_redirect = _maybe_redirect_ceo_to_ceo_path(request)
    if ceo_redirect is not None:
        return ceo_redirect
    approval = get_object_or_404(
        ApprovalRequest.objects.select_related("submitted_by", "approved_by"),
        id=approval_id,
    )
    object_type = (approval.object_type or "").upper()
    object_detail_url = _resolve_object_detail_url(
        object_type,
        approval.object_id,
        _app_prefix_for_request(request),
    )
    attachments = _get_attachments_for_approval(approval)
    context = {
        "approval": approval,
        "object_detail_url": object_detail_url,
        "attachments": attachments,
        "attachment_object_label": _approval_object_label_ko(object_type),
        "attachment_help_text": "승인 상세에서는 첨부를 조회할 수 있습니다.",
        "role": get_user_role(request.user),
        "inbox_url": _inbox_url_for_request(request),
    }
    return render(request, "app/hq/approval_detail.html", context)


@login_required
def field_app_view(request):
    return render(request, "app/field_home.html", {"role": get_user_role(request.user)})


def admin_change_url(obj):
    if obj is None:
        return ""
    opts = obj._meta
    return f"/admin/{opts.app_label}/{opts.model_name}/{obj.pk}/change/"


def _approval_object_label_ko(object_type: str) -> str:
    mapping = {
        "DAILY_PROGRESS": "진행률",
        "DAILY_REPORT": "일일보고",
        "FIELD_REPORT": "기존 현장보고",
        "COST_ACTUAL": "원가",
        "TIMESHEET": "출역부",
        "CONTRACT_CHANGE": "계약 변경",
        "PLAN_CHANGE_REQUEST": "계획 변경",
        "APPROVAL_PACKAGE": "승인 패키지",
        "ADJUSTMENT": "정정",
        "CLOSING_PERIOD": "월 마감",
    }
    return mapping.get((object_type or "").upper(), "승인요청")


def _resolve_object_project_name(object_type: str, object_id: int):
    if not object_type or not object_id:
        return "-"

    normalized = (object_type or "").upper()
    if normalized == "DAILY_PROGRESS":
        obj = DailyProgress.objects.select_related("project").filter(id=object_id).first()
        return obj.project.name if obj and obj.project_id else "-"
    if normalized == "DAILY_REPORT":
        obj = DailyReport.objects.select_related("project").filter(id=object_id).first()
        return obj.project.name if obj and obj.project_id else "-"
    if normalized == "FIELD_REPORT":
        obj = FieldReport.objects.select_related("project").filter(id=object_id).first()
        return obj.project.name if obj and obj.project_id else "-"
    if normalized == "COST_ACTUAL":
        obj = CostActual.objects.select_related("project").filter(id=object_id).first()
        return obj.project.name if obj and obj.project_id else "-"
    if normalized == "PLAN_CHANGE_REQUEST":
        obj = (
            PlanChangeRequest.objects.select_related("project")
            .filter(id=object_id)
            .first()
        )
        return obj.project.name if obj and obj.project_id else "-"
    if normalized == "CONTRACT_CHANGE":
        obj = ContractChange.objects.select_related("project").filter(id=object_id).first()
        return obj.project.name if obj and obj.project_id else "-"
    return "-"


def _get_attachments_for_approval(approval: ApprovalRequest):
    object_type = (approval.object_type or "").upper()
    object_id = approval.object_id
    if object_type == "APPROVAL_REQUEST" and object_id:
        nested = ApprovalRequest.objects.filter(id=object_id).first()
        if nested:
            object_type = (nested.object_type or "").upper()
            object_id = nested.object_id
    return _get_attachments_for_object(object_type, object_id)


def _get_attachments_for_object(object_type: str, object_id: int):
    object_type = (object_type or "").upper()
    if not object_type or not object_id:
        return []
    evidences = (
        Evidence.objects.filter(object_type=object_type, object_id=object_id)
        .prefetch_related("files")
        .order_by("-created_at")
    )
    files = []
    seen_ids = set()
    for evidence in evidences:
        for evidence_file in evidence.files.all().order_by("-created_at"):
            if evidence_file.id in seen_ids:
                continue
            seen_ids.add(evidence_file.id)
            files.append(evidence_file)
    return files


def _app_prefix_for_request(request) -> str:
    path = request.path or ""
    if path.startswith("/app/ceo/"):
        return "/app/ceo"
    role = None
    if getattr(request, "user", None) is not None and request.user.is_authenticated:
        role = get_user_role(request.user)
    if role in (Role.CEO, "ceo", "CEO"):
        return "/app/ceo"
    return "/app/hq"


def _inbox_url_for_request(request) -> str:
    if _app_prefix_for_request(request) == "/app/ceo":
        return "/app/ceo/inbox/"
    return "/app/hq/inbox/"


def _inbox_nav_for_status(request, object_status: str):
    base_url = _inbox_url_for_request(request)
    is_ceo = _app_prefix_for_request(request) == "/app/ceo"
    is_approved = (object_status or "").upper() == "APPROVED"
    if is_ceo and is_approved:
        return {"url": "/app/ceo/inbox/?scope=approved", "label": "승인완료 목록으로"}
    return {"url": base_url, "label": "승인함으로"}


def _resolve_object_detail_url(object_type: str, object_id: int, app_prefix: str) -> str:
    if not object_type or not object_id:
        return ""
    mapping = {
        "DAILY_REPORT": f"{app_prefix}/reports/{object_id}/",
        "DAILY_PROGRESS": f"{app_prefix}/progress/{object_id}/",
        "FIELD_REPORT": f"{app_prefix}/field-reports/{object_id}/",
        "COST_ACTUAL": f"{app_prefix}/costs/{object_id}/",
        "PLAN_CHANGE_REQUEST": f"{app_prefix}/plan-change-requests/{object_id}/",
        "CONTRACT_CHANGE": f"{app_prefix}/contract-changes/{object_id}/",
        "TIMESHEET": f"{app_prefix}/labor/timesheets/{object_id}/",
        "PAYROLLALLOCATIONBATCH": f"{app_prefix}/labor/payroll/{object_id}/",
        "PAYROLL_BATCH": f"{app_prefix}/labor/payroll/{object_id}/",
        "APPROVAL_PACKAGE": f"{app_prefix}/approval-packages/{object_id}/",
        "CLOSING_PERIOD": f"{app_prefix}/closing/{object_id}/",
        "ADJUSTMENT": f"{app_prefix}/adjustments/{object_id}/",
    }
    return mapping.get(object_type, "")


def _resolve_evidence_project(evidence: Evidence):
    object_type = (evidence.object_type or "").upper()
    object_id = evidence.object_id
    if not object_id:
        return None
    if object_type == "PROJECT":
        return Project.objects.filter(id=object_id).first()
    if object_type == "DAILY_PROGRESS":
        return (
            DailyProgress.objects.filter(id=object_id)
            .select_related("project")
            .values_list("project", flat=True)
            .first()
        )
    if object_type == "DAILY_REPORT":
        return (
            DailyReport.objects.filter(id=object_id)
            .select_related("project")
            .values_list("project", flat=True)
            .first()
        )
    if object_type == "FIELD_REPORT":
        return (
            FieldReport.objects.filter(id=object_id)
            .select_related("project")
            .values_list("project", flat=True)
            .first()
        )
    if object_type == "COST_ACTUAL":
        return (
            CostActual.objects.filter(id=object_id)
            .select_related("project")
            .values_list("project", flat=True)
            .first()
        )
    return None


@login_required
def evidence_file_open(request, file_id: int):
    evidence_file = get_object_or_404(
        EvidenceFile.objects.select_related("evidence"),
        id=file_id,
    )
    evidence = evidence_file.evidence
    project_id = _resolve_evidence_project(evidence)
    if project_id:
        require_project_access(request.user, project_id)
    elif get_user_role(request.user) not in (Role.HQ, Role.CEO):
        raise PermissionDenied("Access denied.")

    try:
        return FileResponse(
            evidence_file.file.open("rb"),
            as_attachment=False,
            filename=evidence_file.original_name or evidence_file.file.name,
        )
    except FileNotFoundError as exc:
        raise Http404("File not found.") from exc


class ApprovalRequestListView(ListAPIView):
    serializer_class = ApprovalRequestSerializer
    permission_classes = [IsAuthenticated]

    def get_queryset(self):
        queryset = ApprovalRequest.objects.all().order_by("-created_at")
        object_type = self.request.query_params.get("object_type")
        status_value = self.request.query_params.get("status")
        if object_type:
            queryset = queryset.filter(object_type=object_type)
        if status_value:
            queryset = queryset.filter(status=status_value)
        return queryset


class ApprovalSubmitView(APIView):
    permission_classes = [IsAuthenticated]

    def post(self, request):
        serializer = ApprovalSubmitSerializer(data=request.data, context={"request": request})
        serializer.is_valid(raise_exception=True)
        approval = serializer.save()
        return Response(
            ApprovalRequestSerializer(approval).data,
            status=status.HTTP_201_CREATED,
        )


class ApprovalApproveView(APIView):
    permission_classes = [IsAuthenticated]
    # HQ/CEO approval gating will be enforced by RBAC later.

    def post(self, request, pk):
        approval = get_object_or_404(ApprovalRequest, pk=pk)
        serializer = ApprovalDecisionSerializer(data=request.data, context={"request": request})
        serializer.is_valid(raise_exception=True)
        approval = serializer.approve(approval)
        return Response(ApprovalRequestSerializer(approval).data, status=status.HTTP_200_OK)


class ApprovalRejectView(APIView):
    permission_classes = [IsAuthenticated]
    # HQ/CEO approval gating will be enforced by RBAC later.

    def post(self, request, pk):
        approval = get_object_or_404(ApprovalRequest, pk=pk)
        serializer = ApprovalDecisionSerializer(data=request.data, context={"request": request})
        serializer.is_valid(raise_exception=True)
        approval = serializer.reject(approval)
        return Response(ApprovalRequestSerializer(approval).data, status=status.HTTP_200_OK)

