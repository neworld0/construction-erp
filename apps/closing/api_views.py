from django.core.exceptions import ValidationError
from django.http import JsonResponse
from rest_framework.permissions import IsAuthenticated
from rest_framework.views import APIView

from apps.core.rbac.permissions import require_role

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
        period = get_closing_period(year_int, month_int)
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
            period = close_month(year_int, month_int, request.user, note=note)
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
