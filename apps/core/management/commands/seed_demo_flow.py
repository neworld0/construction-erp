import os
from decimal import Decimal

from django.contrib.auth import get_user_model
from django.core.files.uploadedfile import SimpleUploadedFile
from django.core.management.base import BaseCommand
from django.utils import timezone

from apps.contracts.models import ContractChange, ContractChangeStatus
from apps.core.models import ApprovalRequest, ApprovalStatus
from apps.core.rbac.models import Role, UserProfile
from apps.cost.models import CostActual, CostActualLine, CostActualStatus, CostItem
from apps.evidence.models import Evidence, EvidenceFile
from apps.projects.models import Project
from apps.risk.models import RiskFinding, RiskFindingStatus, RiskRule
from apps.schedule.models import DailyProgress, SchedulePlan, ScheduleTask
from apps.field.models import DailyReport, DailyReportLine


class Command(BaseCommand):
    help = "Seed demo data for local demo flow."

    def handle(self, *args, **options):
        if os.getenv("DEMO_ENABLE", "").strip().lower() != "true":
            self.stdout.write("seed_demo_flow skipped (DEMO_ENABLE != true).")
            return

        ceo_username = os.getenv("SEED_CEO_USERNAME", "ceo")
        hq_username = os.getenv("SEED_HQ_USERNAME", "hq")
        field_username = os.getenv("SEED_FIELD_USERNAME", "field1")

        project_code = os.getenv("SEED_PROJECT_CODE", "PRJ-DEMO-001")
        project_name = os.getenv("SEED_PROJECT_NAME", "Demo Project")

        User = get_user_model()
        ceo_user = _get_or_create_user(User, ceo_username, Role.CEO)
        hq_user = _get_or_create_user(User, hq_username, Role.HQ)
        field_user = _get_or_create_user(User, field_username, Role.FIELD)

        project, project_created = Project.objects.get_or_create(
            code=project_code, defaults={"name": project_name}
        )

        items = _seed_cost_items()

        report_date = timezone.localdate()
        report, report_created = DailyReport.objects.get_or_create(
            project=project,
            report_date=report_date,
            reporter=field_user,
            defaults={"note": "Demo daily report", "status": "draft"},
        )
        if report_created and items:
            DailyReportLine.objects.get_or_create(
                report=report,
                cost_item=items[0],
                defaults={
                    "description": "Demo work",
                    "quantity": Decimal("1.000"),
                    "unit_price": Decimal("100.00"),
                },
            )

        created_cost_actuals = []
        if report and not CostActual.objects.filter(source_daily_report=report).exists():
            cost_actual = CostActual.objects.create(
                project=project,
                report_date=report.report_date,
                source_daily_report=report,
                status=CostActualStatus.SUBMITTED,
            )
            for line in report.lines.all():
                CostActualLine.objects.create(
                    cost_actual=cost_actual,
                    cost_item=line.cost_item,
                    description=line.description,
                    quantity=line.quantity,
                    unit_price=line.unit_price,
                )
            cost_actual.recalculate_total()
            created_cost_actuals.append(cost_actual)

        existing_count = CostActual.objects.filter(project=project).count()
        to_create = max(0, 3 - existing_count)
        for offset in range(to_create):
            cost_actual = CostActual.objects.create(
                project=project,
                report_date=report_date,
                status=CostActualStatus.DRAFT,
            )
            if items:
                CostActualLine.objects.create(
                    cost_actual=cost_actual,
                    cost_item=items[offset % len(items)],
                    description="Demo cost line",
                    quantity=Decimal("2.000"),
                    unit_price=Decimal("50.00"),
                )
            cost_actual.recalculate_total()
            created_cost_actuals.append(cost_actual)

        approval_target = CostActual.objects.filter(project=project).first()
        approval = None
        if approval_target:
            approval, _ = ApprovalRequest.objects.get_or_create(
                object_type="COST_ACTUAL",
                object_id=approval_target.id,
                defaults={
                    "status": ApprovalStatus.SUBMITTED,
                    "submitted_by": hq_user,
                    "submitted_at": timezone.now(),
                },
            )
            if approval.status == ApprovalStatus.DRAFT:
                approval.status = ApprovalStatus.SUBMITTED
                approval.submitted_by = hq_user
                approval.submitted_at = timezone.now()
                approval.save(
                    update_fields=["status", "submitted_by", "submitted_at"]
                )

        change = (
            ContractChange.objects.filter(project=project)
            .order_by("-created_at")
            .first()
        )
        if change is None:
            change = ContractChange.objects.create(
                project=project,
                change_type="design_change",
                reason="Demo change",
                contract_amount_delta=Decimal("500.00"),
                time_extension_days=3,
                status=ContractChangeStatus.SUBMITTED,
                submitted_by=hq_user,
                submitted_at=timezone.now(),
            )

        evidence = Evidence.objects.filter(
            object_type="CONTRACT_CHANGE", object_id=change.id
        ).first()
        if evidence is None:
            evidence = Evidence.objects.create(
                title="Demo Evidence",
                description="",
                object_type="CONTRACT_CHANGE",
                object_id=change.id,
                created_by=hq_user,
            )
        if not evidence.files.exists():
            file_obj = SimpleUploadedFile(
                "demo-evidence.txt", b"demo evidence", content_type="text/plain"
            )
            EvidenceFile.objects.create(
                evidence=evidence,
                file=file_obj,
                original_name="demo-evidence.txt",
                content_type="text/plain",
                size_bytes=file_obj.size,
                created_by=hq_user,
            )

        rule, _ = RiskRule.objects.get_or_create(
            key="DEMO_RISK",
            defaults={
                "name": "Demo Risk",
                "description": "",
                "severity": "high",
                "threshold_json": {"max_daily_delta": 5},
                "is_active": True,
            },
        )
        RiskFinding.objects.get_or_create(
            rule=rule,
            project=project,
            object_type="PROJECT",
            object_id=project.id,
            defaults={
                "score": Decimal("1.000"),
                "severity": "high",
                "title": "Demo risk finding",
                "details": "Demo risk",
                "status": RiskFindingStatus.OPEN,
            },
        )

        plan = SchedulePlan.objects.filter(project=project, is_active=True).first()
        if plan is None:
            plan = SchedulePlan.objects.create(
                project=project,
                version_no=1,
                name="Baseline",
                is_active=True,
                created_by=field_user,
            )
        task, _ = ScheduleTask.objects.get_or_create(
            plan=plan,
            name="Demo Task",
            defaults={"weight_percent": Decimal("100.000"), "sort_order": 1},
        )
        DailyProgress.objects.get_or_create(
            project=project,
            plan=plan,
            task=task,
            report_date=report_date,
            reporter=field_user,
            defaults={"progress_percent": Decimal("25.000")},
        )

        self.stdout.write(
            "seed_demo_flow done: "
            f"project={'created' if project_created else 'exists'} "
            f"(id={project.id}, admin=/admin/projects/project/{project.id}/)"
        )
        if report:
            self.stdout.write(
                f"daily_report id={report.id} admin=/admin/field/dailyreport/{report.id}/"
            )
        if approval:
            self.stdout.write(
                f"approval id={approval.id} admin=/admin/core/approvalrequest/{approval.id}/"
            )
        if change:
            self.stdout.write(
                f"contract_change id={change.id} admin=/admin/contracts/contractchange/{change.id}/"
            )
        if evidence:
            self.stdout.write(
                f"evidence id={evidence.id} admin=/admin/evidence/evidence/{evidence.id}/"
            )


def _get_or_create_user(user_model, username, role):
    user, created = user_model.objects.get_or_create(username=username)
    profile, _ = UserProfile.objects.get_or_create(user=user, defaults={"role": role})
    if profile.role != role:
        profile.role = role
        profile.save(update_fields=["role"])
    return user


def _seed_cost_items():
    items = [
        ("COST-DEMO-LAB", "노무비", "labor"),
        ("COST-DEMO-MAT", "자재비", "material"),
        ("COST-DEMO-EQP", "장비비", "equip"),
        ("COST-DEMO-SUB", "외주비", "subcon"),
        ("COST-DEMO-OTH", "기타경비", "other"),
    ]
    created = []
    for code, name, category in items:
        item, _ = CostItem.objects.get_or_create(
            code=code,
            defaults={
                "name": name,
                "category": category,
                "unit": "",
                "is_direct": True,
                "sort_order": 1,
                "is_active": True,
            },
        )
        created.append(item)
    return created
