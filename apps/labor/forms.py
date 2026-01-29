from django import forms

from apps.cost.models import CostItem
from apps.projects.models import Project

from .models import (
    LaborRateScope,
    LaborRateTable,
    LaborRateType,
    LaborRole,
    PayrollAllocationBatch,
)


class LaborRoleForm(forms.ModelForm):
    class Meta:
        model = LaborRole
        fields = [
            "code",
            "name",
            "role_group",
            "sort_order",
            "default_cbs",
            "is_active",
        ]

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.fields["default_cbs"].queryset = CostItem.objects.order_by("code")
        for field in self.fields.values():
            field.widget.attrs.setdefault("class", "input")


class LaborRateForm(forms.ModelForm):
    scope_type = forms.ChoiceField(choices=LaborRateScope.choices)
    rate_type = forms.ChoiceField(choices=LaborRateType.choices)

    class Meta:
        model = LaborRateTable
        fields = [
            "labor_role",
            "rate_type",
            "unit_rate",
            "currency",
            "effective_from",
            "effective_to",
            "scope_type",
            "project",
            "is_active",
            "note",
        ]

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.fields["project"].queryset = Project.objects.order_by("name")
        self.fields["currency"].required = False
        for field in self.fields.values():
            field.widget.attrs.setdefault("class", "input")

    def clean(self):
        cleaned = super().clean()
        scope_type = cleaned.get("scope_type")
        project = cleaned.get("project")
        if scope_type == LaborRateScope.PROJECT and not project:
            self.add_error(
                "project",
                "\u003cPROJECT\u003e \ub2e8\uac00\ub294 \ud504\ub85c\uc81d\ud2b8\uac00 \ud544\uc694\ud569\ub2c8\ub2e4.",
            )
        if scope_type == LaborRateScope.GLOBAL and project:
            self.add_error(
                "project",
                "\u003cGLOBAL\u003e \ub2e8\uac00\ub294 \ud504\ub85c\uc81d\ud2b8\uac00 \uc5c6\uc5b4\uc57c \ud569\ub2c8\ub2e4.",
            )
        return cleaned


class PayrollBatchForm(forms.ModelForm):
    class Meta:
        model = PayrollAllocationBatch
        fields = ["period_year", "period_month", "total_amount", "note"]

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        for field in self.fields.values():
            field.widget.attrs.setdefault("class", "input")
