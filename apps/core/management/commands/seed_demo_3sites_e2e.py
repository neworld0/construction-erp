import importlib
import json
import os
import random
import re
from calendar import monthrange
from datetime import date, timedelta
from decimal import Decimal

from django.apps import apps
from django.contrib.auth import get_user_model
from django.core.files.base import ContentFile
from django.core.management import call_command
from django.core.management.base import BaseCommand, CommandError
from django.db import models
from django.utils import timezone


STATUS_MAP = {
    "approval": {
        "DRAFT": None,
        "SUBMITTED": None,
        "REJECTED": None,
        "APPROVED": None,
    },
    "closing": {
        "OPEN": None,
        "CLOSED": None,
    },
    "adjustment": {
        "DRAFT": None,
        "SUBMITTED": None,
        "REJECTED": None,
        "APPROVED": None,
    },
}

MODEL_HINTS = {
    "approval_model": "core.ApprovalRequest",
    "closing_period_model": "closing.ClosingPeriod",
    "adjustment_model": "closing.Adjustment",
    "evidence_model": "evidence.Evidence",
    "evidence_file_model": "evidence.EvidenceFile",
}

URL_HINTS = {
    "hq_inbox": "/app/hq/inbox/",
    "hq_closing": "/app/hq/closing/",
    "ceo_adjustments": "/app/ceo/adjustments/",
    "hq_project_detail": "/app/hq/projects/{project_id}/",
}


class Command(BaseCommand):
    help = "D3E-1 scaffold: discover E2E seed prerequisites for 3-sites demo (no writes)."

    def add_arguments(self, parser):
        parser.add_argument("--month", default="2026-02")
        parser.add_argument("--reset", action="store_true")
        parser.add_argument("--dry-run", dest="dry_run", action="store_true", default=True)
        parser.add_argument("--no-dry-run", dest="dry_run", action="store_false")
        parser.add_argument("--mode", choices=["discover", "d3e2", "d3e4"], default="discover")
        parser.add_argument("--ops", action="store_true")
        parser.add_argument("--target-progress", type=Decimal, default=None)
        parser.add_argument("--target-margin", type=Decimal, default=None)

    def handle(self, *args, **options):
        month = (options.get("month") or "2026-02").strip()
        if not re.fullmatch(r"\d{4}-\d{2}", month):
            raise CommandError("--month must be YYYY-MM format")
        year, month_no = month.split("-")
        if int(month_no) < 1 or int(month_no) > 12:
            raise CommandError("--month must be valid month (01..12)")

        if options.get("reset"):
            self.stdout.write("[D3E] --reset received: no-op in current phase.")

        dry_run = bool(options.get("dry_run", True))
        mode = options.get("mode")
        target_progress = options.get("target_progress")
        target_margin = options.get("target_margin")
        discovery = {
            "approvals": self._discover_approvals(),
            "closing": self._discover_closing(),
            "adjustment": self._discover_adjustment(),
            "attachments": self._discover_attachments(),
            "inventory": self._discover_inventory(),
            "labor": self._discover_labor(),
        }

        if mode == "discover":
            report = {
                "meta": {
                    "command": "seed_demo_3sites_e2e",
                    "phase": "D3E-1",
                    "month": month,
                    "mode": mode,
                    "dry_run": dry_run,
                    "db_writes": False,
                },
                "STATUS_MAP": self._build_status_map(),
                "MODEL_HINTS": self._build_model_hints(),
                "URL_HINTS": URL_HINTS,
                "discovery": discovery,
            }
            self.stdout.write(json.dumps(report, ensure_ascii=False, indent=2, default=str))
            return

        if mode == "d3e4":
            seed_summary = self._run_d3e4(
                month=month,
                dry_run=dry_run,
                target_progress=target_progress,
                target_margin=target_margin,
            )
        else:
            seed_summary = self._run_d3e2_seed(
                month=month,
                dry_run=dry_run,
                ops=bool(options.get("ops")),
                target_progress=target_progress,
                target_margin=target_margin,
            )
        report = {
            "meta": {
                "command": "seed_demo_3sites_e2e",
                "phase": "D3E-4" if mode == "d3e4" else "D3E-2",
                "month": month,
                "mode": mode,
                "dry_run": dry_run,
                "db_writes": not dry_run,
                "ops_data_created": bool(options.get("ops")) and not dry_run,
            },
            "STATUS_MAP": self._build_status_map(),
            "MODEL_HINTS": self._build_model_hints(),
            "URL_HINTS": URL_HINTS,
            "discovery": discovery,
            "seed": seed_summary,
        }
        self.stdout.write(json.dumps(report, ensure_ascii=False, indent=2, default=str))

    def _build_status_map(self):
        out = json.loads(json.dumps(STATUS_MAP))

        approval_model = _safe_get_model("core", "ApprovalRequest")
        if approval_model:
            status_field = _get_field(approval_model, "status")
            out["approval"] = _resolve_status_values(status_field, out["approval"])

        closing_model = _safe_get_model("closing", "ClosingPeriod")
        if closing_model:
            status_field = _get_field(closing_model, "status")
            out["closing"] = _resolve_status_values(status_field, out["closing"])

        adjustment_model = _safe_get_model("closing", "Adjustment")
        if adjustment_model:
            status_field = _get_field(adjustment_model, "status")
            out["adjustment"] = _resolve_status_values(status_field, out["adjustment"])

        return out

    def _build_model_hints(self):
        hints = dict(MODEL_HINTS)
        for key, label in list(hints.items()):
            app_label, model_name = label.split(".", 1)
            model = _safe_get_model(app_label, model_name)
            hints[key] = f"{app_label}.{model_name}" if model else None
        return hints

    def _discover_approvals(self):
        model = _safe_get_model("core", "ApprovalRequest")
        if not model:
            return {"found": False}

        status_field = _get_field(model, "status")
        resolved = _resolve_status_values(status_field, STATUS_MAP["approval"])
        timestamp_field = _first_existing_field(
            model, ["decided_at", "approved_at", "decision_at"]
        )
        return {
            "found": True,
            "model": _label(model),
            "status_field": status_field.name if status_field else None,
            "status_values": resolved,
            "decision_timestamp_field": timestamp_field,
        }

    def _discover_closing(self):
        model = _safe_get_model("closing", "ClosingPeriod")
        if not model:
            return {"found": False}

        close_method = "close" if hasattr(model, "close") else None
        service_hints = _discover_functions(
            "apps.closing.services", ["close_month", "approve_project_close"]
        )
        return {
            "found": True,
            "model": _label(model),
            "create_required_fields": _required_create_fields(model),
            "close_method": close_method,
            "close_status_field": "status" if _get_field(model, "status") else None,
            "closed_value": _resolve_status_values(_get_field(model, "status"), {"CLOSED": None}).get(
                "CLOSED"
            ),
            "service_functions": service_hints,
            "close_mark_fields_hint": ["status", "closed_at", "closed_by", "note"],
        }

    def _discover_adjustment(self):
        model = _safe_get_model("closing", "Adjustment")
        if not model:
            return {"found": False}

        status_field = _get_field(model, "status")
        approval_repr = {
            "status_field": status_field.name if status_field else None,
            "status_values": _resolve_status_values(status_field, STATUS_MAP["adjustment"]),
            "approved_by_field": _first_existing_field(model, ["approved_by"]),
            "approved_at_field": _first_existing_field(model, ["approved_at", "decided_at"]),
        }
        return {
            "found": True,
            "model": _label(model),
            "create_required_fields": _required_create_fields(model),
            "approval_representation": approval_repr,
            "service_functions": _discover_functions(
                "apps.closing.adjustments",
                ["submit_adjustment", "approve_adjustment", "reject_adjustment"],
            ),
        }

    def _discover_attachments(self):
        models_found = []
        for model in apps.get_models():
            app_label = model._meta.app_label
            model_name_lower = model.__name__.lower()
            names = {f.name for f in model._meta.get_fields() if isinstance(f, models.Field)}
            has_object_pair = {"object_type", "object_id"}.issubset(names)
            has_content_type_pair = {"content_type", "object_id"}.issubset(names)
            has_target_ct_pair = {"target_content_type", "target_object_id"}.issubset(names)
            has_file = any(isinstance(f, models.FileField) for f in model._meta.fields)
            is_attachment_related = (
                app_label == "evidence"
                or "evidence" in model_name_lower
                or (has_file and app_label in {"evidence", "reports"})
            )
            if not is_attachment_related:
                continue
            if has_object_pair or has_content_type_pair or has_target_ct_pair or has_file:
                link_method = None
                if has_object_pair:
                    link_method = "object_type/object_id"
                elif has_content_type_pair:
                    link_method = "content_type/object_id"
                elif has_target_ct_pair:
                    link_method = "target_content_type/target_object_id"
                models_found.append(
                    {
                        "model": _label(model),
                        "link_method": link_method,
                        "has_file_field": has_file,
                        "minimal_create_fields": _required_create_fields(model, attach_mode=True),
                    }
                )

        evidence = _safe_get_model("evidence", "Evidence")
        evidence_file = _safe_get_model("evidence", "EvidenceFile")
        return {
            "models": models_found,
            "primary_models_hint": [
                _label(evidence) if evidence else None,
                _label(evidence_file) if evidence_file else None,
            ],
        }

    def _discover_inventory(self):
        names = {m.__name__: m for m in apps.get_models()}
        keys = [
            "Warehouse",
            "Location",
            "InventoryLedger",
            "Stock",
            "Transfer",
            "IssueToWork",
        ]
        out = {}
        for key in keys:
            out[key] = _label(names[key]) if key in names else None
        out["IssueToWork_exists"] = bool(out.get("IssueToWork"))
        return out

    def _discover_labor(self):
        names = {m.__name__: m for m in apps.get_models()}
        keys = [
            "Timesheet",
            "LaborRole",
            "LaborRateTable",
            "PayrollAllocationBatch",
            "PayrollAllocationLine",
        ]
        out = {}
        for key in keys:
            out[key] = _label(names[key]) if key in names else None
        return out

    def _run_d3e2_seed(self, *, month: str, dry_run: bool, ops: bool = False, target_progress=None, target_margin=None):
        year, month_no = [int(x) for x in month.split("-")]
        start_date = date(year, month_no, 1)
        project_specs = [
            {
                "key": "P1",
                "code": "ASAN-\uc870\uacbd1",
                "name": "ASAN-\uc870\uacbd1 \uacf5\uc6d0 \ub9ac\ubaa8\ub378\ub9c1",
                "amount": Decimal("3000000000"),
                "end_date": date(2026, 5, 31),
                "project_type": "landscape",
                "warehouse_code": "P1-WH",
            },
            {
                "key": "P2",
                "code": "ASAN-\ud1a0\ubaa91",
                "name": "ASAN-\ud1a0\ubaa91 \uc6b0\uc218\uad00 \uc815\ube44",
                "amount": Decimal("2000000000"),
                "end_date": date(2026, 4, 30),
                "project_type": "civil",
                "warehouse_code": "P2-WH",
            },
            {
                "key": "P3",
                "code": "ASAN-\uac74\ucd951",
                "name": "ASAN-\uac74\ucd951 \uad00\ub9ac\ub3d9 \uc99d\ucd95",
                "amount": Decimal("800000000"),
                "end_date": date(2026, 3, 31),
                "project_type": "arch",
                "warehouse_code": "P3-WH",
            },
        ]
        user_specs = [
            ("ceo1", "ceo"),
            ("hq1", "hq"),
            ("hq2", "hq"),
            ("field3", "field"),
            ("field4", "field"),
            ("field5", "field"),
            ("field6", "field"),
        ]
        if dry_run:
            return {
                "seed_initial_called": False,
                "dry_run": True,
                "planned_projects": project_specs,
                "planned_users": [u for u, _r in user_specs],
                "planned_payroll_period": f"{year}-{month_no:02d}",
                "ops_data_created": bool(ops) and not dry_run,
            }

        UserProfile = _safe_get_model("core", "UserProfile")
        ProjectAssignment = _safe_get_model("core", "ProjectAssignment")
        Project = _safe_get_model("projects", "Project")
        ProjectContract = _safe_get_model("projects", "ProjectContract")
        WBSItem = _safe_get_model("projects", "WBSItem")
        BudgetItem = _safe_get_model("projects", "BudgetItem")
        CostItem = _safe_get_model("cost", "CostItem")
        CostItemAlias = _safe_get_model("cost", "CostItemAlias")
        Warehouse = _safe_get_model("inventory", "Warehouse")
        Location = _safe_get_model("inventory", "Location")
        UoM = _safe_get_model("inventory", "UoM")
        ItemCategory = _safe_get_model("inventory", "ItemCategory")
        ItemMaster = _safe_get_model("inventory", "ItemMaster")
        LaborRole = _safe_get_model("labor", "LaborRole")
        LaborRateTable = _safe_get_model("labor", "LaborRateTable")
        PayrollBatch = _safe_get_model("labor", "PayrollAllocationBatch")
        PayrollLine = _safe_get_model("labor", "PayrollAllocationLine")
        required = {
            "UserProfile": UserProfile,
            "ProjectAssignment": ProjectAssignment,
            "Project": Project,
            "ProjectContract": ProjectContract,
            "WBSItem": WBSItem,
            "BudgetItem": BudgetItem,
            "CostItem": CostItem,
            "Warehouse": Warehouse,
            "Location": Location,
            "UoM": UoM,
            "ItemMaster": ItemMaster,
            "LaborRole": LaborRole,
            "LaborRateTable": LaborRateTable,
            "PayrollAllocationBatch": PayrollBatch,
            "PayrollAllocationLine": PayrollLine,
        }
        missing = [k for k, v in required.items() if v is None]
        if missing:
            raise CommandError(f"Required models not found: {', '.join(missing)}")

        seed_initial_called = self._maybe_call_seed_initial(project_specs[0])
        users = self._ensure_users(user_specs, UserProfile)
        user_map = {username: user for username, _role, user, _has_2fa in users}
        hq_user = user_map["hq1"]

        hq_wh, _ = Warehouse.objects.get_or_create(
            code="HQ-WH",
            defaults={
                "name": "HQ Warehouse",
                "warehouse_type": "hq",
                "project": None,
                "is_active": True,
            },
        )
        hq_wh.name = "HQ Warehouse"
        hq_wh.warehouse_type = "hq"
        hq_wh.project = None
        hq_wh.is_active = True
        hq_wh.save()
        Location.objects.get_or_create(
            warehouse=hq_wh,
            code="MAIN",
            defaults={"name": "Main", "is_default": True, "is_active": True},
        )

        cbs_items, cbs_seeded = self._ensure_cbs_items(CostItem, CostItemAlias)
        item_master_count = self._ensure_item_master(UoM, ItemCategory, ItemMaster, hq_user)
        labor_summary = self._ensure_labor_masters(LaborRole, LaborRateTable, start_date, hq_user)
        budget_cbs = cbs_items[: min(max(10, len(cbs_items)), 20)]

        projects_by_key = {}
        project_rows = []
        for spec in project_specs:
            project, _ = Project.objects.get_or_create(
                code=spec["code"],
                defaults={
                    "name": spec["name"],
                    "project_type": spec["project_type"],
                    "start_date": start_date,
                    "end_date": spec["end_date"],
                    "contract_amount": spec["amount"],
                    "status": "approved",
                    "is_active": True,
                },
            )
            project.name = spec["name"]
            project.project_type = spec["project_type"]
            project.start_date = start_date
            project.end_date = spec["end_date"]
            project.contract_amount = spec["amount"]
            project.status = "approved"
            project.is_active = True
            project.save()
            projects_by_key[spec["key"]] = project

            site_wh, _ = Warehouse.objects.get_or_create(
                code=spec["warehouse_code"],
                defaults={
                    "name": f"{spec['key']} Warehouse",
                    "warehouse_type": "site",
                    "project": project,
                    "is_active": True,
                },
            )
            site_wh.name = f"{spec['key']} Warehouse"
            site_wh.warehouse_type = "site"
            site_wh.project = project
            site_wh.is_active = True
            site_wh.save()
            Location.objects.get_or_create(
                warehouse=site_wh,
                code="MAIN",
                defaults={"name": "Main", "is_default": True, "is_active": True},
            )

            contract, _ = ProjectContract.objects.get_or_create(project=project)
            contract.contract_amount = spec["amount"]
            contract.contract_start_date = start_date
            contract.contract_end_date = spec["end_date"]
            contract.start_date = start_date
            contract.end_date = spec["end_date"]
            contract.status = "approved"
            contract.memo = "D3E-2 scenario contract"
            contract.contract_file.save(
                f"{spec['code']}-contract.txt",
                ContentFile(
                    (
                        f"Contract for {spec['name']}\n"
                        f"Amount={spec['amount']}\n"
                        f"Period={start_date}~{spec['end_date']}\n"
                    ).encode("utf-8")
                ),
                save=False,
            )
            contract.save()

            wbs_created = self._ensure_wbs_baseline(WBSItem, project, start_date, spec["end_date"])
            budget_line_count = self._ensure_budget(BudgetItem, project, budget_cbs, spec["amount"])
            project_rows.append(
                {
                    "project_key": spec["key"],
                    "project_id": project.id,
                    "project_code": project.code,
                    "project_name": project.name,
                    "hq_url": URL_HINTS["hq_project_detail"].format(project_id=project.id),
                    "wbs_created": bool(wbs_created),
                    "wbs_status": "baseline_v1",
                    "budget_created": budget_line_count > 0,
                    "budget_line_count": budget_line_count,
                    "contract_attachment_created": bool(contract.contract_file),
                }
            )

        assignment_map = {"field3": ["P1"], "field4": ["P2"], "field5": ["P3"], "field6": ["P1"]}
        for username, keys in assignment_map.items():
            user = user_map[username]
            for key in keys:
                ProjectAssignment.objects.update_or_create(
                    user=user,
                    project=projects_by_key[key],
                    defaults={"is_active": True},
                )

        payroll_batch, _ = PayrollBatch.objects.get_or_create(
            period_year=year,
            period_month=month_no,
            defaults={
                "batch_no": f"PAY-{year}{month_no:02d}-HQ",
                "total_amount": 0,
                "created_by": hq_user,
                "note": "D3E-2 HQ payroll allocation",
            },
        )
        if not payroll_batch.batch_no:
            payroll_batch.batch_no = f"PAY-{year}{month_no:02d}-HQ"
        if not payroll_batch.created_by_id:
            payroll_batch.created_by = hq_user
        payroll_batch.note = "D3E-2 HQ payroll allocation"
        payroll_batch.save()
        PayrollLine.objects.update_or_create(
            batch=payroll_batch,
            project=projects_by_key["P1"],
            defaults={
                "cbs": budget_cbs[0] if budget_cbs else None,
                "amount": 10000000,
                "memo": "D3E-2 seed allocation",
            },
        )
        total_amount = sum(payroll_batch.lines.values_list("amount", flat=True))
        payroll_batch.total_amount = total_amount
        payroll_batch.save(update_fields=["total_amount", "updated_at"])

        ops_summary = {}
        if ops:
            ops_summary = self._seed_ops_data(
                year=year,
                month=month_no,
                projects_by_key=projects_by_key,
                user_map=user_map,
                cbs_items=cbs_items,
                target_progress=target_progress,
                target_margin=target_margin,
            )

        return {
            "seed_initial_called": seed_initial_called,
            "dry_run": False,
            "ops_data_created": bool(ops) and not dry_run,
            "projects": project_rows,
            "field_assignments": {
                username: [projects_by_key[k].code for k in keys]
                for username, keys in assignment_map.items()
            },
            "masters": {
                "warehouses": {
                    "count": Warehouse.objects.filter(code__in=["HQ-WH", "P1-WH", "P2-WH", "P3-WH"]).count(),
                    "codes": ["HQ-WH", "P1-WH", "P2-WH", "P3-WH"],
                },
                "item_master_count": item_master_count,
                "cbs_count": len(cbs_items),
                "cbs_seeded_minimal": cbs_seeded,
                "labor": labor_summary,
            },
            "payroll_allocation": {
                "batch_id": payroll_batch.id,
                "period": f"{year}-{month_no:02d}",
                "status": payroll_batch.status,
                "line_count": payroll_batch.lines.count(),
                "total_amount": payroll_batch.total_amount,
            },
            "ops": ops_summary,
        }

    def _run_d3e4(self, *, month: str, dry_run: bool, target_progress=None, target_margin=None):
        year, month_no = [int(x) for x in month.split("-")]
        if dry_run:
            return {
                "phase": "D3E-4",
                "dry_run": True,
                "notes": ["Dry-run mode: no DB writes executed."],
            }

        Project = _safe_get_model("projects", "Project")
        ClosingPeriod = _safe_get_model("closing", "ClosingPeriod")
        CostItem = _safe_get_model("cost", "CostItem")
        Adjustment = _safe_get_model("closing", "Adjustment")
        Warehouse = _safe_get_model("inventory", "Warehouse")
        Location = _safe_get_model("inventory", "Location")
        Transfer = _safe_get_model("inventory", "Transfer")
        TransferLine = _safe_get_model("inventory", "TransferLine")
        Stock = _safe_get_model("inventory", "Stock")
        ItemMaster = _safe_get_model("inventory", "ItemMaster")
        IssueToWorkLine = _safe_get_model("inventory", "IssueToWorkLine")

        if not all([Project, ClosingPeriod, CostItem, Adjustment, Warehouse, Location, Transfer, TransferLine, Stock, ItemMaster]):
            raise CommandError("D3E-4 requires projects/closing/cost/inventory models.")

        from apps.closing.guards import guard_write
        from apps.closing.services import close_month
        from apps.closing.adjustments import (
            create_adjustment,
            submit_adjustment,
            approve_adjustment,
            get_adjustment_totals,
        )
        from apps.evidence.attachment_policy import can_edit_attachments
        from django.core.exceptions import PermissionDenied

        User = get_user_model()
        ceo = User.objects.filter(username__in=["ceo1", "ceo"]).order_by("id").first()
        hq = User.objects.filter(username__in=["hq1", "hq"]).order_by("id").first()
        if ceo is None or hq is None:
            raise CommandError("D3E-4 requires CEO/HQ users from D3E-2.")

        p1 = Project.objects.filter(code="ASAN-조경1").first()
        p2 = Project.objects.filter(code="ASAN-토목1").first()
        p3 = Project.objects.filter(code="ASAN-건축1").first()
        if not all([p1, p2, p3]):
            raise CommandError("D3E-4 requires ASAN 3 projects from D3E-2.")

        period = ClosingPeriod.objects.filter(year=year, month=month_no).first()
        if period is None or period.status != "CLOSED":
            period = close_month(year, month_no, actor=hq, note="D3E-4 monthly close")

        close_blocked = False
        close_block_error = ""
        try:
            guard_write(project=p1, target_date=date(year, month_no, 15), message_context="D3E-4 close test")
        except PermissionDenied as exc:
            close_blocked = True
            close_block_error = str(exc)

        cbs = CostItem.objects.filter(is_active=True).order_by("sort_order", "id").first()
        if cbs is None:
            raise CommandError("No active CostItem found for D3E-4 adjustment.")

        adj1 = Adjustment.objects.filter(
            project=p1,
            target_type="COST",
            period_year=year,
            period_month=month_no,
            amount_delta=18000000,
            reason="P1 equipment rental missing",
        ).order_by("-id").first()
        if adj1 is None:
            adj1 = create_adjustment(
                actor=hq,
                project=p1,
                target_type="COST",
                period_year=year,
                period_month=month_no,
                amount_delta=18000000,
                reason="P1 equipment rental missing",
                cbs=cbs,
            )
        if adj1.status == "DRAFT":
            submit_adjustment(adj1, actor=hq)
        if adj1.status != "APPROVED":
            approve_adjustment(adj1, actor=ceo)

        adj2 = Adjustment.objects.filter(
            project=p2,
            target_type="LABOR",
            period_year=year,
            period_month=month_no,
            amount_delta=9500000,
            reason="P2 labor/payroll correction",
        ).order_by("-id").first()
        if adj2 is None:
            adj2 = create_adjustment(
                actor=hq,
                project=p2,
                target_type="LABOR",
                period_year=year,
                period_month=month_no,
                amount_delta=9500000,
                reason="P2 labor/payroll correction",
                cbs=None,
            )
        if adj2.status == "DRAFT":
            submit_adjustment(adj2, actor=hq)
        if adj2.status != "APPROVED":
            approve_adjustment(adj2, actor=ceo)

        totals_cost = get_adjustment_totals([p1.id, p2.id, p3.id], target_type="COST", as_of_date=date(year, month_no, 28))
        totals_labor = get_adjustment_totals([p1.id, p2.id, p3.id], target_type="LABOR", as_of_date=date(year, month_no, 28))

        r5_blocked = False
        try:
            guard_write(project=p2, target_date=date(year, month_no, 20), message_context="DRAFT attempt in closed month")
        except PermissionDenied:
            r5_blocked = True

        hq_wh = Warehouse.objects.filter(code="HQ-WH").first()
        p3_wh = Warehouse.objects.filter(code="P3-WH").first()
        hq_loc = Location.objects.filter(warehouse=hq_wh, is_default=True).first() if hq_wh else None
        p3_loc = Location.objects.filter(warehouse=p3_wh, is_default=True).first() if p3_wh else None
        item = ItemMaster.objects.filter(is_active=True).order_by("-id").first()
        if not all([hq_wh, p3_wh, hq_loc, p3_loc, item]):
            raise CommandError("D3E-4 R6 requires HQ/P3 warehouse+location+item.")

        tr = Transfer.objects.filter(
            project=p3,
            from_warehouse=hq_wh,
            to_warehouse=p3_wh,
            tx_date=date(year, month_no, 27),
            note="D3E-4 R6 transfer without issue",
        ).order_by("-id").first()
        if tr is None:
            transfer_no = f"TR-R6-{year}{month_no:02d}-{timezone.now().strftime('%H%M%S')}"
            tr = Transfer.objects.create(
                transfer_no=transfer_no,
                direction="HQ_TO_SITE",
                project=p3,
                from_warehouse=hq_wh,
                from_location=hq_loc,
                to_warehouse=p3_wh,
                to_location=p3_loc,
                tx_date=date(year, month_no, 27),
                status="RECEIVED",
                note="D3E-4 R6 transfer without issue",
                created_by=hq,
                submitted_at=timezone.now(),
                issued_at=timezone.now(),
                received_at=timezone.now(),
            )
        TransferLine.objects.update_or_create(
            transfer=tr,
            item=item,
            defaults={
                "uom": item.uom,
                "qty": Decimal("9.000"),
                "note": "R6 transfer line",
            },
        )
        stock, _ = Stock.objects.get_or_create(
            warehouse=p3_wh,
            location=p3_loc,
            item=item,
            defaults={"qty_on_hand": Decimal("0.000")},
        )
        stock.qty_on_hand = Decimal("9.000")
        stock.save(update_fields=["qty_on_hand", "updated_at"])
        issue_count = (
            IssueToWorkLine.objects.filter(issue__project=p3, item=item).count()
            if IssueToWorkLine is not None
            else 0
        )

        finance_summary = self._seed_finance_metrics(
            year=year,
            month=month_no,
            projects=[p1, p2, p3],
            hq_user=hq,
            target_progress=target_progress,
            target_margin=target_margin,
        )

        return {
            "phase": "D3E-4",
            "closing_period": {
                "year": year,
                "month": month_no,
                "status": period.status,
                "id": period.id,
            },
            "close_guard_check": {
                "blocked": close_blocked,
                "message": close_block_error,
            },
            "adjustments": {
                "created_ids": [adj1.id, adj2.id],
                "approved_ids": [adj1.id, adj2.id],
                "kpi_totals_cost": totals_cost,
                "kpi_totals_labor": totals_labor,
            },
            "risk_cases": {
                "R5_draft_in_closed_month_blocked": r5_blocked,
                "R5_redirect_hint": "/app/hq/adjustments/",
                "R6_transfer_id": tr.id,
                "R6_issue_count_for_transfer_item": issue_count,
                "R6_remaining_stock_qty": str(stock.qty_on_hand),
            },
            "attachment_policy_check": {
                "reject_editable": can_edit_attachments(status="rejected", is_closed_locked=False),
                "submitted_editable": can_edit_attachments(status="submitted", is_closed_locked=False),
            },
            "url_hints": {
                "hq_inbox": "/app/hq/inbox/",
                "ceo_approvals": "/app/ceo/inbox/",
                "ceo_adjustment_detail_1": f"/app/ceo/adjustments/{adj1.id}/",
                "ceo_adjustment_detail_2": f"/app/ceo/adjustments/{adj2.id}/",
            },
            "finance_seed": finance_summary,
        }

    def _seed_ops_data(self, *, year, month, projects_by_key, user_map, cbs_items, target_progress=None, target_margin=None):
        SchedulePlan = _safe_get_model("schedule", "SchedulePlan")
        ScheduleTask = _safe_get_model("schedule", "ScheduleTask")
        DailyProgress = _safe_get_model("schedule", "DailyProgress")
        FieldReport = _safe_get_model("reports", "FieldReport")
        FieldReportFile = _safe_get_model("reports", "FieldReportFile")
        CostActual = _safe_get_model("cost", "CostActual")
        CostActualLine = _safe_get_model("cost", "CostActualLine")
        Timesheet = _safe_get_model("labor", "Timesheet")
        TimesheetLine = _safe_get_model("labor", "TimesheetLine")
        LaborRole = _safe_get_model("labor", "LaborRole")
        Warehouse = _safe_get_model("inventory", "Warehouse")
        Location = _safe_get_model("inventory", "Location")
        ItemMaster = _safe_get_model("inventory", "ItemMaster")
        InventoryLedger = _safe_get_model("inventory", "InventoryLedger")
        Transfer = _safe_get_model("inventory", "Transfer")
        TransferLine = _safe_get_model("inventory", "TransferLine")
        IssueToWork = _safe_get_model("inventory", "IssueToWork")
        IssueToWorkLine = _safe_get_model("inventory", "IssueToWorkLine")
        ApprovalRequest = _safe_get_model("core", "ApprovalRequest")
        ApprovalPackage = _safe_get_model("projects", "ApprovalPackage")
        Evidence = _safe_get_model("evidence", "Evidence")
        EvidenceFile = _safe_get_model("evidence", "EvidenceFile")

        if not all([SchedulePlan, ScheduleTask, DailyProgress, FieldReport, FieldReportFile, CostActual, CostActualLine, Timesheet, TimesheetLine, LaborRole, ApprovalRequest]):
            raise CommandError("D3E-3 requires schedule/reports/cost/labor/core models.")

        field_users = {k: user_map[k] for k in ("field3", "field4", "field5", "field6") if k in user_map}
        hq_user = user_map["hq1"]
        ceo_user = user_map["ceo1"]
        labor_role = LaborRole.objects.order_by("sort_order", "id").first()
        if labor_role is None:
            raise CommandError("LaborRole not found for timesheet seeding.")

        status_map = self._build_status_map().get("approval", {})
        SUB = status_map.get("SUBMITTED") or "submitted"
        APP = status_map.get("APPROVED") or "approved"
        REJ = status_map.get("REJECTED") or "rejected"

        progress_pending = 0
        report_pending = 0
        cost_pending = 0
        timesheet_pending = 0
        issue_seed_skipped = False
        rng = random.Random(20260229)

        projects = [projects_by_key[k] for k in ("P1", "P2", "P3") if k in projects_by_key]
        for idx, project in enumerate(projects):
            field_user = field_users.get(f"field{idx+3}") or next(iter(field_users.values()))
            workdays = self._pick_workdays(year, month, project.id, min_days=8, max_days=12)

            plan, _ = SchedulePlan.objects.get_or_create(
                project=project,
                is_active=True,
                defaults={"version_no": 1, "name": "Ops Baseline", "created_by": hq_user},
            )
            tasks = list(ScheduleTask.objects.filter(plan=plan).order_by("sort_order", "id")[:3])
            if not tasks:
                for t_idx, t_name in enumerate(["Task-A", "Task-B", "Task-C"], start=1):
                    tasks.append(
                        ScheduleTask.objects.create(
                            plan=plan,
                            name=t_name,
                            sort_order=t_idx,
                            weight_percent=Decimal("33.333"),
                            start_date=workdays[0],
                            end_date=workdays[-1],
                        )
                    )

            progress_states = [
                "submitted", "approved", "draft", "submitted", "approved", "draft", "approved", "draft"
            ]
            for p_idx, day in enumerate(workdays[:8]):
                state = progress_states[p_idx] if p_idx < len(progress_states) else "draft"
                if idx > 0 and state == "submitted" and p_idx == 3:
                    state = "draft"
                entry = DailyProgress.objects.create(
                    project=project,
                    plan=plan,
                    task=tasks[p_idx % len(tasks)],
                    report_date=day,
                    progress_percent=Decimal(str(15 + (p_idx * 8) % 70)),
                    status=state,
                    reporter=field_user,
                    note=f"D3E3 progress {p_idx+1}",
                )
                if state != "submitted" or not (idx == 0 and p_idx == 0):
                    self._attach_evidence(
                        Evidence,
                        EvidenceFile,
                        "DAILY_PROGRESS",
                        entry.id,
                        field_user,
                        1 + (p_idx % 2),
                        f"progress-{project.id}-{entry.id}",
                    )
                if idx == 0 and p_idx == 3:
                    self._create_approval(ApprovalRequest, "DAILY_PROGRESS", entry.id, REJ, field_user, hq_user)
                    self._create_approval(ApprovalRequest, "DAILY_PROGRESS", entry.id, SUB, field_user, None)
                    progress_pending += 1
                elif state == "submitted":
                    self._upsert_approval(ApprovalRequest, "DAILY_PROGRESS", entry.id, SUB, field_user, None)
                    progress_pending += 1
                elif state == "approved":
                    self._upsert_approval(ApprovalRequest, "DAILY_PROGRESS", entry.id, APP, field_user, ceo_user)

            report_days = [workdays[1], workdays[1], workdays[3], workdays[5]]
            for r_idx, day in enumerate(report_days):
                report = FieldReport.objects.create(
                    project=project,
                    report_date=day,
                    title=f"D3E3 Report {r_idx+1} - {project.code}",
                    content="D3E3 seeded field report",
                    status="DRAFT",
                    created_by=field_user,
                )
                status = "SUBMITTED" if r_idx in (0, 3) else ("APPROVED" if r_idx == 1 else "DRAFT")
                if idx > 0 and status == "SUBMITTED" and r_idx == 3:
                    status = "DRAFT"

                if idx == 0 and r_idx == 0:
                    report.status = "REJECTED"
                    report.save(update_fields=["status", "updated_at"])
                    old_file = FieldReportFile.objects.create(
                        report=report,
                        file=ContentFile(b"old", name=f"report-old-{report.id}.jpg"),
                        original_name=f"report-old-{report.id}.jpg",
                        uploaded_by=field_user,
                    )
                    old_file.delete()
                    FieldReportFile.objects.create(
                        report=report,
                        file=ContentFile(b"new", name=f"report-new-{report.id}.jpg"),
                        original_name=f"report-new-{report.id}.jpg",
                        uploaded_by=field_user,
                    )
                    report.status = "SUBMITTED"
                    report.submitted_at = timezone.now()
                    report.save(update_fields=["status", "submitted_at", "updated_at"])
                    self._create_approval(ApprovalRequest, "FIELD_REPORT", report.id, REJ, field_user, hq_user)
                    self._create_approval(ApprovalRequest, "FIELD_REPORT", report.id, SUB, field_user, None)
                    report_pending += 1
                    continue

                if status in {"SUBMITTED", "APPROVED"}:
                    FieldReportFile.objects.create(
                        report=report,
                        file=ContentFile(b"img", name=f"report-{report.id}.jpg"),
                        original_name=f"report-{report.id}.jpg",
                        uploaded_by=field_user,
                    )
                report.status = status
                report.submitted_at = timezone.now() if status == "SUBMITTED" else report.submitted_at
                report.approved_at = timezone.now() if status == "APPROVED" else report.approved_at
                report.save(update_fields=["status", "submitted_at", "approved_at", "updated_at"])
                if status == "SUBMITTED":
                    self._upsert_approval(ApprovalRequest, "FIELD_REPORT", report.id, SUB, field_user, None)
                    report_pending += 1
                elif status == "APPROVED":
                    self._upsert_approval(ApprovalRequest, "FIELD_REPORT", report.id, APP, field_user, ceo_user)

            cost_days = [workdays[2], workdays[2], workdays[4], workdays[6]]
            for c_idx, day in enumerate(cost_days):
                status = "submitted" if c_idx in (0, 2) else ("approved" if c_idx == 1 else "draft")
                if idx > 0 and status == "submitted" and c_idx == 2:
                    status = "draft"
                cost = CostActual.objects.create(
                    project=project,
                    report_date=day,
                    status=status,
                )
                for line_idx in range(2):
                    item = cbs_items[(c_idx + line_idx) % len(cbs_items)]
                    CostActualLine.objects.create(
                        cost_actual=cost,
                        cost_item=item,
                        description=f"D3E3 cost line {line_idx+1}",
                        quantity=Decimal("1.000"),
                        unit_price=Decimal(str(10000 + (line_idx * 2500))),
                    )
                cost.recalculate_total()
                if not (idx == 0 and c_idx == 0):
                    self._attach_evidence(
                        Evidence,
                        EvidenceFile,
                        "COST_ACTUAL",
                        cost.id,
                        field_user,
                        1 + (c_idx % 2),
                        f"cost-{project.id}-{cost.id}",
                    )
                if status == "submitted":
                    self._upsert_approval(ApprovalRequest, "COST_ACTUAL", cost.id, SUB, field_user, None)
                    cost_pending += 1
                elif status == "approved":
                    self._upsert_approval(ApprovalRequest, "COST_ACTUAL", cost.id, APP, field_user, ceo_user)

            month_end = date(year, month, 28)
            t_rng = random.Random(project.id * 131 + year * 100 + month)
            ts_target = 6 if len(workdays) <= 6 else min(10, t_rng.randint(6, min(10, len(workdays))))
            ts_days = sorted(set(workdays[: max(ts_target - 1, 1)] + [month_end]))[:10]
            for t_idx, day in enumerate(ts_days):
                sheet_no = f"TS-{year}{month:02d}-{project.id:03d}-{t_idx+1:02d}"
                t_status = "APPROVED" if t_idx in (0, 2, 4) else ("SUBMITTED" if t_idx == 5 else "DRAFT")
                timesheet, _ = Timesheet.objects.get_or_create(
                    sheet_no=sheet_no,
                    defaults={
                        "project": project,
                        "work_date": day,
                        "status": t_status,
                        "note": "D3E3 timesheet",
                        "created_by": field_user,
                    },
                )
                timesheet.project = project
                timesheet.work_date = day
                timesheet.status = t_status
                timesheet.note = "D3E3 timesheet"
                timesheet.created_by = field_user
                if t_status == "SUBMITTED":
                    timesheet.submitted_at = timezone.now()
                if t_status == "APPROVED":
                    timesheet.approved_by = hq_user
                    timesheet.approved_at = timezone.now()
                timesheet.save()
                TimesheetLine.objects.update_or_create(
                    timesheet=timesheet,
                    labor_role=labor_role,
                    defaults={
                        "headcount": Decimal("3.00"),
                        "hours": Decimal("8.00"),
                        "rate_type": "DAY",
                        "unit_rate": 240000,
                        "amount": 720000,
                        "memo": "D3E3 labor line",
                    },
                )
                if idx == 0 and t_idx == 1:
                    timesheet.status = "REJECTED"
                    timesheet.rejected_by = hq_user
                    timesheet.rejected_at = timezone.now()
                    timesheet.reject_reason = "Missing memo"
                    timesheet.save(update_fields=["status", "rejected_by", "rejected_at", "reject_reason", "updated_at"])
                    self._create_approval(ApprovalRequest, "TIMESHEET", timesheet.id, REJ, field_user, hq_user)
                    timesheet.status = "SUBMITTED"
                    timesheet.submitted_at = timezone.now()
                    timesheet.save(update_fields=["status", "submitted_at", "updated_at"])
                    self._create_approval(ApprovalRequest, "TIMESHEET", timesheet.id, SUB, field_user, None)
                    timesheet_pending += 1
                elif timesheet.status == "SUBMITTED":
                    self._upsert_approval(ApprovalRequest, "TIMESHEET", timesheet.id, SUB, field_user, None)
                    timesheet_pending += 1
                elif timesheet.status == "APPROVED":
                    self._upsert_approval(ApprovalRequest, "TIMESHEET", timesheet.id, APP, field_user, ceo_user)

        inventory_summary = {"receipts": 0, "transfers": 0, "issues": 0, "issue_seed_skipped": False}
        if Warehouse and Location and ItemMaster and InventoryLedger and Transfer and TransferLine:
            hq_wh = Warehouse.objects.filter(code="HQ-WH").first()
            hq_loc = Location.objects.filter(warehouse=hq_wh, is_default=True).first() if hq_wh else None
            items = list(ItemMaster.objects.filter(is_active=True).order_by("id")[:12])
            if hq_wh and hq_loc and items:
                for i in range(6):
                    InventoryLedger.objects.create(
                        tx_type="RECEIPT",
                        tx_date=date(year, month, 1) + timedelta(days=2 + i * 3),
                        warehouse=hq_wh,
                        location=hq_loc,
                        item=items[i % len(items)],
                        qty_delta=Decimal("10.000"),
                        uom=items[i % len(items)].uom,
                        unit_cost=10000 + (i * 100),
                        amount=100000 + (i * 1000),
                        ref_type="MANUAL",
                        note="D3E3 HQ receipt",
                        created_by=hq_user,
                    )
                    inventory_summary["receipts"] += 1

            site_specs = [("P1-WH", "P1"), ("P2-WH", "P2"), ("P3-WH", "P3")]
            for i, (site_code, p_key) in enumerate(site_specs):
                site_wh = Warehouse.objects.filter(code=site_code).first()
                site_loc = Location.objects.filter(warehouse=site_wh, is_default=True).first() if site_wh else None
                if not (hq_wh and site_wh and hq_loc and site_loc and items):
                    continue
                tr = Transfer.objects.create(
                    transfer_no=f"TR-{year}{month:02d}-{i+1:03d}",
                    direction="HQ_TO_SITE",
                    project=projects_by_key[p_key],
                    from_warehouse=hq_wh,
                    from_location=hq_loc,
                    to_warehouse=site_wh,
                    to_location=site_loc,
                    tx_date=date(year, month, 5 + i * 4),
                    status="RECEIVED",
                    note="D3E3 transfer",
                    created_by=hq_user,
                    submitted_at=timezone.now(),
                    issued_at=timezone.now(),
                    received_at=timezone.now(),
                )
                TransferLine.objects.create(
                    transfer=tr,
                    item=items[i % len(items)],
                    uom=items[i % len(items)].uom,
                    qty=Decimal("5.000"),
                    note="D3E3 transfer line",
                )
                inventory_summary["transfers"] += 1

            if IssueToWork and IssueToWorkLine and cbs_items:
                for i, (site_code, p_key) in enumerate(site_specs):
                    site_wh = Warehouse.objects.filter(code=site_code).first()
                    site_loc = Location.objects.filter(warehouse=site_wh, is_default=True).first() if site_wh else None
                    if not (site_wh and site_loc and items):
                        continue
                    issue = IssueToWork.objects.create(
                        issue_no=f"IS-{year}{month:02d}-{i+1:03d}",
                        project=projects_by_key[p_key],
                        warehouse=site_wh,
                        location=site_loc,
                        issue_date=date(year, month, 10 + i * 5),
                        status="SUBMITTED" if i < 2 else "APPROVED",
                        note="D3E3 issue to work",
                        created_by=hq_user,
                        submitted_at=timezone.now(),
                        approved_at=timezone.now() if i == 2 else None,
                        approved_by=hq_user if i == 2 else None,
                    )
                    IssueToWorkLine.objects.create(
                        issue=issue,
                        item=items[(i + 1) % len(items)],
                        qty=Decimal("2.000"),
                        uom=items[(i + 1) % len(items)].uom,
                        cbs=cbs_items[i % len(cbs_items)],
                        unit_cost=12000,
                        amount=24000,
                        memo="D3E3 issue line",
                    )
                    inventory_summary["issues"] += 1
            else:
                inventory_summary["issue_seed_skipped"] = True
                issue_seed_skipped = True
        else:
            inventory_summary["issue_seed_skipped"] = True
            issue_seed_skipped = True

        approved_counts = {
            "progress": ApprovalRequest.objects.filter(status=APP, object_type="DAILY_PROGRESS").count(),
            "report": ApprovalRequest.objects.filter(status=APP, object_type="FIELD_REPORT").count(),
            "cost": ApprovalRequest.objects.filter(status=APP, object_type="COST_ACTUAL").count(),
        }
        pending_counts = {
            "progress": progress_pending,
            "report": report_pending,
            "cost": cost_pending,
            "timesheet": timesheet_pending,
        }
        ceo_only = {"seeded": False, "type": None, "count": 0, "note": "No CEO-only feature found"}
        if ApprovalPackage and projects:
            pkg, _ = ApprovalPackage.objects.get_or_create(
                project=projects[0],
                title="D3E3 CEO approval package",
                defaults={
                    "reason": "D3E3 seeded package",
                    "created_by": hq_user,
                    "status": "submitted",
                    "submitted_at": timezone.now(),
                },
            )
            if pkg.status == "draft":
                pkg.status = "submitted"
                pkg.submitted_at = timezone.now()
                pkg.save(update_fields=["status", "submitted_at", "updated_at"])
            ceo_only = {"seeded": True, "type": "ApprovalPackage", "count": 1, "ids": [pkg.id]}
        finance_summary = self._seed_finance_metrics(
            year=year,
            month=month,
            projects=projects,
            hq_user=hq_user,
            target_progress=target_progress,
            target_margin=target_margin,
        )
        return {
            "hq_inbox_url_hint": "/app/hq/inbox/",
            "ceo_approvals_url_hint": "/app/ceo/inbox/",
            "pending_counts": pending_counts,
            "field_approved_counts": approved_counts,
            "inventory": inventory_summary,
            "ceo_only": ceo_only,
            "issue_seed_skipped": issue_seed_skipped,
            "finance_seed": finance_summary,
        }

    def _seed_finance_metrics(self, *, year, month, projects, hq_user, target_progress=None, target_margin=None):
        DailyProgress = _safe_get_model("schedule", "DailyProgress")
        CostActual = _safe_get_model("cost", "CostActual")
        CostActualLine = _safe_get_model("cost", "CostActualLine")
        CostItem = _safe_get_model("cost", "CostItem")
        RevenueRecognition = _safe_get_model("cost", "RevenueRecognition")
        ContractSnapshot = _safe_get_model("contracts", "ContractSnapshot")
        CashAccount = _safe_get_model("finance", "CashAccount")
        CashEvent = _safe_get_model("finance", "CashEvent")
        if not all([DailyProgress, CostActual, CostActualLine, CostItem, RevenueRecognition, ContractSnapshot, CashAccount, CashEvent]):
            return {"seeded": False, "reason": "finance or contract models unavailable"}

        month_end = date(year, month, monthrange(year, month)[1])
        account, _ = CashAccount.objects.get_or_create(
            name="Demo Main Account",
            defaults={"bank_name": "Demo Bank", "masked_account_no": "000-***-0000", "is_active": True},
        )
        default_cost_item = CostItem.objects.filter(is_active=True).order_by("sort_order", "id").first()
        if default_cost_item is None:
            return {"seeded": False, "reason": "active CostItem not found"}

        rows = []
        for project in projects:
            approved_progress = (
                DailyProgress.objects.filter(
                    project=project,
                    status="approved",
                    report_date__lte=month_end,
                )
                .order_by("-report_date", "-id")
                .first()
            )
            progress_percent = Decimal(getattr(approved_progress, "progress_percent", 0) or 0)
            if target_progress is not None:
                progress_percent = Decimal(target_progress)
            if progress_percent > Decimal("100"):
                progress_percent = Decimal("100")
            if progress_percent < Decimal("0"):
                progress_percent = Decimal("0")

            snapshot = (
                ContractSnapshot.objects.filter(project=project, is_active=True)
                .order_by("-version_no")
                .first()
            )
            if snapshot is None:
                latest = ContractSnapshot.objects.filter(project=project).order_by("-version_no").first()
                next_version = (latest.version_no if latest else 0) + 1
                snapshot = ContractSnapshot.objects.create(
                    project=project,
                    version_no=next_version,
                    base_contract_amount=Decimal(getattr(project, "contract_amount", 0) or 0),
                    start_date=getattr(project, "start_date", None),
                    end_date=getattr(project, "end_date", None),
                    is_active=True,
                )

            revenue, _ = RevenueRecognition.objects.update_or_create(
                project=project,
                contract_snapshot=snapshot,
                as_of_date=month_end,
                defaults={"progress_percent": progress_percent},
            )
            target_revenue = (
                Decimal(getattr(snapshot, "base_contract_amount", 0) or 0)
                * (progress_percent / Decimal("100"))
            ).quantize(Decimal("1.00"))
            previous_revenue = (
                RevenueRecognition.objects.filter(
                    project=project,
                    contract_snapshot=snapshot,
                    as_of_date__lt=month_end,
                )
                .order_by("-as_of_date", "-id")
                .first()
            )
            previous_amount = Decimal(getattr(previous_revenue, "recognized_revenue", 0) or 0)
            RevenueRecognition.objects.filter(id=revenue.id).update(
                progress_percent=progress_percent,
                recognized_revenue=target_revenue,
                delta_revenue=(target_revenue - previous_amount),
            )
            revenue.refresh_from_db()

            approved_cost = (
                CostActual.objects.filter(
                    project=project,
                    status="approved",
                    report_date__lte=month_end,
                ).aggregate(total=models.Sum("total_amount")).get("total")
                or Decimal("0")
            )
            inflow_amount = (revenue.recognized_revenue * Decimal("0.35")).quantize(Decimal("1.00"))
            margin_percent = Decimal(target_margin) if target_margin is not None else None
            if margin_percent is not None:
                if margin_percent > Decimal("99"):
                    margin_percent = Decimal("99")
                if margin_percent < Decimal("0"):
                    margin_percent = Decimal("0")
                target_cost = (
                    revenue.recognized_revenue * (Decimal("100") - margin_percent) / Decimal("100")
                ).quantize(Decimal("1.00"))
                delta = target_cost - approved_cost
                align_line = (
                    CostActualLine.objects.filter(
                        cost_actual__project=project,
                        cost_actual__status="approved",
                        cost_actual__report_date=month_end,
                        description="D3E finance margin align",
                    )
                    .select_related("cost_actual")
                    .order_by("-id")
                    .first()
                )
                if align_line is not None:
                    new_amount = (align_line.amount or Decimal("0")) + delta
                    if new_amount < 0:
                        new_amount = Decimal("0")
                    align_line.quantity = Decimal("1.000")
                    align_line.unit_price = new_amount.quantize(Decimal("1.00"))
                    align_line.save()
                elif delta > 0:
                    align_cost = CostActual.objects.create(
                        project=project,
                        report_date=month_end,
                        status="approved",
                        approved_by=hq_user,
                        approved_at=timezone.now(),
                    )
                    CostActualLine.objects.create(
                        cost_actual=align_cost,
                        cost_item=default_cost_item,
                        description="D3E finance margin align",
                        quantity=Decimal("1.000"),
                        unit_price=delta.quantize(Decimal("1.00")),
                    )
                approved_cost = (
                    CostActual.objects.filter(
                        project=project,
                        status="approved",
                        report_date__lte=month_end,
                    ).aggregate(total=models.Sum("total_amount")).get("total")
                    or Decimal("0")
                )
            outflow_base = approved_cost if approved_cost > 0 else (inflow_amount * Decimal("0.55"))
            outflow_amount = Decimal(outflow_base).quantize(Decimal("1.00"))

            CashEvent.objects.update_or_create(
                project=project,
                contract_snapshot=snapshot,
                event_type="in",
                status="planned",
                event_date=month_end,
                description=f"D3E planned inflow {year}-{month:02d}",
                defaults={"amount": inflow_amount, "account": account, "created_by": hq_user},
            )
            CashEvent.objects.update_or_create(
                project=project,
                contract_snapshot=snapshot,
                event_type="out",
                status="planned",
                event_date=month_end,
                description=f"D3E planned outflow {year}-{month:02d}",
                defaults={"amount": outflow_amount, "account": account, "created_by": hq_user},
            )

            rows.append(
                {
                    "project_id": project.id,
                    "project_code": project.code,
                    "progress_percent": str(progress_percent),
                    "recognized_revenue": str(revenue.recognized_revenue),
                    "planned_inflow": str(inflow_amount),
                    "planned_outflow": str(outflow_amount),
                    "planned_net": str(inflow_amount - outflow_amount),
                }
            )

        return {"seeded": True, "month": f"{year}-{month:02d}", "projects": rows}

    def _pick_workdays(self, year, month, seed_value, min_days=8, max_days=12):
        days = []
        cursor = date(year, month, 1)
        while cursor.month == month:
            if cursor.weekday() < 5:
                days.append(cursor)
            cursor += timedelta(days=1)
        rng = random.Random(seed_value + year * 100 + month)
        low = max(1, min_days)
        high = min(max_days, len(days))
        count = low if low >= high else rng.randint(low, high)
        return sorted(rng.sample(days, count))

    def _attach_evidence(self, Evidence, EvidenceFile, object_type, object_id, user, file_count, prefix):
        if not (Evidence and EvidenceFile):
            return
        evidence, _ = Evidence.objects.get_or_create(
            object_type=object_type,
            object_id=object_id,
            defaults={
                "title": f"{object_type} evidence {object_id}",
                "description": "D3E3 generated evidence",
                "created_by": user,
                "status": "submitted",
            },
        )
        for idx in range(max(file_count, 0)):
            fname = f"{prefix}-{idx+1}.jpg"
            EvidenceFile.objects.create(
                evidence=evidence,
                file=ContentFile(b"img", name=fname),
                original_name=fname,
                content_type="image/jpeg",
                created_by=user,
            )

    def _upsert_approval(self, ApprovalRequest, object_type, object_id, status, submitter, approver):
        approval = ApprovalRequest.objects.filter(object_type=object_type, object_id=object_id).order_by("id").first()
        if approval is None:
            approval = ApprovalRequest(object_type=object_type, object_id=object_id)
        approval.status = status
        approval.submitted_by = submitter
        if status == "submitted":
            approval.submitted_at = timezone.now()
            approval.approved_by = None
            approval.approved_at = None
        if status == "approved":
            approval.submitted_at = approval.submitted_at or timezone.now()
            approval.approved_by = approver
            approval.approved_at = timezone.now()
        if status == "rejected":
            approval.submitted_at = approval.submitted_at or timezone.now()
        approval.save()

    def _create_approval(self, ApprovalRequest, object_type, object_id, status, submitter, approver):
        approval = ApprovalRequest(
            object_type=object_type,
            object_id=object_id,
            status=status,
            submitted_by=submitter,
            submitted_at=timezone.now(),
        )
        if status == "approved":
            approval.approved_by = approver
            approval.approved_at = timezone.now()
        approval.save()

    def _maybe_call_seed_initial(self, first_project_spec):
        try:
            importlib.import_module("apps.core.management.commands.seed_initial")
        except Exception:
            return False

        env_backup = {
            "SEED_ENABLE": os.getenv("SEED_ENABLE"),
            "SEED_PROJECT_CODE": os.getenv("SEED_PROJECT_CODE"),
            "SEED_PROJECT_NAME": os.getenv("SEED_PROJECT_NAME"),
            "SEED_CEO_USERNAME": os.getenv("SEED_CEO_USERNAME"),
            "SEED_HQ_USERNAME": os.getenv("SEED_HQ_USERNAME"),
            "SEED_FIELD_USERNAME": os.getenv("SEED_FIELD_USERNAME"),
        }
        try:
            os.environ["SEED_ENABLE"] = "true"
            os.environ["SEED_PROJECT_CODE"] = first_project_spec["code"]
            os.environ["SEED_PROJECT_NAME"] = first_project_spec["name"]
            os.environ["SEED_CEO_USERNAME"] = "ceo1"
            os.environ["SEED_HQ_USERNAME"] = "hq1"
            os.environ["SEED_FIELD_USERNAME"] = "field3"
            call_command("seed_initial", verbosity=0)
            return True
        except Exception:
            return False
        finally:
            for key, value in env_backup.items():
                if value is None:
                    os.environ.pop(key, None)
                else:
                    os.environ[key] = value

    def _ensure_users(self, user_specs, UserProfile):
        User = get_user_model()
        users = []
        for username, role in user_specs:
            user, _ = User.objects.get_or_create(username=username)
            if not user.has_usable_password():
                user.set_password("change-me")
                user.save(update_fields=["password"])
            profile, _ = UserProfile.objects.get_or_create(user=user, defaults={"role": role})
            if profile.role != role:
                profile.role = role
                profile.save(update_fields=["role"])
            users.append((username, role, user, self._ensure_static_2fa(user)))
        return users

    def _ensure_static_2fa(self, user):
        try:
            from django_otp.plugins.otp_static.models import StaticDevice, StaticToken
        except Exception:
            return False
        device, _ = StaticDevice.objects.get_or_create(user=user, name="seed-static")
        if not device.token_set.exists():
            token = str((user.id or 0) % 1000000).zfill(6)
            StaticToken.objects.create(device=device, token=token)
        return True

    def _ensure_item_master(self, UoM, ItemCategory, ItemMaster, actor):
        uom_specs = [("EA", "Each"), ("M", "Meter"), ("M2", "Square Meter"), ("M3", "Cubic Meter")]
        uoms = {}
        for code, name in uom_specs:
            uom, _ = UoM.objects.get_or_create(code=code, defaults={"name": name, "is_active": True})
            if not uom.is_active:
                uom.is_active = True
                uom.save(update_fields=["is_active", "updated_at"])
            uoms[code] = uom

        category = None
        if ItemCategory is not None:
            category, _ = ItemCategory.objects.get_or_create(
                name="Landscape",
                defaults={"code": "LS", "is_active": True},
            )
            if not category.is_active:
                category.is_active = True
                category.save(update_fields=["is_active", "updated_at"])

        item_specs = [
            ("LS-001", "Turf Grass", "M2"), ("LS-002", "Shrub", "EA"), ("LS-003", "Tree", "EA"),
            ("LS-004", "Fertilizer", "EA"), ("LS-005", "Drain Pipe", "M"), ("LS-006", "Curb Stone", "EA"),
            ("LS-007", "Permeable Block", "EA"), ("LS-008", "Wood Deck", "M2"), ("LS-009", "Bench", "EA"),
            ("LS-010", "Pergola", "EA"), ("LS-011", "Landscape Light", "EA"), ("LS-012", "CCTV", "EA"),
            ("LS-013", "Irrigation Kit", "EA"), ("LS-014", "Power Panel", "EA"), ("LS-015", "Soil Additive", "EA"),
            ("LS-016", "Geotextile", "M2"), ("LS-017", "Gravel", "M3"), ("LS-018", "Safety Fence", "M"),
            ("LS-019", "Guide Sign", "EA"), ("LS-020", "Play Facility", "EA"), ("LS-021", "Fountain Set", "EA"),
            ("LS-022", "Tree Support", "EA"),
        ]
        for code, name, uom_code in item_specs:
            item, _ = ItemMaster.objects.get_or_create(
                code=code,
                defaults={
                    "name": name,
                    "uom": uoms[uom_code],
                    "category": category,
                    "is_active": True,
                    "created_by": actor,
                    "updated_by": actor,
                },
            )
            item.name = name
            item.uom = uoms[uom_code]
            item.category = category
            item.is_active = True
            item.updated_by = actor
            item.save()
        return ItemMaster.objects.filter(code__startswith="LS-").count()

    def _ensure_cbs_items(self, CostItem, CostItemAlias):
        active_items = list(CostItem.objects.filter(is_active=True).order_by("sort_order", "id"))
        preferred = []
        for item in active_items:
            name = f"{item.name} {item.get_display_name()}".lower()
            if item.work_type in {"07", "08", "09", "10", "11", "12"} or "land" in name:
                preferred.append(item)
        selected = preferred or active_items

        created_minimal = False
        if not selected:
            created_minimal = True
            seed_specs = [
                ("CBS-LS-001", "Landscape Works", "other"), ("CBS-LS-002", "Earth Work", "material"),
                ("CBS-LS-003", "Planting", "material"), ("CBS-LS-004", "Facilities", "subcon"),
                ("CBS-LS-005", "Irrigation", "material"), ("CBS-LS-006", "Paving", "material"),
                ("CBS-LS-007", "Electrical", "equip"), ("CBS-LS-008", "Labor", "labor"),
                ("CBS-LS-009", "Transport", "subcon"), ("CBS-LS-010", "Safety Mgmt", "other"),
            ]
            for idx, (code, name, category) in enumerate(seed_specs, start=1):
                kwargs = {
                    "name": name,
                    "category": category,
                    "unit": "",
                    "is_direct": True,
                    "is_active": True,
                    "sort_order": idx,
                }
                if _has_field(CostItem, "cost_type"):
                    kwargs["cost_type"] = ""
                if _has_field(CostItem, "work_type"):
                    kwargs["work_type"] = ""
                if _has_field(CostItem, "is_locked"):
                    kwargs["is_locked"] = False
                item, _ = CostItem.objects.get_or_create(code=code, defaults=kwargs)
                selected.append(item)
                if CostItemAlias is not None:
                    CostItemAlias.objects.get_or_create(
                        cost_item=item,
                        alias=name,
                        defaults={"is_primary": True},
                    )
        selected = sorted(selected, key=lambda x: (x.sort_order, x.id))
        if len(selected) < 10:
            raise CommandError("CBS items must be at least 10 for budget seeding.")
        return selected, created_minimal

    def _ensure_labor_masters(self, LaborRole, LaborRateTable, start_date, actor):
        role_specs = [
            ("LR-FRM", "Foreman", "FOREMAN", 320000),
            ("LR-ENG", "Engineer", "ENGINEER", 280000),
            ("LR-SKL", "Skilled Worker", "SKILLED", 240000),
            ("LR-USK", "General Worker", "UNSKILLED", 180000),
            ("LR-OPR", "Equipment Operator", "OPERATOR", 260000),
            ("LR-ADM", "Site Admin", "ADMIN", 210000),
            ("LR-QLT", "Quality Lead", "ENGINEER", 250000),
        ]
        created_roles = 0
        for idx, (code, name, group, rate) in enumerate(role_specs, start=1):
            role, created = LaborRole.objects.get_or_create(
                code=code,
                defaults={
                    "name": name,
                    "role_group": group,
                    "is_active": True,
                    "sort_order": idx,
                },
            )
            if created:
                created_roles += 1
            role.name = name
            role.role_group = group
            role.is_active = True
            role.sort_order = idx
            role.save()
            LaborRateTable.objects.get_or_create(
                labor_role=role,
                scope_type="GLOBAL",
                project=None,
                effective_from=start_date,
                defaults={
                    "rate_type": "DAY",
                    "unit_rate": rate,
                    "currency": "KRW",
                    "is_active": True,
                    "created_by": actor,
                },
            )
        return {
            "role_count": LaborRole.objects.filter(code__startswith="LR-").count(),
            "rate_count": LaborRateTable.objects.filter(labor_role__code__startswith="LR-").count(),
            "created_roles": created_roles,
        }

    def _ensure_wbs_baseline(self, WBSItem, project, start_date, end_date):
        existing = WBSItem.objects.filter(project=project, baseline_version=1, is_baseline=True).exists()
        if existing:
            return False
        days_total = max((end_date - start_date).days, 1)
        task_specs = [
            ("Kickoff", 10),
            ("Demolition", 10),
            ("Groundwork", 15),
            ("Main Construction", 20),
            ("Ancillary Work", 15),
            ("Landscape and Finish", 15),
            ("Inspection and Commissioning", 10),
            ("Handover", 5),
        ]
        cursor = start_date
        for idx, (name, weight) in enumerate(task_specs, start=1):
            span = max(int(days_total * (weight / 100)), 1)
            task_end = min(end_date, cursor.fromordinal(cursor.toordinal() + span))
            WBSItem.objects.create(
                project=project,
                name=name,
                weight=Decimal(str(weight)),
                sort_order=idx,
                plan_start_date=cursor,
                plan_end_date=task_end,
                baseline_version=1,
                is_baseline=True,
            )
            cursor = task_end
        return True

    def _ensure_budget(self, BudgetItem, project, cbs_items, contract_amount):
        target_items = cbs_items[: min(max(10, len(cbs_items)), 20)]
        line_count = len(target_items)
        if line_count == 0:
            return 0

        total_budget = int((Decimal(contract_amount) * Decimal("0.82")).quantize(Decimal("1")))
        per_line = max(total_budget // line_count, 1)

        for idx, cost_item in enumerate(target_items, start=1):
            planned_amount = per_line + (idx % 4) * 1000000
            category_map = {
                "labor": "LABOR",
                "material": "MATERIAL",
                "equip": "EQUIP",
                "subcon": "SUBCON",
                "other": "OTHER",
            }
            budget, _ = BudgetItem.objects.get_or_create(
                project=project,
                cost_item=cost_item,
                defaults={
                    "category": category_map.get(cost_item.category, "OTHER"),
                    "name": cost_item.get_display_name(),
                    "planned_amount": planned_amount,
                    "status": "approved",
                    "note": "D3E-2 baseline budget",
                },
            )
            budget.category = category_map.get(cost_item.category, "OTHER")
            budget.name = cost_item.get_display_name()
            budget.planned_amount = planned_amount
            budget.status = "approved"
            budget.note = "D3E-2 baseline budget"
            budget.save()

        return BudgetItem.objects.filter(project=project).count()


def _safe_get_model(app_label, model_name):
    try:
        return apps.get_model(app_label, model_name)
    except Exception:
        return None


def _label(model):
    return f"{model._meta.app_label}.{model.__name__}" if model else None


def _get_field(model, field_name):
    try:
        return model._meta.get_field(field_name)
    except Exception:
        return None


def _first_existing_field(model, candidates):
    for name in candidates:
        if _get_field(model, name) is not None:
            return name
    return None


def _resolve_status_values(status_field, default_map):
    out = dict(default_map)
    if status_field is None:
        return out
    choices = list(getattr(status_field, "choices", []) or [])
    if not choices:
        return out
    normalized = []
    for row in choices:
        if isinstance(row, (list, tuple)) and len(row) >= 2:
            normalized.append((row[0], row[1]))
    for key in out:
        target = key.upper()
        matched = None
        for value, label in normalized:
            if str(value).upper() == target:
                matched = value
                break
            if str(label).upper() == target:
                matched = value
                break
        out[key] = matched
    return out


def _required_create_fields(model, attach_mode=False):
    required = []
    for field in model._meta.get_fields():
        if not isinstance(field, models.Field):
            continue
        if not getattr(field, "concrete", False):
            continue
        if getattr(field, "auto_created", False):
            continue
        if getattr(field, "primary_key", False):
            continue
        if getattr(field, "many_to_many", False):
            continue
        if getattr(field, "auto_now", False) or getattr(field, "auto_now_add", False):
            continue
        if getattr(field, "null", False):
            continue
        if field.has_default():
            continue
        required.append(field.name)

    if attach_mode:
        # These are often filled in model.save() for file attachments.
        required = [name for name in required if name not in {"size_bytes", "sha256"}]
    return required


def _discover_functions(module_path, names):
    out = {}
    try:
        module = importlib.import_module(module_path)
    except Exception as exc:
        return {"module": module_path, "import_error": str(exc)}
    for name in names:
        out[name] = bool(getattr(module, name, None))
    return {"module": module_path, "functions": out}


def _has_field(model, field_name):
    try:
        model._meta.get_field(field_name)
        return True
    except Exception:
        return False






