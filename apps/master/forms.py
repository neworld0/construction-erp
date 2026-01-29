from django import forms

from apps.cost.models import CostItem
from .models import (
    MasterBudgetTemplateItem,
    MasterTemplate,
    MasterTemplateCategory,
    MasterWBSTemplateItem,
)


class MasterTemplateForm(forms.ModelForm):
    class Meta:
        model = MasterTemplate
        fields = ["name", "category", "domain", "version", "is_active", "note"]

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        for field in self.fields.values():
            field.widget.attrs.setdefault("class", "form-control")


class MasterWBSTemplateItemForm(forms.ModelForm):
    class Meta:
        model = MasterWBSTemplateItem
        fields = [
            "order",
            "task_name",
            "weight",
            "default_offset_start_days",
            "default_duration_days",
        ]

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        for field in self.fields.values():
            field.widget.attrs.setdefault("class", "form-control")


class MasterBudgetTemplateItemForm(forms.ModelForm):
    class Meta:
        model = MasterBudgetTemplateItem
        fields = [
            "order",
            "cost_item",
            "label",
            "is_labor",
            "default_amount",
        ]

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.fields["cost_item"].queryset = CostItem.objects.all().order_by(
            "sort_order", "name"
        )
        self.fields["cost_item"].required = False
        self.fields["label"].required = True
        for field in self.fields.values():
            field.widget.attrs.setdefault("class", "form-control")
        self.fields["is_labor"].widget.attrs.setdefault("class", "")
