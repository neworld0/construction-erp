from __future__ import annotations

from urllib.parse import quote

from django.conf import settings
from django.http import JsonResponse
from django.shortcuts import redirect
from django.utils.deprecation import MiddlewareMixin
from django_otp.plugins.otp_static.models import StaticDevice
from django_otp.plugins.otp_totp.models import TOTPDevice

from apps.core.rbac.models import Role
from apps.core.rbac.permissions import get_user_role


class TwoFactorEnforceMiddleware(MiddlewareMixin):
    def process_request(self, request):
        user = getattr(request, "user", None)
        if user is None or not user.is_authenticated:
            return None

        role = get_user_role(user)
        if role not in (Role.CEO, Role.HQ, Role.FIELD):
            return None

        require_for_field = getattr(settings, "FIELD_2FA_REQUIRED", False)
        if role == Role.FIELD and not require_for_field:
            return None

        if request.path.startswith("/api/"):
            return None
        if request.path.startswith(("/login/", "/logout/", "/account/")):
            return None
        if request.path.startswith(("/healthz/", "/health")):
            return None
        if not request.path.startswith(("/app/", "/admin/")):
            return None
        if request.path.startswith(("/static/", "/media/")):
            return None

        if getattr(user, "is_verified", lambda: False)():
            return None

        has_device = (
            TOTPDevice.objects.filter(user=user, confirmed=True).exists()
            or StaticDevice.objects.filter(user=user).exists()
        )
        is_api = request.path.startswith("/api/") or request.headers.get(
            "Accept", ""
        ).startswith("application/json")

        if is_api:
            return JsonResponse(
                {"detail": "Two-factor authentication required."}, status=403
            )

        next_path = quote(request.get_full_path())
        if not has_device:
            return redirect(f"/account/two_factor/setup/?next={next_path}")
        return redirect(f"/login/?next={next_path}")
