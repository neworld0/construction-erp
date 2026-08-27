import re

from django import forms
from django.contrib.auth import get_user_model

from apps.cost.models import CostItem

from apps.core.rbac.models import LegalEntity, LegalEntityLicense, ProjectAssignment, Role
from apps.core.rbac.permissions import get_user_legal_entities

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

BUDGET_BASELINE_CATEGORY_LABELS = {
    BudgetCategory.MATERIAL: "재료비",
    BudgetCategory.SUBCON: "하도급",
    BudgetCategory.LABOR: "노무비",
    BudgetCategory.OTHER: "경비",
    BudgetCategory.EQUIP: "경비",
    BudgetCategory.OVERHEAD: "경비",
}

BUDGET_BASELINE_CATEGORY_CHOICES = [
    (BudgetCategory.MATERIAL, "재료비"),
    (BudgetCategory.SUBCON, "하도급"),
    (BudgetCategory.LABOR, "노무비"),
    (BudgetCategory.OTHER, "경비"),
]


class ProjectOnboardingForm(forms.ModelForm):
    LICENSE_TYPES_BY_ENTITY_AND_PROJECT_TYPE = {
        ("ASAN", ProjectType.LANDSCAPE): {"조경공사업"},
        ("ASAN", ProjectType.CIVIL): {"토목공사업"},
        ("MISAN", ProjectType.LANDSCAPE): {"조경식재공사업", "조경시설물설치공사업"},
    }
    work_types = forms.MultipleChoiceField(
        choices=[
            (ProjectType.LANDSCAPE, "조경"),
            (ProjectType.CIVIL, "토목"),
            (ProjectType.ARCH, "건축"),
        ],
        widget=forms.CheckboxSelectMultiple,
        label="계약 공종",
        help_text="복수 선택할 수 있습니다. 프로젝트 코드는 대표 공종을 기준으로 생성됩니다.",
    )
    contracting_licenses = forms.ModelMultipleChoiceField(
        queryset=LegalEntityLicense.objects.none(),
        widget=forms.CheckboxSelectMultiple,
        label="계약 적용 면허",
        help_text="복합 공종에 적용되는 면허를 모두 선택해 주세요.",
    )

    class Meta:
        model = Project
        fields = ["legal_entity", "name", "start_date", "end_date", "status", "client_name", "site_address", "requires_ceo_billing_approval"]
        widgets = {
            "start_date": forms.DateInput(attrs={"type": "date"}),
            "end_date": forms.DateInput(attrs={"type": "date"}),
        }

    def __init__(self, *args, **kwargs):
        actor = kwargs.pop("actor", None)
        super().__init__(*args, **kwargs)
        self.fields["legal_entity"].queryset = (
            get_user_legal_entities(actor)
            if actor is not None
            else LegalEntity.objects.filter(is_active=True)
        )
        license_queryset = LegalEntityLicense.objects.filter(
            is_active=True, legal_entity__is_active=True
        ).select_related("legal_entity").order_by("legal_entity__code", "license_type")
        self.fields["contracting_licenses"].queryset = license_queryset
        if self.instance and self.instance.pk:
            self.initial.setdefault("work_types", self.instance.work_types or [self.instance.project_type])
            self.initial.setdefault("contracting_licenses", self.instance.contracting_licenses.all())
        else:
            self.initial.setdefault("work_types", [ProjectType.LANDSCAPE])
        self.fields["status"].choices = [
            (ProjectStatus.DRAFT, "DRAFT"),
            (ProjectStatus.SUBMITTED, "SUBMITTED"),
            (ProjectStatus.APPROVED, "APPROVED"),
        ]
        for field in self.fields.values():
            field.widget.attrs.setdefault("class", "form-control")

    def clean(self):
        cleaned = super().clean()
        entity = cleaned.get("legal_entity")
        license_objs = list(cleaned.get("contracting_licenses") or [])
        work_types = list(cleaned.get("work_types") or [])
        start_date = cleaned.get("start_date")
        if not entity or not license_objs or not work_types:
            return cleaned
        if any(license_obj.legal_entity_id != entity.id for license_obj in license_objs):
            self.add_error("contracting_licenses", "계약 법인에 등록된 면허만 선택할 수 있습니다.")
            return cleaned
        license_types = {license_obj.license_type for license_obj in license_objs}
        for work_type in work_types:
            allowed_types = self.LICENSE_TYPES_BY_ENTITY_AND_PROJECT_TYPE.get((entity.code, work_type), set())
            if not allowed_types or not (license_types & allowed_types):
                self.add_error("contracting_licenses", f"{entity.name}의 {dict(self.fields['work_types'].choices)[work_type]} 공종에 필요한 유효 면허를 선택해 주세요.")
                break
        for license_obj in license_objs:
            effective_date = start_date or license_obj.registered_on
            if license_obj.valid_from and effective_date < license_obj.valid_from:
                self.add_error("contracting_licenses", "공사 시작일에 아직 유효하지 않은 면허가 포함되어 있습니다.")
            if license_obj.valid_to and effective_date > license_obj.valid_to:
                self.add_error("contracting_licenses", "공사 시작일에 유효기간이 지난 면허가 포함되어 있습니다.")
        return cleaned


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
        self.require_file = kwargs.pop("require_file", True)
        super().__init__(*args, **kwargs)
        for field in self.fields.values():
            field.widget.attrs.setdefault("class", "form-control")

    def clean_contract_file(self):
        file_obj = self.cleaned_data.get("contract_file")
        if not file_obj and self.require_file:
            raise forms.ValidationError("계약서 파일은 필수입니다.")
        return file_obj


class ProjectAssignmentForm(forms.ModelForm):
    class Meta:
        model = ProjectAssignment
        fields = ["user", "assignment_type", "is_active"]

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
        self.fields["category"].choices = BUDGET_BASELINE_CATEGORY_CHOICES
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
        self.fields["category"].choices = [(BudgetCategory.LABOR, "노무비")]
        self.fields["category"].initial = BudgetCategory.LABOR
        self.fields["category"].widget = forms.HiddenInput()
        base_qs = CostItem.objects.exclude(code="CIVIL-PROFIT").filter(
            category="labor"
        )
        if self.is_bound:
            raw_cost_item = self.data.get(self.add_prefix("cost_item"))
            if raw_cost_item:
                base_qs = CostItem.objects.filter(id=raw_cost_item) | base_qs
        self.fields["cost_item"].queryset = base_qs.order_by("sort_order", "name")

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
            "weight": forms.NumberInput(
                attrs={
                    "step": "0.01",
                    "min": "0",
                    "max": "100",
                    "inputmode": "decimal",
                }
            ),
            "plan_start_date": forms.DateInput(attrs={"type": "date"}),
            "plan_end_date": forms.DateInput(attrs={"type": "date"}),
        }

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        # WBS ordering is assigned by the baseline save flow when HQ leaves it blank.
        self.fields["sort_order"].required = False
        for field in self.fields.values():
            field.widget.attrs.setdefault("class", "form-control")
        weight_attrs = self.fields["weight"].widget.attrs
        weight_attrs["class"] = "form-control"
        weight_attrs["step"] = "0.01"
        weight_attrs["min"] = "0"
        weight_attrs["max"] = "100"
        weight_attrs["inputmode"] = "decimal"


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
        weight_attrs = self.fields["weight"].widget.attrs
        weight_attrs["class"] = "form-control"
        weight_attrs["step"] = "0.01"
        weight_attrs["min"] = "0"
        weight_attrs["max"] = "100"
        weight_attrs["inputmode"] = "decimal"


class ApprovalPackageForm(forms.ModelForm):
    class Meta:
        model = ApprovalPackage
        fields = ["title", "reason"]

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        for field in self.fields.values():
            field.widget.attrs.setdefault("class", "form-control")

