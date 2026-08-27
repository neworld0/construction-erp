"""Shared current-operation visibility policy for RiskFinding dashboards."""

from django.db.models import Q

from apps.risk.models import RiskFinding, RiskFindingStatus


DEMO_SEED_RISK_FILTER = (
    Q(rule__key__icontains="demo")
    | Q(rule__key__icontains="seed")
    | Q(title__icontains="demo")
    | Q(title__icontains="seed")
    | Q(details__icontains="demo")
    | Q(details__icontains="seed")
)


def is_demo_seed_risk(finding):
    rule_key = str(getattr(getattr(finding, "rule", None), "key", "") or "").lower()
    text = " ".join((finding.title or "", finding.details or "")).lower()
    return any(token in rule_key or token in text for token in ("demo", "seed", "test", "데모"))


def classify_operational_dashboard_risk(finding):
    if finding.status != RiskFindingStatus.OPEN:
        return "CLOSED_OR_RESOLVED_RISK"
    if is_demo_seed_risk(finding):
        return "DEMO_SEED_RISK"
    if finding.project_id is None:
        return "ORPHAN_PROJECT_RISK" if (finding.object_type or "").upper() == "PROJECT" else "PROJECTLESS_NON_SYSTEM_RISK"
    if not finding.project.is_active:
        return "INACTIVE_PROJECT_RISK"
    if (finding.object_type or "").upper() == "PROJECT" and finding.object_id != finding.project_id:
        return "ORPHAN_PROJECT_RISK"
    return "VALID_ACTIVE_PROJECT_RISK"


def get_operational_dashboard_risk_queryset():
    """Open, active-project risks only; preserve all excluded rows in RiskFinding."""
    return (
        RiskFinding.objects.filter(
            status=RiskFindingStatus.OPEN,
            project__is_active=True,
        )
        .exclude(DEMO_SEED_RISK_FILTER)
        .select_related("project", "rule")
    )
