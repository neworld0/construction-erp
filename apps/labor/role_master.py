"""Canonical LaborRole seed data used by HQ worker registration."""

from django.db import transaction

from .models import LaborRole, LaborRoleGroup


LOCAL_OPS_LABOR_ROLE_SPECS = (
    ("LAB-GEN", "보통인부", LaborRoleGroup.UNSKILLED, 10),
    ("LAB-PAV", "포장공", LaborRoleGroup.SKILLED, 20),
    ("LAB-EQP", "장비공", LaborRoleGroup.OPERATOR, 30),
    ("LAB-CMP", "다짐공", LaborRoleGroup.SKILLED, 40),
    ("LAB-PNT", "도색공", LaborRoleGroup.SKILLED, 50),
)


def seed_local_ops_labor_roles():
    """Create or align the stable role codes required for LOCAL-OPS safely."""
    results = {"created": [], "updated": [], "unchanged": []}
    with transaction.atomic():
        for code, name, role_group, sort_order in LOCAL_OPS_LABOR_ROLE_SPECS:
            defaults = {
                "name": name,
                "role_group": role_group,
                "is_active": True,
                "sort_order": sort_order,
            }
            role, created = LaborRole.objects.get_or_create(code=code, defaults=defaults)
            if created:
                results["created"].append(role)
                continue

            changed_fields = [
                field for field, value in defaults.items() if getattr(role, field) != value
            ]
            if changed_fields:
                for field in changed_fields:
                    setattr(role, field, defaults[field])
                role.save(update_fields=[*changed_fields, "updated_at"])
                results["updated"].append(role)
            else:
                results["unchanged"].append(role)
    return results
