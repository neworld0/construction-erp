import re

from django import forms
from django.contrib.auth import get_user_model

from apps.cost.models import CostItem

from apps.core.rbac.models import ProjectAssignment, Role

from .models import (
    BudgetCategory,
    BudgetItem,
    ApprovalPackage,
    Project,
    ProjectContract,
    ProjectStatus,
    ProjectType,
    WBSChangeLine,
    WBSChangeRequest,
    WBSChangeRequestType,
    WBSItem,
)


class ProjectOnboardingForm(forms.ModelForm):
    class Meta:
        model = Project
        fields = ["name", "start_date", "end_date", "status", "client_name", "site_address", "project_type"]
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
        self.fields["project_type"].choices = [
            (ProjectType.LANDSCAPE, "조경"),
            (ProjectType.CIVIL, "토목"),
            (ProjectType.ARCH, "건축"),
        ]
        for field in self.fields.values():
            field.widget.attrs.setdefault("class", "form-control")


class ProjectContractForm(forms.ModelForm):
    contract_amount = forms.CharField(
        required=True,
        widget=forms.TextInput(attrs={"inputmode": "numeric"}),
    )

    class Meta:
        model = ProjectContract
        fields = ["contract_amount", "contract_file", "contract_start_date", "contract_end_date", "memo"]
        widgets = {
            "contract_start_date": forms.DateInput(attrs={"type": "date"}),
            "contract_end_date": forms.DateInput(attrs={"type": "date"}),
        }

    def clean_contract_amount(self):
        raw = self.cleaned_data.get("contract_amount")
        if raw in (None, ""):
            return None
        if isinstance(raw, str):
            raw = re.sub(r"[^0-9]", "", raw)
            if raw == "":
                raise forms.ValidationError("숫자를 입력하세요.")
        try:
            value = int(raw)
        except (TypeError, ValueError):
            raise forms.ValidationError("숫자를 입력하세요.")
        if value < 0:
            raise forms.ValidationError("계약 금액은 0 이상이어야 합니다.")
        return value

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        for field in self.fields.values():
            field.widget.attrs.setdefault("class", "form-control")

    def clean_contract_file(self):
        file_obj = self.cleaned_data.get("contract_file")
        if not file_obj:
            raise forms.ValidationError("계약서 파일은 필수입니다.")
        return file_obj


class ProjectAssignmentForm(forms.ModelForm):
    class Meta:
        model = ProjectAssignment
        fields = ["user", "is_active"]

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        User = get_user_model()
        self.fields["user"].queryset = User.objects.filter(
            profile__role__in=[Role.FIELD, Role.HQ]
        ).order_by("username")
        for field in self.fields.values():
            field.widget.attrs.setdefault("class", "form-control")


class BudgetItemForm(forms.ModelForm):
    class Meta:
        model = BudgetItem
        fields = ["category", "cost_item", "name", "planned_amount", "note"]

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.fields["cost_item"].queryset = CostItem.objects.all().order_by(
            "sort_order", "name"
        )
        self.fields["cost_item"].label_from_instance = self._label_from_cost_item
        for field in self.fields.values():
            field.widget.attrs.setdefault("class", "form-control")

    @staticmethod
    def _label_from_cost_item(item):
        alias = item.get_display_name()
        name = item.name
        if alias and alias != name:
            return f"{item.code} - {alias} - {name}"
        return f"{item.code} - {name}"

    def clean_planned_amount(self):
        raw = self.cleaned_data.get("planned_amount")
        if raw is None:
            return 0
        if isinstance(raw, str):
            raw = raw.replace(",", "").strip()
        return int(raw)

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


class WBSChangeRequestForm(forms.ModelForm):
    class Meta:
        model = WBSChangeRequest
        fields = ["request_type", "reason", "change_order"]

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.fields["request_type"].choices = [
            (WBSChangeRequestType.DESIGN_CONTRACT_CHANGE, "설계/계약 변경"),
            (WBSChangeRequestType.SCHEDULE_ADJUSTMENT, "공정 조정"),
        ]
        self.fields["reason"].required = True
        for field in self.fields.values():
            field.widget.attrs.setdefault("class", "form-control")


class WBSChangeLineForm(forms.ModelForm):
    class Meta:
        model = WBSChangeLine
        fields = ["task_name", "weight", "planned_start", "planned_end", "note"]
        widgets = {
            "planned_start": forms.DateInput(attrs={"type": "date"}),
            "planned_end": forms.DateInput(attrs={"type": "date"}),
        }

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        for field in self.fields.values():
            field.widget.attrs.setdefault("class", "form-control")


class ApprovalPackageForm(forms.ModelForm):
    class Meta:
        model = ApprovalPackage
        fields = ["title", "reason"]

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        for field in self.fields.values():
            field.widget.attrs.setdefault("class", "form-control")

