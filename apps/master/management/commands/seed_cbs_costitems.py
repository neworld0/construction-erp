import csv
import re
from pathlib import Path

from django.apps import apps
from django.core.management.base import BaseCommand, CommandError
from django.db import models, transaction


CODE_PATTERN = re.compile(r"^CB-[MLESOGP]-\d{2}-\d{3}$")
ALLOWED_COST_TYPES = {"M", "L", "E", "S", "O", "G", "P"}


class Command(BaseCommand):
    help = "Seed CBS CostItems from CSV with safe field mapping."

    def add_arguments(self, parser):
        parser.add_argument(
            "--csv",
            default="data/master/cbs_costitems_v1.csv",
            help="CSV path (default: data/master/cbs_costitems_v1.csv)",
        )
        parser.add_argument("--dry-run", action="store_true", help="Validate only.")
        parser.add_argument(
            "--no-strict",
            dest="strict",
            action="store_false",
            help="Continue on validation errors.",
        )
        parser.set_defaults(strict=True)

    def handle(self, *args, **options):
        csv_path = Path(options["csv"])
        dry_run = options["dry_run"]
        strict = options["strict"]

        if not csv_path.exists():
            raise CommandError(f"CSV not found: {csv_path}")

        model = _get_costitem_model()
        field_map = _resolve_field_map(model)
        self.stdout.write(
            "Mapping: code->{code}, name->{name}, cost_type->{cost_type}, "
            "work_type->{work_type}, active->{active}".format(**field_map)
        )

        rows = _load_csv(csv_path, strict, self)
        if not rows:
            self.stdout.write("No rows loaded.")
            return

        code_field = field_map["code"]
        existing = model.objects.in_bulk(
            [row["code"] for row in rows], field_name=code_field
        )

        created = []
        updated = []
        unchanged = 0
        skipped = 0

        update_fields = [
            field_map["name"],
            field_map["cost_type"],
            field_map["work_type"],
        ]
        active_field = field_map.get("active")
        work_type_field = model._meta.get_field(field_map["work_type"])

        for row in rows:
            code = row["code"]
            existing_obj = existing.get(code)
            work_type_value = _coerce_work_type(row["work_type"], work_type_field)
            if existing_obj is None:
                attrs = {
                    field_map["code"]: code,
                    field_map["name"]: row["name"],
                    field_map["cost_type"]: row["cost_type"],
                    field_map["work_type"]: work_type_value,
                }
                if active_field:
                    attrs[active_field] = True
                created.append(model(**attrs))
                continue

            changed = False
            if getattr(existing_obj, field_map["name"]) != row["name"]:
                setattr(existing_obj, field_map["name"], row["name"])
                changed = True
            if getattr(existing_obj, field_map["cost_type"]) != row["cost_type"]:
                setattr(existing_obj, field_map["cost_type"], row["cost_type"])
                changed = True
            if getattr(existing_obj, field_map["work_type"]) != work_type_value:
                setattr(existing_obj, field_map["work_type"], work_type_value)
                changed = True

            if changed:
                updated.append(existing_obj)
            else:
                unchanged += 1

        if dry_run:
            self.stdout.write(
                f"created={len(created)}, updated={len(updated)}, unchanged={unchanged}, skipped={skipped}"
            )
            return

        with transaction.atomic():
            if created:
                model.objects.bulk_create(created, batch_size=500)
            if updated:
                model.objects.bulk_update(updated, update_fields, batch_size=500)

        self.stdout.write(
            f"created={len(created)}, updated={len(updated)}, unchanged={unchanged}, skipped={skipped}"
        )
        self.stdout.write("Verify:")
        self.stdout.write(
            "  python manage.py seed_cbs_costitems --csv data/master/cbs_costitems_v1.csv --dry-run"
        )
        self.stdout.write(
            "  python manage.py seed_cbs_costitems --csv data/master/cbs_costitems_v1.csv"
        )
        self.stdout.write("  python manage.py shell")
        self.stdout.write(
            '    from django.apps import apps\n'
            '    CostItem = [m for m in apps.get_models() if m.__name__=="CostItem"][0]\n'
            "    CostItem.objects.count()\n"
            f'    CostItem.objects.filter(**{{"{code_field}":"CB-M-07-001"}}).values().first()'
        )


def _get_costitem_model():
    try:
        from apps.master.models import CostItem as MasterCostItem  # noqa: F401

        return MasterCostItem
    except Exception:
        pass

    for model in apps.get_models():
        if model.__name__ == "CostItem":
            return model

    raise CommandError("CostItem model not found. Please create CostItem model first.")


def _resolve_field_map(model):
    fields = {field.name: field for field in model._meta.get_fields() if hasattr(field, "attname")}

    code_field = _pick_field(fields, ["code", "item_code", "cost_code", "cbs_code"], required=True)
    if not getattr(fields[code_field], "unique", False):
        raise CommandError("code field must be unique")

    name_field = _pick_field(fields, ["name", "title", "label", "display_name"], required=True)
    cost_type_field = _pick_field(
        fields, ["cost_type", "ctype", "type", "category", "cost_category"], required=True
    )
    work_type_field = _pick_field(
        fields, ["work_type", "work_code", "work_kind", "trade_code"], required=True
    )

    active_field = _pick_field(fields, ["active", "is_active", "enabled"], required=False)
    sort_field = _pick_field(fields, ["sort_order", "order", "seq"], required=False)

    return {
        "code": code_field,
        "name": name_field,
        "cost_type": cost_type_field,
        "work_type": work_type_field,
        "active": active_field,
        "sort_order": sort_field,
    }


def _pick_field(fields, candidates, required):
    for name in candidates:
        if name in fields:
            return name
    if required:
        field_list = ", ".join(sorted(fields.keys()))
        raise CommandError(
            f"Required field not found for candidates {candidates}. "
            f"Model fields: {field_list}"
        )
    return None


def _load_csv(csv_path, strict, command):
    rows = []
    seen_codes = set()
    errors = 0

    with csv_path.open("r", encoding="utf-8", newline="") as handle:
        reader = csv.DictReader(handle)
        if reader.fieldnames is None:
            raise CommandError("CSV header is required.")

        required = {"code", "name", "cost_type", "work_type"}
        if set(reader.fieldnames) < required:
            raise CommandError(f"CSV header must include {sorted(required)}.")

        for index, raw in enumerate(reader, start=2):
            row = {k: (v or "").strip() for k, v in raw.items()}
            code = row.get("code", "")
            if not code:
                errors = _handle_error(
                    command, strict, errors, f"Row {index}: code is required."
                )
                continue
            if code in seen_codes:
                errors = _handle_error(
                    command, strict, errors, f"Row {index}: duplicate code {code}."
                )
                continue
            if not CODE_PATTERN.match(code):
                errors = _handle_error(
                    command,
                    strict,
                    errors,
                    f"Row {index}: invalid code format {code}.",
                )
                continue

            cost_type = row.get("cost_type", "").upper()
            if cost_type not in ALLOWED_COST_TYPES:
                errors = _handle_error(
                    command,
                    strict,
                    errors,
                    f"Row {index}: invalid cost_type {cost_type}.",
                )
                continue

            work_type = row.get("work_type", "")
            if not work_type.isdigit() or len(work_type) != 2:
                errors = _handle_error(
                    command,
                    strict,
                    errors,
                    f"Row {index}: invalid work_type {work_type}.",
                )
                continue

            name = row.get("name", "")
            if not name:
                errors = _handle_error(
                    command, strict, errors, f"Row {index}: name is required."
                )
                continue

            seen_codes.add(code)
            rows.append(
                {
                    "code": code,
                    "name": name,
                    "cost_type": cost_type,
                    "work_type": work_type,
                }
            )

    if strict and errors:
        raise CommandError(f"Validation failed with {errors} error(s).")
    return rows


def _handle_error(command, strict, errors, message):
    if strict:
        raise CommandError(message)
    command.stdout.write(f"Skip: {message}")
    return errors + 1


def _coerce_work_type(value, field):
    if isinstance(field, models.IntegerField):
        return int(value)
    return value
