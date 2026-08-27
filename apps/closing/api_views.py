from django.core.exceptions import ValidationError
from django.http import JsonResponse
from rest_framework.permissions import IsAuthenticated
from rest_framework.views import APIView

from apps.core.rbac.permissions import (
    get_current_legal_entity,
    require_legal_entity_access,
    require_role,
)
from apps.core.rbac.models import LegalEntity

from .services import close_month, get_closing_period


class ClosingMonthStatusView(APIView):
    permission_classes = [IsAuthenticated]

    def get(self, request):
        require_role(request.user, ["hq", "ceo"], request=request)
        year = request.GET.get("year")
        month = request.GET.get("month")
        if not (year and month and str(year).isdigit() and str(month).isdigit()):
            return JsonResponse({"detail": "year and month are required."}, status=400)
        year_int = int(year)
        month_int = int(month)
        legal_entity = _resolve_legal_entity(request)
        period = get_closing_period(year_int, month_int, legal_entity=legal_entity)
        if not period:
            return JsonResponse(
                {
                    "year": year_int,
                    "month": month_int,
                    "status": "OPEN",
                    "closed_at": None,
                    "closed_by": None,
                },
                status=200,
            )
        return JsonResponse(
            {
                "year": period.year,
                "month": period.month,
                "status": period.status,
                "closed_at": period.closed_at.isoformat() if period.closed_at else None,
                "closed_by": period.closed_by.username
                if period.closed_by
                else None,
            },
            status=200,
        )


class ClosingMonthCloseView(APIView):
    permission_classes = [IsAuthenticated]

    def post(self, request):
        require_role(request.user, ["hq", "ceo"], request=request)
        year = request.data.get("year")
        month = request.data.get("month")
        note = request.data.get("note")
        if not (year and month):
            return JsonResponse({"detail": "year and month are required."}, status=400)
        try:
            year_int = int(year)
            month_int = int(month)
            legal_entity = _resolve_legal_entity(request)
            period = close_month(year_int, month_int, request.user, legal_entity=legal_entity, note=note)
        except (ValueError, ValidationError) as exc:
            return JsonResponse({"detail": str(exc)}, status=400)
        return JsonResponse(
            {
                "year": period.year,
                "month": period.month,
                "status": period.status,
                "closed_at": period.closed_at.isoformat() if period.closed_at else None,
                "closed_by": period.closed_by.username if period.closed_by else None,
            },
            status=200,
        )


def _resolve_legal_entity(request):
    raw_entity_id = request.data.get("legal_entity_id") if request.method == "POST" else request.GET.get("legal_entity_id")
    if raw_entity_id not in (None, ""):
        legal_entity = LegalEntity.objects.filter(id=raw_entity_id, is_active=True).first()
        if legal_entity is None:
            raise ValidationError("법인을 확인해 주세요.")
        require_legal_entity_access(request.user, legal_entity, request=request)
        return legal_entity
    legal_entity = get_current_legal_entity(request)
    if legal_entity is None:
        raise ValidationError("선택 가능한 법인이 없습니다.")
    return legal_entity
