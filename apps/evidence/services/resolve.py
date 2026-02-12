from datetime import date

from django.core.exceptions import ValidationError

from apps.contracts.models import ContractChange
from apps.evidence.models import Evidence, EvidenceFile
from apps.projects.models import Project
from apps.schedule.models import PlanChangeRequest
from apps.cost.models import CostActual
from apps.field.models import DailyReport
from apps.reports.models import FieldReport
from apps.schedule.models import DailyProgress


def resolve_project_for_evidence(evidence):
    if evidence is None:
        return None
    if evidence.object_type == "CONTRACT_CHANGE":
        change = ContractChange.objects.filter(id=evidence.object_id).first()
        return change.project if change else None
    if evidence.object_type == "PLAN_CHANGE_REQUEST":
        plan_change = PlanChangeRequest.objects.filter(id=evidence.object_id).first()
        return plan_change.project if plan_change else None
    if evidence.object_type == "PROJECT":
        return Project.objects.filter(id=evidence.object_id).first()
    if evidence.object_type == "COST_ACTUAL":
        cost_actual = CostActual.objects.filter(id=evidence.object_id).first()
        return cost_actual.project if cost_actual else None
    # TODO: extend for other object types.
    return None


def resolve_target_date_for_evidence(evidence):
    if evidence is None:
        return None
    if evidence.object_type == "DAILY_PROGRESS":
        obj = DailyProgress.objects.filter(id=evidence.object_id).only("report_date").first()
        return getattr(obj, "report_date", None)
    if evidence.object_type == "DAILY_REPORT":
        obj = DailyReport.objects.filter(id=evidence.object_id).only("report_date").first()
        return getattr(obj, "report_date", None)
    if evidence.object_type == "FIELD_REPORT":
        obj = FieldReport.objects.filter(id=evidence.object_id).only("report_date").first()
        return getattr(obj, "report_date", None)
    if evidence.object_type == "COST_ACTUAL":
        obj = CostActual.objects.filter(id=evidence.object_id).only("report_date").first()
        return getattr(obj, "report_date", None)
    return None


def is_project_or_month_locked(*, project, target_date: date | None) -> bool:
    if project is not None and getattr(getattr(project, "close", None), "status", None) == "CLOSED":
        return True
    if target_date is not None:
        from apps.closing.services import is_month_closed

        return is_month_closed(target_date)
    return False


def resolve_project_for_evidence_file(file_id):
    evidence_file = EvidenceFile.objects.select_related("evidence").filter(id=file_id).first()
    if evidence_file is None:
        raise ValidationError("EvidenceFile not found.")

    evidence = evidence_file.evidence
    project = resolve_project_for_evidence(evidence)
    if project is None:
        raise ValidationError("Evidence project could not be resolved.")

    return project, evidence.object_type, evidence.object_id, evidence, evidence_file
