"""Project and as-of-date reconciliation used before completion billing."""

from collections import defaultdict
from decimal import Decimal

from django.db.models import Sum

from apps.cost.models import CostActual, CostActualStatus
from apps.inventory.models import InventoryLedger, IssueStatus, IssueToWork, WarehouseType
from apps.labor.models import Timesheet, TimesheetStatus
from apps.schedule.models import DailyProgress, SchedulePlan


def _decimal(value):
    return Decimal(value or 0)


def _approved_progress(project, as_of_date):
    plan = SchedulePlan.objects.filter(project=project, is_active=True).prefetch_related("tasks").first()
    if not plan:
        return Decimal("0"), [], ["활성 공정 기준선이 없습니다."]
    tasks = list(plan.tasks.filter(is_active=True).order_by("sort_order", "id"))
    if not tasks:
        return Decimal("0"), [], ["활성 공정이 없습니다."]
    entries = DailyProgress.objects.filter(project=project, plan=plan, task__in=tasks, status="approved", report_date__lte=as_of_date).order_by("task_id", "-report_date", "-id")
    latest_by_task = {}
    for entry in entries:
        latest_by_task.setdefault(entry.task_id, entry)
    weight_total = sum((_decimal(task.weight_percent) for task in tasks), Decimal("0"))
    weighted_sum = Decimal("0")
    rows = []
    for task in tasks:
        entry = latest_by_task.get(task.id)
        progress = _decimal(entry.progress_percent if entry else 0)
        weight = _decimal(task.weight_percent)
        weighted_sum += weight * progress
        rows.append({"task": task.name, "weight": weight, "progress": progress, "report_date": entry.report_date if entry else None})
    return (weighted_sum / weight_total if weight_total else Decimal("0")).quantize(Decimal("0.001")), rows, []


def build_project_reconciliation(*, project, as_of_date, require_completion=False):
    """Build an auditable, read-only project reconciliation package."""
    progress_percent, progress_rows, progress_issues = _approved_progress(project, as_of_date)
    blocking_issues = list(progress_issues)
    if require_completion and progress_percent != Decimal("100"):
        blocking_issues.append(f"준공 기준 승인 진행률이 100%가 아닙니다. (현재 {progress_percent}%)")

    timesheets = Timesheet.objects.filter(project=project, work_date__lte=as_of_date).prefetch_related("lines")
    approved_timesheets = timesheets.filter(status=TimesheetStatus.APPROVED)
    labor_units = sum((_decimal(line.headcount) for sheet in approved_timesheets for line in sheet.lines.all()), Decimal("0"))
    labor_amount = sum((_decimal(line.amount) for sheet in approved_timesheets for line in sheet.lines.all()), Decimal("0"))
    unresolved_timesheets = list(timesheets.exclude(status=TimesheetStatus.APPROVED))
    if unresolved_timesheets:
        blocking_issues.append(f"미승인 또는 반려 출역부 {len(unresolved_timesheets)}건이 있습니다.")

    costs = CostActual.objects.filter(project=project, report_date__lte=as_of_date)
    approved_costs = costs.filter(status__in=(CostActualStatus.APPROVED, CostActualStatus.CLOSED))
    cost_amount = _decimal(approved_costs.aggregate(total=Sum("total_amount"))["total"])
    unresolved_costs = list(costs.exclude(status__in=(CostActualStatus.APPROVED, CostActualStatus.CLOSED)))
    if unresolved_costs:
        blocking_issues.append(f"미승인 또는 반려 원가 {len(unresolved_costs)}건이 있습니다.")

    issues = IssueToWork.objects.filter(project=project, issue_date__lte=as_of_date).prefetch_related("lines")
    approved_issues = issues.filter(status=IssueStatus.APPROVED)
    material_amount = sum((_decimal(line.amount) for issue in approved_issues for line in issue.lines.all()), Decimal("0"))
    unresolved_issues = list(issues.exclude(status=IssueStatus.APPROVED))
    if unresolved_issues:
        blocking_issues.append(f"미승인 또는 반려 자재 투입 {len(unresolved_issues)}건이 있습니다.")

    stock_balances = defaultdict(lambda: {"item": "", "uom": "", "qty": Decimal("0")})
    ledgers = InventoryLedger.objects.filter(warehouse__warehouse_type=WarehouseType.SITE, warehouse__project=project, tx_date__lte=as_of_date).select_related("item", "uom")
    for ledger in ledgers:
        row = stock_balances[(ledger.item_id, ledger.uom_id)]
        row["item"], row["uom"] = ledger.item.name, ledger.uom.code
        row["qty"] += _decimal(ledger.qty_delta)
    stock_rows = sorted((row for row in stock_balances.values() if row["qty"] != 0), key=lambda row: row["item"])

    return {
        "project": project, "as_of_date": as_of_date, "progress_percent": progress_percent,
        "progress_rows": progress_rows, "stock_rows": stock_rows,
        "summary_rows": [
            {"name": "승인 진행률", "value": f"{progress_percent}%", "detail": f"공정 {len(progress_rows)}개", "url": "/app/hq/inbox/?scope=approved&kind=progress"},
            {"name": "승인 출역", "value": f"{labor_units} 공수", "detail": f"노무비 {labor_amount:,.0f}원", "url": "/app/hq/labor/timesheets/?status=APPROVED"},
            {"name": "승인 원가", "value": f"{cost_amount:,.0f}원", "detail": "자재 투입 원가를 포함한 원가 실적", "url": "/app/hq/inbox/?scope=approved&kind=cost"},
            {"name": "승인 자재 투입", "value": f"{material_amount:,.0f}원", "detail": "승인 원가와 중복 합산하지 않음", "url": f"/app/hq/inbox/?scope=approved&kind=material&project_id={project.id}&as_of_date={as_of_date.isoformat()}"},
            {"name": "현장창고 기준일 재고", "value": f"{len(stock_rows)} 품목", "detail": f"재고 원장 {ledgers.count()}건 기준", "url": "/app/hq/master/warehouses/?show_sites=1"},
        ],
        "unresolved": {"timesheets": unresolved_timesheets, "costs": unresolved_costs, "issues": unresolved_issues},
        "blocking_issues": blocking_issues, "ready": not blocking_issues,
    }
