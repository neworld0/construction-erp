import os
from django.db import connections
from django.db.utils import OperationalError
from django.utils import timezone

from django.conf import settings
from django.contrib.auth import authenticate, login, logout
from django.http import JsonResponse
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

from .models import ApprovalRequest
from .rbac.models import Role
from .rbac.permissions import get_user_role, require_role
from .serializers import (
    ApprovalDecisionSerializer,
    ApprovalRequestSerializer,
    ApprovalSubmitSerializer,
)
from apps.contracts.models import ContractChange, ContractChangeStatus
from apps.cost.models import CostActual, CostActualStatus
from apps.evidence.services.policy import check_evidence_required
from apps.field.models import DailyReport, DailyReportStatus
from apps.risk.models import RiskFinding, RiskFindingStatus
from apps.schedule.models import PlanChangeRequest, PlanChangeStatus


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

    pending_reports = list(
        DailyReport.objects.filter(status=DailyReportStatus.SUBMITTED)
        .select_related("project", "reporter")
        .order_by("-report_date")[:10]
    )
    pending_costs = list(
        CostActual.objects.filter(status=CostActualStatus.SUBMITTED)
        .select_related("project")
        .order_by("-report_date")[:10]
    )
    pending_plan_changes = list(
        PlanChangeRequest.objects.filter(status=PlanChangeStatus.SUBMITTED)
        .select_related("project", "base_plan")
        .order_by("-requested_at")[:10]
    )
    pending_contract_changes = list(
        ContractChange.objects.filter(status=ContractChangeStatus.SUBMITTED)
        .select_related("project")
        .order_by("-submitted_at")[:10]
    )

    risk_open = list(
        RiskFinding.objects.filter(status=RiskFindingStatus.OPEN)
        .select_related("project", "rule")
        .order_by("-created_at")[:10]
    )

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
        "risk_open": risk_open,
        "evidence_missing": evidence_missing,
        "admin_change_url": admin_change_url,
        "role": get_user_role(request.user),
    }
    return render(request, "app/hq_home.html", context)


@login_required
def field_app_view(request):
    return render(request, "app/field_home.html", {"role": get_user_role(request.user)})


def admin_change_url(obj):
    if obj is None:
        return ""
    opts = obj._meta
    return f"/admin/{opts.app_label}/{opts.model_name}/{obj.pk}/change/"


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
