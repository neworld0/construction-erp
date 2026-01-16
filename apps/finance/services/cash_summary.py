from decimal import Decimal

from django.db.models import Q, Sum

from apps.finance.models import CashEvent, CashEventStatus, CashEventType


def _sum_amount(queryset, status, event_type, date_from=None, date_to=None):
    filters = Q(status=status, event_type=event_type)
    if date_from:
        filters &= Q(event_date__gte=date_from)
    if date_to:
        filters &= Q(event_date__lte=date_to)
    total = queryset.filter(filters).aggregate(total=Sum("amount"))["total"]
    return total or Decimal("0")


def get_cash_summary(project_id, date_from=None, date_to=None):
    queryset = CashEvent.objects.filter(project_id=project_id)

    inflow_confirmed = _sum_amount(
        queryset, CashEventStatus.CONFIRMED, CashEventType.IN, date_from, date_to
    )
    outflow_confirmed = _sum_amount(
        queryset, CashEventStatus.CONFIRMED, CashEventType.OUT, date_from, date_to
    )
    inflow_planned = _sum_amount(
        queryset, CashEventStatus.PLANNED, CashEventType.IN, date_from, date_to
    )
    outflow_planned = _sum_amount(
        queryset, CashEventStatus.PLANNED, CashEventType.OUT, date_from, date_to
    )

    return {
        "inflow_confirmed": inflow_confirmed,
        "outflow_confirmed": outflow_confirmed,
        "net_confirmed": inflow_confirmed - outflow_confirmed,
        "inflow_planned": inflow_planned,
        "outflow_planned": outflow_planned,
        "net_planned": inflow_planned - outflow_planned,
    }
