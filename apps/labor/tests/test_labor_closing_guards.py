from datetime import date
from decimal import Decimal

import pytest
from django.contrib.auth import get_user_model
from django.core.exceptions import PermissionDenied

from apps.closing.services import close_month
from apps.core.rbac.models import Role, UserProfile
from apps.labor.models import (
    LaborRole,
    LaborWorkLedger,
    PayrollAllocationStatus,
    WorkerMaster,
)
from apps.labor.services import (
    create_labor_work_ledger,
    create_payroll_batch,
    submit_payroll_batch,
    update_labor_reporting_project,
    update_labor_work_ledger,
    update_payroll_batch,
)
from apps.projects.models import Project


def _hq_user(username="labor-guard-hq"):
    user = get_user_model().objects.create_user(username=username, password="pass")
    UserProfile.objects.create(user=user, role=Role.HQ)
    return user


def _project(code="PRJ-LAB-GUARD-001"):
    return Project.objects.create(code=code, name=code)


def _worker(name="Guard Worker", rrn="900101-1234567"):
    worker = WorkerMaster(name=name, active=True)
    worker.set_rrn(rrn)
    worker.save()
    return worker


def _role(code="ROLE-GUARD"):
    return LaborRole.objects.create(code=code, name=code, is_active=True)


def _ledger_payload(project, worker, role, work_date=date(2026, 5, 10), unit="1.0"):
    return {
        "worker": worker,
        "actual_project": project,
        "report_project": project,
        "labor_role": role,
        "work_date": work_date,
        "work_unit": unit,
        "work_hours": "8",
        "unit_wage": 100000,
    }


@pytest.mark.django_db
def test_labor_work_ledger_create_blocked_in_closed_month():
    actor = _hq_user("labor-create-closed")
    project = _project("PRJ-LAB-GUARD-001")
    worker = _worker()
    role = _role()
    close_month(2026, 5, actor)

    with pytest.raises(PermissionDenied):
        create_labor_work_ledger(_ledger_payload(project, worker, role), actor=actor)

    assert LaborWorkLedger.objects.count() == 0


@pytest.mark.django_db
def test_labor_work_ledger_update_blocked_in_closed_month():
    actor = _hq_user("labor-update-closed")
    project = _project("PRJ-LAB-GUARD-002")
    worker = _worker(name="Update Worker", rrn="900102-1234567")
    role = _role("ROLE-GUARD-UPDATE")
    ledger = create_labor_work_ledger(_ledger_payload(project, worker, role), actor=actor)
    close_month(2026, 5, actor)

    with pytest.raises(PermissionDenied):
        update_labor_work_ledger(
            ledger,
            {**_ledger_payload(project, worker, role), "work_unit": "2.0"},
            actor=actor,
        )

    ledger.refresh_from_db()
    assert ledger.work_unit == Decimal("1.0")


@pytest.mark.django_db
def test_reporting_project_mapping_blocked_in_closed_month():
    actor = _hq_user("labor-reporting-closed")
    actual_project = _project("PRJ-LAB-GUARD-003")
    report_project = _project("PRJ-LAB-GUARD-004")
    worker = _worker(name="Reporting Worker", rrn="900103-1234567")
    role = _role("ROLE-GUARD-REPORT")
    ledger = create_labor_work_ledger(
        _ledger_payload(actual_project, worker, role),
        actor=actor,
    )
    close_month(2026, 5, actor)

    with pytest.raises(PermissionDenied):
        update_labor_reporting_project([ledger.id], report_project, "closed month test", actor)

    ledger.refresh_from_db()
    assert ledger.report_project == actual_project


@pytest.mark.django_db
def test_payroll_allocation_update_and_submit_blocked_in_closed_period():
    actor = _hq_user("payroll-closed")
    batch = create_payroll_batch(year=2026, month=5, total_amount=1000, actor=actor)
    close_month(2026, 5, actor)

    with pytest.raises(PermissionDenied):
        update_payroll_batch(batch, {"total_amount": 2000}, actor=actor)
    with pytest.raises(PermissionDenied):
        submit_payroll_batch(batch, actor=actor)

    batch.refresh_from_db()
    assert batch.status == PayrollAllocationStatus.DRAFT
    assert batch.total_amount == 1000
