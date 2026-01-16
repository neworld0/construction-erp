from datetime import timedelta
from decimal import Decimal

from django.db import transaction
from django.utils import timezone

from apps.contracts.models import ContractChange
from apps.cost.models import CostActual
from apps.evidence.services.policy import check_evidence_required
from apps.projects.models import Project
from apps.schedule.models import PlanChangeRequest

from ..models import RiskEvent, RiskFinding, RiskFindingStatus, RiskRule


def emit_event(event_type, object_type, object_id, payload, actor=None):
    with transaction.atomic():
        event = RiskEvent.objects.create(
            event_type=event_type,
            object_type=object_type,
            object_id=object_id,
            actor=actor,
            payload=payload or {},
        )
        evaluate_event(event)
    # AuditLog/CEO 차단 정책 연계 포인트
    return event


def evaluate_event(event):
    findings = []
    rules = RiskRule.objects.filter(is_active=True)
    for rule in rules:
        handler = _RULE_HANDLERS.get(rule.key)
        if handler is None:
            continue
        finding = handler(rule, event)
        if finding is not None:
            findings.append(finding)
    return findings


def _create_finding(rule, event, title, details, severity=None, score=Decimal("1.0")):
    project = _resolve_project(event)
    finding = RiskFinding.objects.create(
        rule=rule,
        event=event,
        project=project,
        object_type=event.object_type,
        object_id=event.object_id,
        score=score,
        severity=severity or rule.severity,
        title=title,
        details=details,
        status=RiskFindingStatus.OPEN,
    )
    return finding


def _resolve_project(event):
    if event.object_type == "PROJECT":
        return Project.objects.filter(id=event.object_id).first()
    if event.object_type == "PLAN_CHANGE_REQUEST":
        change = PlanChangeRequest.objects.filter(id=event.object_id).first()
        return change.project if change else None
    if event.object_type == "CONTRACT_CHANGE":
        change = ContractChange.objects.filter(id=event.object_id).first()
        return change.project if change else None
    if event.object_type == "COST_ACTUAL":
        actual = CostActual.objects.filter(id=event.object_id).first()
        return actual.project if actual else None
    return None


def _rule_progress_spike(rule, event):
    if event.event_type != "DAILY_PROGRESS":
        return None
    payload = event.payload or {}
    delta_percent = Decimal(str(payload.get("delta_percent", 0)))
    max_delta = Decimal(str(rule.threshold_json.get("max_daily_delta", 0)))
    if delta_percent > max_delta:
        return _create_finding(
            rule,
            event,
            "Progress spike detected",
            f"Delta {delta_percent} exceeds threshold {max_delta}.",
        )
    return None


def _rule_plan_change_frequency(rule, event):
    if event.event_type != "PLAN_APPROVED":
        return None
    threshold_days = int(rule.threshold_json.get("window_days", 30))
    max_changes = int(rule.threshold_json.get("max_changes", 0))
    since = timezone.now() - timedelta(days=threshold_days)
    count = (
        PlanChangeRequest.objects.filter(
            project=_resolve_project(event),
            status="approved",
            approved_at__gte=since,
        ).count()
    )
    if max_changes and count > max_changes:
        return _create_finding(
            rule,
            event,
            "Plan change frequency high",
            f"{count} changes in last {threshold_days} days exceeds {max_changes}.",
        )
    return None


def _rule_contract_change_impact(rule, event):
    if event.event_type != "CONTRACT_APPROVED":
        return None
    payload = event.payload or {}
    max_amount = Decimal(str(rule.threshold_json.get("max_amount_delta", 0)))
    max_days = int(rule.threshold_json.get("max_time_extension_days", 0))
    amount_delta = Decimal(str(payload.get("contract_amount_delta", 0)))
    extension_days = int(payload.get("time_extension_days", 0))
    if (max_amount and amount_delta > max_amount) or (max_days and extension_days > max_days):
        return _create_finding(
            rule,
            event,
            "Contract change impact high",
            f"Delta {amount_delta} / extension {extension_days} exceeds threshold.",
        )
    return None


def _rule_evidence_weak(rule, event):
    payload = event.payload or {}
    when_status = payload.get("when_status") or rule.threshold_json.get("when_status")
    if not when_status:
        return None
    ok, reason = check_evidence_required(event.object_type, event.object_id, when_status)
    if not ok:
        return _create_finding(
            rule,
            event,
            "Evidence policy violation",
            reason,
        )
    return None


def _rule_cost_category_shift(rule, event):
    if event.event_type != "COST_APPROVED":
        return None
    payload = event.payload or {}
    subcon_ratio = Decimal(str(payload.get("subcon_ratio", 0)))
    max_ratio = Decimal(str(rule.threshold_json.get("max_subcon_ratio", 0)))
    if max_ratio and subcon_ratio > max_ratio:
        return _create_finding(
            rule,
            event,
            "Cost category shift detected",
            f"SUBCON ratio {subcon_ratio} exceeds {max_ratio}.",
        )
    return None


_RULE_HANDLERS = {
    "PROGRESS_SPIKE": _rule_progress_spike,
    "PLAN_CHANGE_FREQUENCY": _rule_plan_change_frequency,
    "CONTRACT_CHANGE_IMPACT": _rule_contract_change_impact,
    "EVIDENCE_WEAK": _rule_evidence_weak,
    "COST_CATEGORY_SHIFT": _rule_cost_category_shift,
}
