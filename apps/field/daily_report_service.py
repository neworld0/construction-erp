"""Read-only, source-backed construction daily-report aggregation.

The report has no write path.  It makes the familiar field daily-report form
from approved/source evidence that already belongs to progress, labour, cost,
and inventory workflows.  That keeps approval, closing and audit ownership in
their original modules.
"""
from __future__ import annotations

from collections import Counter
from datetime import timedelta
from decimal import Decimal

from django.db.models import Sum

from apps.cost.models import CostActual, CostActualStatus
from apps.inventory.models import InventoryLedger, InventoryTxType, IssueStatus, IssueToWork
from apps.labor.models import Timesheet, TimesheetStatus
from apps.schedule.models import DailyProgress


ZERO = Decimal("0")

# CEO 공사일보는 현장 입력 자체가 아니라 경영 개입이 필요한 예외만 알린다.
# 제출 후 이틀이 지나도 승인·반려되지 않은 건을 장기 승인 대기로 본다.
CEO_APPROVAL_WAIT_DAYS = 2


def _status_is(status, *values):
    return str(status).upper() in {str(value).upper() for value in values}


def _is_approved_status(status):
    return _status_is(status, "APPROVED", "CLOSED")


def _sum(queryset, field):
    return queryset.aggregate(value=Sum(field)).get("value") or ZERO


def _status_rows(queryset, field="status"):
    counts = Counter(queryset.values_list(field, flat=True))
    return [{"status": key, "count": counts[key]} for key in sorted(counts)]


def _status_summary(*status_groups):
    pending = sum(
        row["count"]
        for group in status_groups
        for row in group
        if str(row["status"]).upper() not in {"APPROVED", "CLOSED"}
        and str(row["status"]).lower() not in {"approved", "closed"}
    )
    return {"state": "ATTENTION" if pending else "READY", "pending_count": pending}


def _ceo_attention_for_project(*, project, as_of_date):
    """Return CEO-actionable exceptions that existed by the selected date.

    Drafts are intentionally excluded. A rejected row stays visible until the
    source workflow is resubmitted; submitted rows become visible only after
    the approval waiting threshold. Material issues create a linked CostActual,
    so that generated cost row is excluded to avoid double counting.
    """
    wait_cutoff = as_of_date - timedelta(days=CEO_APPROVAL_WAIT_DAYS)
    progress = DailyProgress.objects.filter(project=project, created_at__date__lte=as_of_date)
    timesheets = Timesheet.objects.filter(project=project, created_at__date__lte=as_of_date)
    costs = CostActual.objects.filter(
        project=project,
        created_at__date__lte=as_of_date,
        inventory_issue_to_work__isnull=True,
    )
    issues = IssueToWork.objects.filter(project=project, created_at__date__lte=as_of_date)

    rejected_count = (
        progress.filter(status__iexact="rejected").count()
        + timesheets.filter(status__iexact="rejected").count()
        + costs.filter(status__iexact="rejected").count()
        + issues.filter(status__iexact="rejected").count()
    )
    overdue_submission_count = (
        progress.filter(status__iexact="submitted", created_at__date__lte=wait_cutoff).count()
        + timesheets.filter(status__iexact="submitted", submitted_at__date__lte=wait_cutoff).count()
        + costs.filter(status__iexact="submitted", updated_at__date__lte=wait_cutoff).count()
        + issues.filter(status__iexact="submitted", submitted_at__date__lte=wait_cutoff).count()
    )
    total = rejected_count + overdue_submission_count
    return {
        "total": total,
        "rejected_count": rejected_count,
        "overdue_submission_count": overdue_submission_count,
        "wait_days": CEO_APPROVAL_WAIT_DAYS,
    }


def _summary_for_period(*, project, start_date, end_date):
    """Return one consistent KPI set for a closed date interval."""
    progress = DailyProgress.objects.filter(project=project, report_date__range=(start_date, end_date))
    timesheets = Timesheet.objects.filter(project=project, work_date__range=(start_date, end_date))
    costs = CostActual.objects.filter(project=project, report_date__range=(start_date, end_date))
    issues = IssueToWork.objects.filter(project=project, issue_date__range=(start_date, end_date))
    ledger = InventoryLedger.objects.filter(warehouse__project=project, tx_date__range=(start_date, end_date))
    approved_labor = timesheets.filter(status=TimesheetStatus.APPROVED)
    approved_cost = costs.filter(status__in=[CostActualStatus.APPROVED, CostActualStatus.CLOSED])
    approved_issues = issues.filter(status=IssueStatus.APPROVED)
    progress_count = progress.count()
    return {
        "start_date": start_date,
        "end_date": end_date,
        "progress_count": progress_count,
        # This is an input average, not a contractual overall rate.
        "progress_average": _sum(progress, "progress_percent") / Decimal(progress_count) if progress_count else ZERO,
        "labor_headcount": _sum(approved_labor.values("lines__headcount"), "lines__headcount"),
        "labor_amount": _sum(approved_labor.values("lines__amount"), "lines__amount"),
        "cost_amount": _sum(approved_cost, "total_amount"),
        "issue_amount": _sum(approved_issues.values("lines__amount"), "lines__amount"),
        "receipt_qty": _sum(ledger.filter(tx_type=InventoryTxType.RECEIPT), "qty_delta"),
        "issue_qty": abs(_sum(ledger.filter(tx_type=InventoryTxType.ISSUE), "qty_delta")),
    }


def _today_rows(*, project, as_of_date):
    """Build detail rows and a concise work narrative for the selected date."""
    progress = DailyProgress.objects.filter(project=project, report_date=as_of_date).select_related(
        "task", "reporter", "approved_by"
    )
    timesheets = Timesheet.objects.filter(project=project, work_date=as_of_date).prefetch_related(
        "lines__labor_role"
    )
    costs = CostActual.objects.filter(project=project, report_date=as_of_date).prefetch_related("lines__cost_item")
    issues = IssueToWork.objects.filter(project=project, issue_date=as_of_date).prefetch_related("lines__item")
    ledger = InventoryLedger.objects.filter(warehouse__project=project, tx_date=as_of_date).select_related("item", "warehouse")

    progress_rows = [
        {
            "id": row.id, "task": row.task.name, "percent": row.progress_percent,
            "status": row.status, "note": row.note, "url": f"/app/field/progress/{row.id}/",
        }
        for row in progress.order_by("task__sort_order", "id")
    ]
    labor_rows, cost_rows, issue_rows, work_items = [], [], [], []
    for sheet in timesheets.order_by("id"):
        roles = ", ".join(sorted({line.labor_role.name for line in sheet.lines.all()}))
        row = {
            "id": sheet.id, "sheet_no": sheet.sheet_no, "status": sheet.status,
            "headcount": _sum(sheet.lines.all(), "headcount"), "amount": _sum(sheet.lines.all(), "amount"),
            "note": sheet.note, "roles": roles, "url": f"/app/field/labor/timesheets/{sheet.id}/",
        }
        labor_rows.append(row)
        work_items.append({"category": "출역", "title": f"{sheet.sheet_no} · {roles or '직종 미입력'}", "detail": sheet.note or "출역 입력", "status": sheet.status, "amount": row["amount"], "url": row["url"]})
    for cost in costs.order_by("id"):
        description = ", ".join(line.description or line.cost_item.name for line in cost.lines.all())
        row = {"id": cost.id, "status": cost.status, "amount": cost.total_amount, "description": description, "url": f"/app/field/cost/{cost.id}/"}
        cost_rows.append(row)
        work_items.append({"category": "원가", "title": description or f"원가 입력 #{cost.id}", "detail": f"원가 입력 #{cost.id}", "status": cost.status, "amount": cost.total_amount, "url": row["url"]})
    for issue in issues.order_by("id"):
        items = ", ".join(line.item.name for line in issue.lines.all())
        row = {
            "id": issue.id, "issue_no": issue.issue_no, "status": issue.status,
            "qty": _sum(issue.lines.all(), "qty"), "amount": _sum(issue.lines.all(), "amount"),
            "note": issue.note, "items": items, "url": f"/app/field/inventory/issues/{issue.id}/",
        }
        issue_rows.append(row)
        work_items.append({"category": "자재", "title": items or issue.issue_no, "detail": issue.note or f"자재투입 {issue.issue_no}", "status": issue.status, "amount": row["amount"], "url": row["url"]})
    for row in reversed(progress_rows):
        work_items.insert(0, {"category": "진행", "title": row["task"], "detail": row["note"] or "진행률 입력", "status": row["status"], "amount": None, "url": row["url"]})
    inventory_rows = [
        {"id": row.id, "type": row.tx_type, "item": row.item.name, "qty": row.qty_delta, "amount": row.amount or ZERO, "warehouse": row.warehouse.name}
        for row in ledger.order_by("id")
    ]
    return {
        "progress_rows": progress_rows, "labor_rows": labor_rows, "cost_rows": cost_rows,
        "issue_rows": issue_rows, "inventory_rows": inventory_rows, "work_items": work_items,
        "approved_work_items": [item for item in work_items if _is_approved_status(item["status"])],
        "progress_statuses": _status_rows(progress), "labor_statuses": _status_rows(timesheets),
        "cost_statuses": _status_rows(costs), "issue_statuses": _status_rows(issues),
    }


def build_project_daily_report(*, project, as_of_date):
    """Build one project report with yesterday, today and monthly totals."""
    yesterday = as_of_date - timedelta(days=1)
    month_start = as_of_date.replace(day=1)
    detail = _today_rows(project=project, as_of_date=as_of_date)
    today = _summary_for_period(project=project, start_date=as_of_date, end_date=as_of_date)
    report = {
        "project": project, "as_of_date": as_of_date, **detail,
        # ``summary`` stays today's KPI for existing callers.
        "summary": today,
        "periods": {
            "yesterday": _summary_for_period(project=project, start_date=yesterday, end_date=yesterday),
            "today": today,
            "month_to_date": _summary_for_period(project=project, start_date=month_start, end_date=as_of_date),
        },
    }
    report["report_status"] = _status_summary(detail["progress_statuses"], detail["labor_statuses"], detail["cost_statuses"], detail["issue_statuses"])
    report["ceo_attention"] = _ceo_attention_for_project(project=project, as_of_date=as_of_date)
    return report


def _organization_totals(reports, period_key):
    keys = ("progress_count", "labor_headcount", "labor_amount", "cost_amount", "issue_amount", "receipt_qty", "issue_qty")
    totals = {key: sum((row["periods"][period_key][key] for row in reports), ZERO) for key in keys}
    if reports:
        totals["start_date"] = reports[0]["periods"][period_key]["start_date"]
        totals["end_date"] = reports[0]["periods"][period_key]["end_date"]
    totals["project_count"] = len(reports)
    totals["attention_count"] = sum(row["report_status"]["pending_count"] for row in reports)
    return totals


def build_organization_daily_report(*, projects, as_of_date):
    reports = [build_project_daily_report(project=project, as_of_date=as_of_date) for project in projects]
    return {
        "as_of_date": as_of_date, "project_reports": reports,
        "totals": _organization_totals(reports, "today"),
        "period_totals": {
            "yesterday": _organization_totals(reports, "yesterday"),
            "today": _organization_totals(reports, "today"),
            "month_to_date": _organization_totals(reports, "month_to_date"),
        },
    }
