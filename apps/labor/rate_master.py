"""Canonical HQ-owned LaborRole rates for the LOCAL-OPS rehearsal."""

from datetime import date

from django.db import transaction
from django.db.models import Q

from .models import LaborRateScope, LaborRateTable, LaborRateType, LaborRole
from .role_master import LOCAL_OPS_LABOR_ROLE_SPECS, seed_local_ops_labor_roles


LOCAL_OPS_RATE_EFFECTIVE_FROM = date(2026, 8, 1)
LOCAL_OPS_LABOR_RATE_SPECS = (
    ("LAB-GEN", 160000),
    ("LAB-PAV", 210000),
    ("LAB-EQP", 250000),
    ("LAB-CMP", 220000),
    ("LAB-PNT", 200000),
)


def seed_local_ops_labor_rates():
    """Create or align standard global daily rates without duplicates.

    Older LOCAL-OPS data can use a legacy code for the same Korean role name.
    Seed that active equivalent role as well so existing WorkerMaster assignments
    resolve a rate without changing their role foreign keys.
    """
    role_result = seed_local_ops_labor_roles()
    results = {"created": [], "updated": [], "unchanged": [], "roles": role_result}
    role_name_by_code = {
        code: name for code, name, _role_group, _sort_order in LOCAL_OPS_LABOR_ROLE_SPECS
    }
    with transaction.atomic():
        for role_code, unit_rate in LOCAL_OPS_LABOR_RATE_SPECS:
            roles = LaborRole.objects.filter(
                Q(code=role_code) | Q(name=role_name_by_code[role_code]),
                is_active=True,
            ).order_by("code", "id")
            for role in roles:
                lookup = {
                    "labor_role": role,
                    "rate_type": LaborRateType.DAY,
                    "scope_type": LaborRateScope.GLOBAL,
                    "project": None,
                    "worker": None,
                    "effective_from": LOCAL_OPS_RATE_EFFECTIVE_FROM,
                }
                defaults = {
                    "unit_rate": unit_rate,
                    "currency": "KRW",
                    "effective_to": None,
                    "is_active": True,
                    "note": "LOCAL-OPS 기본 일단가",
                }
                rate, created = LaborRateTable.objects.get_or_create(
                    **lookup, defaults=defaults
                )
                if created:
                    results["created"].append(rate)
                    continue

                changed_fields = [
                    field for field, value in defaults.items() if getattr(rate, field) != value
                ]
                if changed_fields:
                    for field in changed_fields:
                        setattr(rate, field, defaults[field])
                    rate.save(update_fields=[*changed_fields, "updated_at"])
                    results["updated"].append(rate)
                else:
                    results["unchanged"].append(rate)
    return results
