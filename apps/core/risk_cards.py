from __future__ import annotations

from dataclasses import dataclass
from typing import Iterable

from django.utils import timezone

from apps.risk.models import RiskFinding, RiskSeverity


SEVERITY_ORDER = {
    "CRITICAL": 0,
    "HIGH": 1,
    "MED": 2,
    "LOW": 3,
}

CATEGORY_LABELS = {
    "EVIDENCE": "증빙",
    "COST": "원가",
    "PROGRESS": "진행",
    "INVENTORY": "재고",
    "LABOR": "인력",
    "APPROVAL": "승인",
    "CLOSING": "마감",
    "CHANGE": "변경",
    "DATA": "데이터",
}

REASON_PREFIX_MAP = {
    "EVIDENCE": "EVIDENCE",
    "COST": "COST",
    "PROGRESS": "PROGRESS",
    "INVENTORY": "INVENTORY",
    "LABOR": "LABOR",
    "APPROVAL": "APPROVAL",
    "CLOSING": "CLOSING",
    "CHANGE": "CHANGE",
    "DATA": "DATA",
}

OBJECT_TYPE_MAP = {
    "evidence": "EVIDENCE",
    "file": "EVIDENCE",
    "upload": "EVIDENCE",
    "costactual": "COST",
    "dailyreportline": "COST",
    "budgetitem": "COST",
    "progressentry": "PROGRESS",
    "wbsprogress": "PROGRESS",
    "inventoryledger": "INVENTORY",
    "stock": "INVENTORY",
    "transfer": "INVENTORY",
    "issuetowork": "INVENTORY",
    "warehouse": "INVENTORY",
    "timesheet": "LABOR",
    "payrollallocation": "LABOR",
    "laborrole": "LABOR",
    "approvalrequest": "APPROVAL",
    "closingperiod": "CLOSING",
    "adjustment": "CLOSING",
    "changeorder": "CHANGE",
    "contract_change": "CHANGE",
    "planchangerequest": "CHANGE",
    "plan_change_request": "CHANGE",
    "wbschangerequest": "CHANGE",
    "wbs_change_request": "CHANGE",
}

KEYWORD_MAP = [
    (("증빙", "파일", "업로드", "evidence", "upload"), "EVIDENCE"),
    (("원가", "cbs", "금액", "cost"), "COST"),
    (("진행", "공정", "wbs", "progress"), "PROGRESS"),
    (("재고", "창고", "이동", "투입", "inventory", "transfer"), "INVENTORY"),
    (("출역", "급여", "직종", "labor", "timesheet"), "LABOR"),
    (("승인", "반려", "대기", "approval"), "APPROVAL"),
    (("마감", "정정", "close", "closing"), "CLOSING"),
    (("변경", "계약", "설계", "changeorder"), "CHANGE"),
]


@dataclass
class RiskCard:
    id: int
    category: str
    category_label: str
    severity: str
    severity_label: str
    title: str
    detected_at: timezone.datetime
    updated_at: timezone.datetime | None
    project_name: str | None
    project_id: int | None
    detail_url: str | None
    stale_24h: bool
    stale_48h: bool


def build_risk_cards(findings: Iterable[RiskFinding], limit: int = 5) -> dict:
    now = timezone.now()
    cards = []
    for finding in findings:
        detected_at = finding.created_at
        updated_at = finding.updated_at or detected_at
        reason_code = ""
        if finding.rule_id and finding.rule:
            reason_code = (finding.rule.key or "").upper()
        category = _resolve_category(reason_code, finding.object_type, finding.title, finding.details)
        severity = _resolve_severity(
            finding,
            category,
            detected_at,
            now,
        )
        title = finding.title or CATEGORY_LABELS.get(category, "리스크")
        detail_url = _resolve_detail_url(finding)
        age_hours = (now - detected_at).total_seconds() / 3600.0
        stale_48h = age_hours >= 48
        stale_24h = age_hours >= 24
        cards.append(
            RiskCard(
                id=finding.id,
                category=category,
                category_label=CATEGORY_LABELS.get(category, "데이터"),
                severity=severity,
                severity_label=_severity_label(severity),
                title=title,
                detected_at=detected_at,
                updated_at=updated_at,
                project_name=finding.project.name if finding.project_id else None,
                project_id=finding.project_id,
                detail_url=detail_url,
                stale_24h=stale_24h,
                stale_48h=stale_48h,
            )
        )

    cards.sort(key=_sort_key)
    summary = _build_summary(cards)
    return {"cards": cards[:limit], "summary": summary}


def _resolve_category(reason_code: str, object_type: str, title: str, details: str) -> str:
    if reason_code:
        for prefix, category in REASON_PREFIX_MAP.items():
            if reason_code.startswith(prefix):
                return category
    if object_type:
        mapped = OBJECT_TYPE_MAP.get(object_type.lower())
        if mapped:
            return mapped
    message = f"{title or ''} {details or ''}".lower()
    for keywords, category in KEYWORD_MAP:
        for keyword in keywords:
            if keyword.lower() in message:
                return category
    return "DATA"


def _resolve_severity(
    finding: RiskFinding,
    category: str,
    detected_at: timezone.datetime,
    now: timezone.datetime,
) -> str:
    severity = (finding.severity or "").lower()
    if severity == RiskSeverity.CRITICAL:
        return "CRITICAL"
    if severity == RiskSeverity.HIGH:
        base = "HIGH"
    elif severity == RiskSeverity.MEDIUM:
        base = "MED"
    elif severity == RiskSeverity.LOW:
        base = "LOW"
    else:
        base = "MED"

    age_hours = (now - detected_at).total_seconds() / 3600.0
    if category == "CLOSING":
        return "CRITICAL"
    if "마감" in (finding.title or "") or "마감" in (finding.details or ""):
        return "CRITICAL"
    if category in {"CLOSING", "CHANGE", "COST", "INVENTORY"} and age_hours >= 48:
        return "CRITICAL"
    if age_hours >= 24:
        return "HIGH" if base != "CRITICAL" else base
    if category in {"EVIDENCE", "APPROVAL"} and base in {"MED", "LOW"}:
        return "HIGH"
    return base


def _severity_label(severity: str) -> str:
    if severity == "CRITICAL":
        return "CRITICAL"
    if severity == "HIGH":
        return "HIGH"
    if severity == "MED":
        return "MED"
    return "LOW"


def _resolve_detail_url(finding: RiskFinding) -> str | None:
    object_type = (finding.object_type or "").lower()
    if object_type == "evidence":
        return f"/app/evidence/{finding.object_id}/edit/"
    if object_type == "adjustment":
        return f"/app/hq/adjustments/{finding.object_id}/"
    if object_type == "closingperiod":
        return f"/app/hq/closing/{finding.object_id}/"
    if object_type == "timesheet":
        return f"/app/hq/labor/timesheets/{finding.object_id}/"
    if object_type in {"payrollallocationbatch", "payroll_batch"}:
        return f"/app/hq/labor/payroll/{finding.object_id}/"
    if object_type in {"approvalpackage", "approval_package"} and finding.project_id:
        return f"/app/hq/projects/{finding.project_id}/approval-packages/{finding.object_id}/"
    if object_type in {"wbschangerequest", "wbs_change_request"}:
        return f"/app/ceo/wbs-change/requests/{finding.object_id}/"
    if object_type in {"contract_change"}:
        return f"/app/hq/contract-changes/{finding.object_id}/"
    if object_type in {"plan_change_request"}:
        return f"/app/hq/plan-change-requests/{finding.object_id}/"
    if object_type in {"cost_actual"} and finding.project_id:
        return f"/app/hq/projects/{finding.project_id}/"
    if object_type == "project":
        return f"/app/hq/projects/{finding.object_id}/"
    if finding.project_id:
        return f"/app/hq/projects/{finding.project_id}/"
    return None


def _sort_key(card: RiskCard) -> tuple:
    return (
        SEVERITY_ORDER.get(card.severity, 9),
        0 if card.stale_48h else 1,
        0 if card.stale_24h else 1,
        card.detected_at,
    )


def _build_summary(cards: list[RiskCard]) -> dict:
    summary = {"open_total": len(cards), "critical": 0, "high": 0}
    for card in cards:
        if card.severity == "CRITICAL":
            summary["critical"] += 1
        elif card.severity == "HIGH":
            summary["high"] += 1
    return summary
