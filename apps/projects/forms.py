from django import forms
from django.contrib.auth import get_user_model

from apps.cost.models import CostItem

from apps.core.rbac.models import ProjectAssignment, ProjectRole

from .models import (
    BudgetCategory,
    BudgetItem,
    Project,
    ProjectContract,
    ProjectStatus,
    WBSItem,
)


class ProjectOnboardingForm(forms.ModelForm):
    class Meta:
        model = Project
        fields = ["name", "start_date", "end_date", "status"]
        widgets = {
            "start_date": forms.DateInput(attrs={"type": "date"}),
            "end_date": forms.DateInput(attrs={"type": "date"}),
        }

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.fields["status"].choices = [
            (ProjectStatus.DRAFT, "DRAFT"),
            (ProjectStatus.SUBMITTED, "SUBMITTED"),
            (ProjectStatus.APPROVED, "APPROVED"),
        ]


class ProjectContractForm(forms.ModelForm):
    class Meta:
        model = ProjectContract
        fields = ["contract_amount", "contract_file", "contract_start_date", "contract_end_date", "memo"]
        widgets = {
            "contract_start_date": forms.DateInput(attrs={"type": "date"}),
            "contract_end_date": forms.DateInput(attrs={"type": "date"}),
        }


class ProjectAssignmentForm(forms.ModelForm):
    class Meta:
        model = ProjectAssignment
        fields = ["user", "role_in_project", "is_active"]

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        User = get_user_model()
        self.fields["user"].queryset = User.objects.filter(
            profile__role__in=[ProjectRole.FIELD, ProjectRole.HQ]
        ).order_by("username")
        for field in self.fields.values():
            field.widget.attrs.setdefault("class", "form-control")


class BudgetItemForm(forms.ModelForm):
    class Meta:
        model = BudgetItem
        fields = ["category", "cost_item", "name", "planned_amount", "notes"]

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.fields["planned_amount"].widget.attrs.setdefault("step", "0.01")
        self.fields["cost_item"].queryset = CostItem.objects.filter(is_active=True).order_by(
            "sort_order", "name"
        )
        for field in self.fields.values():
            field.widget.attrs.setdefault("class", "form-control")

    def clean(self):
        cleaned = super().clean()
        cost_item = cleaned.get("cost_item")
        name = cleaned.get("name")
        if cost_item and not name:
            cleaned["name"] = cost_item.name
        return cleaned


class LaborBudgetItemForm(BudgetItemForm):
    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.fields["category"].initial = BudgetCategory.LABOR
        self.fields["category"].widget = forms.HiddenInput()

    def clean(self):
        cleaned = super().clean()
        cleaned["category"] = BudgetCategory.LABOR
        return cleaned


class WBSItemForm(forms.ModelForm):
    class Meta:
        model = WBSItem
        fields = [
            "name",
            "parent",
            "weight",
            "sort_order",
            "plan_start_date",
            "plan_end_date",
        ]
        widgets = {
            "plan_start_date": forms.DateInput(attrs={"type": "date"}),
            "plan_end_date": forms.DateInput(attrs={"type": "date"}),
        }

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        for field in self.fields.values():
            field.widget.attrs.setdefault("class", "form-control")
