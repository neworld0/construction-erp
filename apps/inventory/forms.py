from django import forms

from apps.core.rbac.models import LegalEntity
from .models import ItemCategory, ItemMaster, UoM, Warehouse, WarehouseType


class WarehouseCreateForm(forms.ModelForm):
    class Meta:
        model = Warehouse
        fields = ["legal_entity", "code", "name"]
        widgets = {
            "code": forms.TextInput(attrs={"class": "input"}),
            "name": forms.TextInput(attrs={"class": "input"}),
        }

    def clean_code(self):
        code = (self.cleaned_data.get("code") or "").strip().upper()
        if not code:
            raise forms.ValidationError("코드를 입력하세요.")
        return code


class WarehouseUpdateForm(forms.ModelForm):
    class Meta:
        model = Warehouse
        fields = ["code", "name"]
        widgets = {
            "code": forms.TextInput(attrs={"class": "input"}),
            "name": forms.TextInput(attrs={"class": "input"}),
        }

    def clean_code(self):
        code = (self.cleaned_data.get("code") or "").strip().upper()
        if not code:
            raise forms.ValidationError("코드를 입력하세요.")
        return code

    def clean(self):
        cleaned = super().clean()
        warehouse = self.instance
        if warehouse.warehouse_type != WarehouseType.HQ:
            raise forms.ValidationError("HQ 창고만 수정할 수 있습니다.")
        return cleaned


class UoMForm(forms.ModelForm):
    class Meta:
        model = UoM
        fields = ["code", "name", "is_active"]
        widgets = {
            "code": forms.TextInput(attrs={"class": "input"}),
            "name": forms.TextInput(attrs={"class": "input"}),
        }

    def clean_code(self):
        code = (self.cleaned_data.get("code") or "").strip().upper()
        if not code:
            raise forms.ValidationError("단위 코드를 입력하세요.")
        return code


class ItemCategoryForm(forms.ModelForm):
    class Meta:
        model = ItemCategory
        fields = ["name", "code", "parent", "sort_order", "is_active"]
        widgets = {
            "name": forms.TextInput(attrs={"class": "input"}),
            "code": forms.TextInput(attrs={"class": "input"}),
            "sort_order": forms.NumberInput(attrs={"class": "input"}),
        }

    def clean_name(self):
        name = (self.cleaned_data.get("name") or "").strip()
        if not name:
            raise forms.ValidationError("카테고리명을 입력하세요.")
        return name

    def clean_code(self):
        code = (self.cleaned_data.get("code") or "").strip().upper()
        return code


class ItemMasterCreateForm(forms.ModelForm):
    auto_code = forms.BooleanField(
        required=False,
        initial=True,
        label="코드 자동 생성",
    )

    class Meta:
        model = ItemMaster
        fields = [
            "code",
            "name",
            "category",
            "uom",
            "spec",
            "description",
            "barcode",
            "is_active",
        ]
        widgets = {
            "code": forms.TextInput(attrs={"class": "input"}),
            "name": forms.TextInput(attrs={"class": "input"}),
            "spec": forms.TextInput(attrs={"class": "input"}),
            "barcode": forms.TextInput(attrs={"class": "input"}),
            "description": forms.Textarea(attrs={"class": "input", "rows": 3}),
        }

    def clean_name(self):
        name = (self.cleaned_data.get("name") or "").strip()
        if not name:
            raise forms.ValidationError("품목명을 입력하세요.")
        return name

    def clean_code(self):
        code = (self.cleaned_data.get("code") or "").strip().upper()
        auto_code = self.cleaned_data.get("auto_code")
        if auto_code:
            return ""
        if not code:
            raise forms.ValidationError("코드를 입력하세요.")
        return code


class ItemMasterUpdateForm(forms.ModelForm):
    class Meta:
        model = ItemMaster
        fields = [
            "code",
            "name",
            "category",
            "uom",
            "spec",
            "description",
            "barcode",
            "is_active",
        ]
        widgets = {
            "code": forms.TextInput(attrs={"class": "input"}),
            "name": forms.TextInput(attrs={"class": "input"}),
            "spec": forms.TextInput(attrs={"class": "input"}),
            "barcode": forms.TextInput(attrs={"class": "input"}),
            "description": forms.Textarea(attrs={"class": "input", "rows": 3}),
        }

    def clean_code(self):
        code = (self.cleaned_data.get("code") or "").strip().upper()
        if not code:
            raise forms.ValidationError("코드를 입력하세요.")
        return code
