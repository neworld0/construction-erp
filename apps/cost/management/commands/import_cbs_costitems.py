import csv
from dataclasses import dataclass
from pathlib import Path

from django.core.management.base import BaseCommand, CommandError
from django.db import transaction

from apps.cost.models import CostItem, CostItemCategory
from apps.master.models import CBSChangeRequest, CBSChangeRequestStatus
from apps.master.web_views import _is_costitem_locked


ENCODING_CANDIDATES = ("utf-8-sig", "utf-8", "cp949")
FIELD_CANDIDATES = {
    "code": ("code", "코드", "CBS코드", "cbs_code", "cost_code"),
    "name": ("name", "항목명", "명칭", "CBS명", "cbs_name", "cost_name"),
    "category": ("category", "구분", "예산구분", "비용구분"),
    "cost_type": ("cost_type", "원가유형", "비용유형"),
    "work_type": ("work_type", "공종", "공종구분"),
    "is_active": ("is_active", "active", "사용여부", "활성"),
    "is_direct": ("is_direct", "직접비여부", "직접비"),
    "sort_order": ("sort_order", "정렬", "순서"),
    "parent": ("parent", "parent_code", "상위코드", "상위CBS코드"),
    "note": ("description", "note", "비고", "설명"),
}
TRUE_VALUES = {"y", "yes", "1", "true", "사용", "활성"}
FALSE_VALUES = {"n", "no", "0", "false", "미사용", "비활성"}
ALLOWED_COST_TYPES = {"M", "L", "E", "S", "O", "G", "P", "I", "D"}
CATEGORY_BY_COST_TYPE = {
    "M": CostItemCategory.MATERIAL,
    "L": CostItemCategory.LABOR,
    "S": CostItemCategory.SUBCON,
    "E": CostItemCategory.OTHER,
    "O": CostItemCategory.OTHER,
    "G": CostItemCategory.OTHER,
    "P": CostItemCategory.OTHER,
    "I": CostItemCategory.OTHER,
    "D": CostItemCategory.OTHER,
}
CATEGORY_VALUE_MAP = {
    "material": CostItemCategory.MATERIAL,
    "재료": CostItemCategory.MATERIAL,
    "재료비": CostItemCategory.MATERIAL,
    "labor": CostItemCategory.LABOR,
    "노무": CostItemCategory.LABOR,
    "노무비": CostItemCategory.LABOR,
    "subcon": CostItemCategory.SUBCON,
    "하도급": CostItemCategory.SUBCON,
    "equip": CostItemCategory.OTHER,
    "장비": CostItemCategory.OTHER,
    "장비비": CostItemCategory.OTHER,
    "other": CostItemCategory.OTHER,
    "overhead": CostItemCategory.OTHER,
    "경비": CostItemCategory.OTHER,
    "일반관리비": CostItemCategory.OTHER,
    "이윤": CostItemCategory.OTHER,
}


@dataclass
class RowOutcome:
    created: int = 0
    updated: int = 0
    skipped: int = 0
    errors: int = 0
    locked_skipped: int = 0


class Command(BaseCommand):
    help = "Import CBS CostItems from CSV into CostItem with safe upsert behavior."

    def add_arguments(self, parser):
        parser.add_argument(
            "--path",
            default="data/master/cbs_costitems_v1.csv",
            help="CSV path (default: data/master/cbs_costitems_v1.csv)",
        )
        parser.add_argument("--dry-run", action="store_true", help="Validate only without saving.")
        parser.add_argument(
            "--update-existing",
            action="store_true",
            help="Update existing CostItem rows when safe.",
        )
        parser.add_argument(
            "--encoding",
            default="utf-8-sig",
            help="Preferred CSV encoding. Fallback order still applies.",
        )

    def handle(self, *args, **options):
        csv_path = Path(options["path"])
        if not csv_path.is_absolute():
            csv_path = Path.cwd() / csv_path
        if not csv_path.exists():
            raise CommandError(f"CSV not found: {csv_path}")

        preferred_encoding = (options.get("encoding") or "utf-8-sig").strip().lower()
        encodings = [preferred_encoding] + [enc for enc in ENCODING_CANDIDATES if enc != preferred_encoding]

        rows, detected_headers, encoding = self._load_rows(csv_path, encodings)
        header_map = self._resolve_header_map(detected_headers)
        missing = [field for field in ("code", "name") if field not in header_map]
        if missing:
            raise CommandError(f"필수 헤더가 누락되었습니다: {', '.join(missing)}")

        self.stdout.write(f"CSV path: {csv_path}")
        self.stdout.write(f"encoding: {encoding}")
        self.stdout.write(f"detected headers: {', '.join(detected_headers)}")
        self.stdout.write(f"total rows: {len(rows)}")

        model_fields = {field.name for field in CostItem._meta.get_fields() if hasattr(field, "attname")}
        supports_parent = "parent" in model_fields and "parent" in header_map

        outcome = RowOutcome()
        warnings = []
        sample_names = []
        pending_parents = []
        seen_codes = set()

        def apply_import():
            local_existing = {item.code: item for item in CostItem.objects.all()}
            for index, raw in enumerate(rows, start=2):
                try:
                    payload = self._normalize_row(raw, header_map, model_fields)
                except ValueError as exc:
                    outcome.errors += 1
                    if len(warnings) < 20:
                        warnings.append(f"row {index}: {exc}")
                    continue

                code = payload["code"]
                if code in seen_codes:
                    outcome.errors += 1
                    if len(warnings) < 20:
                        warnings.append(f"row {index}: duplicate code {code}")
                    continue
                seen_codes.add(code)
                if len(sample_names) < 3:
                    sample_names.append(payload["name"])

                existing = local_existing.get(code)
                if existing is None:
                    if options["dry_run"]:
                        outcome.created += 1
                        local_existing[code] = CostItem(code=code, name=payload["name"])
                    else:
                        item = CostItem.objects.create(**payload["fields"])
                        outcome.created += 1
                        local_existing[code] = item
                    if supports_parent and payload["parent_code"]:
                        pending_parents.append((code, payload["parent_code"], index))
                    continue

                if not options["update_existing"]:
                    outcome.skipped += 1
                    continue

                if self._has_pending_change(existing):
                    outcome.locked_skipped += 1
                    outcome.skipped += 1
                    if len(warnings) < 20:
                        warnings.append(f"row {index}: skip locked/pending {code} (pending change)")
                    continue
                locked, reasons, _stats = _is_costitem_locked(existing, CostItem)
                if locked:
                    outcome.locked_skipped += 1
                    outcome.skipped += 1
                    if len(warnings) < 20:
                        reason_text = "; ".join(reasons) if reasons else "locked"
                        warnings.append(f"row {index}: skip locked/pending {code} ({reason_text})")
                    continue

                changed_fields = []
                for field_name, new_value in payload["fields"].items():
                    if field_name == "code":
                        continue
                    if getattr(existing, field_name) != new_value:
                        setattr(existing, field_name, new_value)
                        changed_fields.append(field_name)
                if changed_fields:
                    if options["dry_run"]:
                        outcome.updated += 1
                    else:
                        existing.save(update_fields=changed_fields + ["updated_at"])
                        outcome.updated += 1
                else:
                    outcome.skipped += 1

            if supports_parent:
                self._apply_parents(local_existing, pending_parents, outcome, warnings, options["dry_run"])

        if options["dry_run"]:
            apply_import()
        else:
            with transaction.atomic():
                apply_import()

        self.stdout.write(f"created count: {outcome.created}")
        self.stdout.write(f"updated count: {outcome.updated}")
        self.stdout.write(f"skipped count: {outcome.skipped}")
        self.stdout.write(f"error count: {outcome.errors}")
        self.stdout.write(f"locked skipped count: {outcome.locked_skipped}")
        self.stdout.write(f"sample names: {', '.join(sample_names[:3])}")
        if warnings:
            self.stdout.write("first warnings/errors:")
            for message in warnings[:20]:
                self.stdout.write(f"- {message}")
        if not warnings:
            self.stdout.write("first warnings/errors: none")
        self.stdout.write("AuditLog: skipped (no actor in management command).")

    def _load_rows(self, csv_path, encodings):
        last_error = None
        for encoding in encodings:
            try:
                with csv_path.open("r", encoding=encoding, newline="") as handle:
                    reader = csv.DictReader(handle)
                    if reader.fieldnames is None:
                        raise CommandError("CSV header is required.")
                    headers = [str(name or "").strip() for name in reader.fieldnames]
                    rows = [{str(k or "").strip(): str(v or "").strip() for k, v in row.items()} for row in reader]
                    if any("\ufffd" in ",".join(row.values()) for row in rows[:5]):
                        raise UnicodeError("replacement character detected")
                    return rows, headers, encoding
            except UnicodeDecodeError as exc:
                last_error = exc
                continue
            except UnicodeError as exc:
                last_error = exc
                continue
        raise CommandError(f"CSV 디코딩에 실패했습니다. tried={encodings} last_error={last_error}")

    def _resolve_header_map(self, headers):
        normalized = {self._normalize_header(name): name for name in headers}
        resolved = {}
        for field_name, candidates in FIELD_CANDIDATES.items():
            for candidate in candidates:
                original = normalized.get(self._normalize_header(candidate))
                if original:
                    resolved[field_name] = original
                    break
        return resolved

    def _normalize_header(self, value):
        return "".join(str(value or "").strip().lower().replace("_", "").split())

    def _normalize_row(self, raw, header_map, model_fields):
        code = str(raw.get(header_map["code"], "") or "").strip().upper()
        name = str(raw.get(header_map["name"], "") or "").strip()
        if not code:
            raise ValueError("code is required")
        if not name:
            raise ValueError(f"{code}: name is required")

        cost_type = str(raw.get(header_map.get("cost_type", ""), "") or "").strip().upper()
        if cost_type and cost_type not in ALLOWED_COST_TYPES:
            raise ValueError(f"{code}: invalid cost_type {cost_type}")

        category = self._normalize_category(
            raw.get(header_map.get("category", ""), "") if header_map.get("category") else "",
            cost_type,
        )
        if not category:
            raise ValueError(f"{code}: category could not be resolved")

        work_type_raw = str(raw.get(header_map.get("work_type", ""), "") or "").strip()
        if work_type_raw and (not work_type_raw.isdigit() or len(work_type_raw) != 2):
            raise ValueError(f"{code}: invalid work_type {work_type_raw}")

        fields = {
            "code": code,
            "name": name,
            "category": category,
            "cost_type": cost_type,
            "work_type": work_type_raw,
        }
        if "is_active" in model_fields:
            fields["is_active"] = self._normalize_bool(
                raw.get(header_map.get("is_active", ""), "") if header_map.get("is_active") else "",
                default=True,
            )
        if "is_direct" in model_fields:
            fields["is_direct"] = self._normalize_bool(
                raw.get(header_map.get("is_direct", ""), "") if header_map.get("is_direct") else "",
                default=cost_type not in {"O", "G", "P"},
            )
        if "sort_order" in model_fields:
            sort_value = raw.get(header_map.get("sort_order", ""), "") if header_map.get("sort_order") else ""
            fields["sort_order"] = self._normalize_int(sort_value, default=0)
        if "unit" in model_fields and "unit" in header_map:
            fields["unit"] = str(raw.get(header_map["unit"], "") or "").strip()

        parent_code = ""
        if header_map.get("parent"):
            parent_code = str(raw.get(header_map["parent"], "") or "").strip().upper()
        return {"code": code, "name": name, "fields": fields, "parent_code": parent_code}

    def _normalize_category(self, raw_value, cost_type):
        value = str(raw_value or "").strip().lower()
        normalized_value = "".join(value.split())
        if normalized_value:
            if normalized_value in CATEGORY_VALUE_MAP:
                return CATEGORY_VALUE_MAP[normalized_value]
        return CATEGORY_BY_COST_TYPE.get(cost_type or "", "")

    def _normalize_bool(self, raw_value, *, default):
        text = str(raw_value or "").strip().lower()
        if not text:
            return default
        if text in TRUE_VALUES:
            return True
        if text in FALSE_VALUES:
            return False
        return default

    def _normalize_int(self, raw_value, *, default):
        text = str(raw_value or "").strip().replace(",", "")
        if not text:
            return default
        try:
            return int(text)
        except (TypeError, ValueError):
            return default

    def _apply_parents(self, existing_by_code, pending_parents, outcome, warnings, dry_run):
        for code, parent_code, index in pending_parents:
            if not parent_code:
                continue
            item = existing_by_code.get(code)
            parent = existing_by_code.get(parent_code)
            if item is None or parent is None:
                outcome.errors += 1
                if len(warnings) < 20:
                    warnings.append(f"row {index}: parent not found for {code} -> {parent_code}")
                continue
            if getattr(item, "parent_id", None) == parent.id:
                continue
            if dry_run:
                continue
            item.parent = parent
            item.save(update_fields=["parent", "updated_at"])

    def _has_pending_change(self, cost_item):
        return CBSChangeRequest.objects.filter(
            cost_item=cost_item,
            status=CBSChangeRequestStatus.SUBMITTED,
        ).exists()
