import os
from datetime import timedelta
from decimal import Decimal

from django.contrib.auth import get_user_model
from django.core.files.uploadedfile import SimpleUploadedFile
from django.core.management import call_command
from django.core.management.base import BaseCommand
from django.utils import timezone

from apps.core.models import ApprovalRequest, ApprovalStatus
from apps.core.rbac.models import Role, UserProfile
from apps.cost.models import CostActual, CostActualLine, CostActualStatus, CostItem
from apps.projects.models import (
    BudgetCategory,
    BudgetItem,
    Project,
    ProjectContract,
    ProjectContractStatus,
    ProjectStatus,
    WBSItem,
)
from apps.reports.models import FieldReport, FieldReportStatus
from apps.schedule.models import DailyProgress, SchedulePlan, ScheduleTask


class Command(BaseCommand):
    help = "Seed demo data for 3 sites baseline metrics."

    def handle(self, *args, **options):
        if os.getenv("DEMO_ENABLE", "").strip().lower() != "true":
            self.stdout.write("seed_demo_3sites skipped (DEMO_ENABLE != true).")
            return

        call_command("seed_master_templates")

        User = get_user_model()
        _get_or_create_user(
            User,
            os.getenv("SEED_CEO_USERNAME", "ceo"),
            os.getenv("SEED_CEO_PASSWORD", "change-me"),
            Role.CEO,
        )
        hq_user = _get_or_create_user(
            User,
            os.getenv("SEED_HQ_USERNAME", "hq"),
            os.getenv("SEED_HQ_PASSWORD", "change-me"),
            Role.HQ,
        )
        field_user = _get_or_create_user(
            User,
            os.getenv("SEED_FIELD_USERNAME", "field1"),
            os.getenv("SEED_FIELD_PASSWORD", "change-me"),
            Role.FIELD,
        )

        cost_items = list(CostItem.objects.filter(is_active=True).order_by("sort_order"))
        if not cost_items:
            cost_items = _seed_cost_items()

        project_specs = [
            ("PRJ-BASE-001", "Demo Site A", ProjectStatus.APPROVED),
            ("PRJ-BASE-002", "Demo Site B", ProjectStatus.APPROVED),
            ("PRJ-BASE-003", "Demo Site C", ProjectStatus.APPROVED),
        ]

        contract_created = 0
        contract_skipped = 0
        budget_created = 0
        budget_skipped = 0
        for code, name, status in project_specs:
            project, _ = Project.objects.get_or_create(
                code=code,
                defaults={
                    "name": name,
                    "status": status,
                    "start_date": timezone.localdate(),
                    "end_date": timezone.localdate() + timedelta(days=365),
                },
            )
            if project.status != status:
                project.status = status
                project.save(update_fields=["status"])

            contract, created = ProjectContract.objects.get_or_create(
                project=project,
                defaults={
                    "contract_amount": Decimal("1000000.00"),
                    "contract_start_date": project.start_date,
                    "contract_end_date": project.end_date,
                    "start_date": project.start_date,
                    "end_date": project.end_date,
                    "status": "approved",
                },
            )
            if created:
                contract_created += 1
                contract_file = SimpleUploadedFile(
                    f"{code}-contract.txt",
                    b"demo contract",
                    content_type="text/plain",
                )
                contract.contract_file = contract_file
                contract.contract_start_date = project.start_date
                contract.contract_end_date = project.end_date
                contract.start_date = project.start_date
                contract.end_date = project.end_date
                contract.save()
            else:
                contract_skipped += 1

            wbs_items = _seed_wbs(project)
            created, skipped = _seed_budget(project, cost_items)
            budget_created += created
            budget_skipped += skipped
            _seed_actuals(project, cost_items, wbs_items, field_user, hq_user)

        self.stdout.write(
            f"ProjectContract seeded: created={contract_created}, skipped={contract_skipped}"
        )
        self.stdout.write(
            f"BudgetItem seeded: created={budget_created}, skipped={budget_skipped}"
        )
        self.stdout.write("seed_demo_3sites done.")


def _get_or_create_user(user_model, username, password, role):
    user, _created = user_model.objects.get_or_create(username=username)
    if password:
        user.set_password(password)
        user.save(update_fields=["password"])
    profile, _ = UserProfile.objects.get_or_create(user=user, defaults={"role": role})
    if profile.role != role:
        profile.role = role
        profile.save(update_fields=["role"])
    return user


def _seed_wbs(project):
    existing = list(WBSItem.objects.filter(project=project).order_by("sort_order"))
    if len(existing) >= 3:
        return existing
    today = timezone.localdate()
    items = [
        ("Foundation", Decimal("15.00"), 1, today, today + timedelta(days=20)),
        ("Structure", Decimal("20.00"), 2, today + timedelta(days=21), today + timedelta(days=60)),
        ("Facade", Decimal("15.00"), 3, today + timedelta(days=50), today + timedelta(days=95)),
        ("Interior", Decimal("20.00"), 4, today + timedelta(days=80), today + timedelta(days=140)),
        ("Landscape", Decimal("15.00"), 5, today + timedelta(days=110), today + timedelta(days=180)),
        ("Commissioning", Decimal("15.00"), 6, today + timedelta(days=170), today + timedelta(days=220)),
    ]
    created_items = []
    for name, weight, sort_order, start_date, end_date in items:
        wbs, _ = WBSItem.objects.get_or_create(
            project=project,
            name=name,
            defaults={
                "weight": weight,
                "sort_order": sort_order,
                "plan_start_date": start_date,
                "plan_end_date": end_date,
            },
        )
        created_items.append(wbs)
    return created_items


def _seed_budget(project, cost_items):
    existing = BudgetItem.objects.filter(project=project).count()
    if existing >= 10:
        return 0, 0

    preferred_work_types = {"07", "08", "09", "11", "12"}
    preferred = [item for item in cost_items if item.work_type in preferred_work_types]
    fallback = [item for item in cost_items if item not in preferred]
    candidates = preferred + fallback
    if not candidates:
        return 0, 0

    contract = ProjectContract.objects.filter(project=project).first()
    contract_amount = contract.contract_amount if contract else Decimal("0")
    target_ratio = Decimal("0.8")
    target_total = int((contract_amount * target_ratio).to_integral_value())
    if target_total <= 0:
        target_total = 100000000

    target_count = min(max(10, len(candidates) // 2), 30, len(candidates))
    per_item = max(target_total // target_count, 1000000)

    created = 0
    skipped = 0
    for idx, cost_item in enumerate(candidates[:target_count]):
        planned_amount = per_item + (idx % 5) * 500000
        _, was_created = BudgetItem.objects.get_or_create(
            project=project,
            cost_item=cost_item,
            defaults={
                "category": BudgetCategory.OTHER,
                "name": cost_item.name,
                "planned_amount": planned_amount,
                "status": ProjectContractStatus.APPROVED,
                "note": "demo budget",
            },
        )
        if was_created:
            created += 1
        else:
            skipped += 1
    return created, skipped


def _seed_cost_items():
    items = [
        ("COST-LABOR", "Labor", "labor"),
        ("COST-MAT", "Material", "material"),
        ("COST-EQUIP", "Equip", "equip"),
        ("COST-SUB", "Subcon", "subcon"),
        ("COST-OTHER", "Other", "other"),
    ]
    created = []
    for idx, (code, name, category) in enumerate(items):
        item, _ = CostItem.objects.get_or_create(
            code=code,
            defaults={
                "name": name,
                "category": category,
                "unit": "",
                "is_direct": True,
                "sort_order": idx,
            },
        )
        created.append(item)
    return created


def _seed_actuals(project, cost_items, wbs_items, field_user, hq_user):
    today = timezone.localdate()
    if CostActual.objects.filter(project=project).count() < 12:
        for offset in range(12):
            report_date = today - timedelta(days=offset)
            cost_status = (
                CostActualStatus.APPROVED
                if offset % 4 == 0
                else CostActualStatus.SUBMITTED
            )
            cost_actual = CostActual.objects.create(
                project=project,
                report_date=report_date,
                status=cost_status,
                approved_by=hq_user if cost_status == CostActualStatus.APPROVED else None,
                approved_at=timezone.now()
                if cost_status == CostActualStatus.APPROVED
                else None,
            )
            cost_item = cost_items[offset % len(cost_items)]
            CostActualLine.objects.create(
                cost_actual=cost_actual,
                cost_item=cost_item,
                description="demo",
                quantity=Decimal("8") + Decimal(offset % 5),
                unit_price=Decimal("900") + Decimal(offset * 150),
            )
            if cost_status == CostActualStatus.SUBMITTED:
                ApprovalRequest.objects.get_or_create(
                    object_type="COST_ACTUAL",
                    object_id=cost_actual.id,
                    defaults={
                        "status": ApprovalStatus.SUBMITTED,
                        "submitted_by": hq_user,
                        "submitted_at": timezone.now(),
                    },
                )

    active_plan = SchedulePlan.objects.filter(project=project, is_active=True).first()
    if active_plan is None:
        active_plan = SchedulePlan.objects.create(
            project=project,
            name="Baseline",
            version_no=1,
            is_active=True,
            created_by=hq_user,
        )

    tasks = []
    for idx, item in enumerate(wbs_items or []):
        task, _ = ScheduleTask.objects.get_or_create(
            plan=active_plan,
            name=item.name,
            defaults={
                "weight_percent": item.weight,
                "sort_order": idx + 1,
                "is_active": True,
            },
        )
        tasks.append(task)

    if tasks and DailyProgress.objects.filter(project=project).count() < 12:
        for offset in range(12):
            report_date = today - timedelta(days=offset)
            progress_status = "approved" if offset % 4 == 0 else "submitted"
            task = tasks[offset % len(tasks)]
            progress, created = DailyProgress.objects.get_or_create(
                project=project,
                plan=active_plan,
                task=task,
                report_date=report_date,
                reporter=field_user,
                defaults={
                    "progress_percent": min(
                        Decimal("100"), Decimal("9") * Decimal(offset + 1)
                    ),
                    "status": progress_status,
                    "note": "demo progress",
                },
            )
            if not created:
                continue
            if progress_status == "submitted":
                ApprovalRequest.objects.get_or_create(
                    object_type="DAILY_PROGRESS",
                    object_id=progress.id,
                    defaults={
                        "status": ApprovalStatus.SUBMITTED,
                        "submitted_by": field_user,
                        "submitted_at": timezone.now(),
                    },
                )

    if FieldReport.objects.filter(project=project).count() < 4:
        for idx in range(4):
            report_status = (
                FieldReportStatus.APPROVED
                if idx % 3 == 0
                else FieldReportStatus.SUBMITTED
            )
            report = FieldReport.objects.create(
                project=project,
                report_date=today - timedelta(days=idx),
                title=f"Report {idx + 1}",
                content="demo report",
                status=report_status,
                created_by=field_user,
                submitted_at=timezone.now()
                if report_status != FieldReportStatus.DRAFT
                else None,
                approved_at=timezone.now()
                if report_status == FieldReportStatus.APPROVED
                else None,
            )
            if report_status == FieldReportStatus.SUBMITTED:
                ApprovalRequest.objects.get_or_create(
                    object_type="FIELD_REPORT",
                    object_id=report.id,
                    defaults={
                        "status": ApprovalStatus.SUBMITTED,
                        "submitted_by": field_user,
                        "submitted_at": timezone.now(),
                    },
                )
