from django import forms
from django.db.models import Q
from django.core.exceptions import ValidationError

from apps.cost.models import CostActual, CostItem
from apps.core.rbac.models import LegalEntity
from apps.projects.models import Project

from .models import (
    ElectronicCardImportBatchStatus,
    LaborWorkLedger,
    LaborWorkLedgerSource,
    LaborWorkLedgerStatus,
    LaborRateScope,
    LaborRateTable,
    LaborRateType,
    LaborRole,
    PayrollAllocationBatch,
    Timesheet,
    WorkerMaster,
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
    scope_type = forms.ChoiceField(
        choices=[
            (LaborRateScope.GLOBAL, "기본 또는 근로자 단가"),
            (LaborRateScope.PROJECT, "프로젝트 단가"),
        ]
    )
    rate_type = forms.ChoiceField(
        choices=[
            (LaborRateType.DAY, "일 단가"),
            (LaborRateType.HOUR, "시간 단가"),
        ]
    )

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
            "worker",
            "is_active",
            "note",
        ]

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.fields["project"].queryset = Project.objects.order_by("name")
        worker_queryset = WorkerMaster.objects.filter(active=True).select_related(
            "default_labor_role"
        )
        if self.instance and self.instance.pk and self.instance.worker_id:
            worker_queryset = worker_queryset | WorkerMaster.objects.filter(
                id=self.instance.worker_id
            ).select_related("default_labor_role")
        self.fields["worker"].queryset = worker_queryset.order_by("name", "id")
        self.fields["worker"].label_from_instance = lambda worker: (
            f"{worker.name}"
            + (f" / {worker.default_labor_role.name}" if worker.default_labor_role else "")
        )
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
        fields = ["legal_entity", "period_year", "period_month", "total_amount", "note"]

    def __init__(self, *args, **kwargs):
        actor = kwargs.pop("actor", None)
        super().__init__(*args, **kwargs)
        if actor is not None:
            from apps.core.rbac.permissions import get_user_legal_entities

            self.fields["legal_entity"].queryset = get_user_legal_entities(actor)
        else:
            self.fields["legal_entity"].queryset = LegalEntity.objects.filter(is_active=True)
        if self.instance and self.instance.pk:
            self.fields["legal_entity"].disabled = True
        for field in self.fields.values():
            field.widget.attrs.setdefault("class", "input")


class WorkerMasterForm(forms.ModelForm):
    rrn = forms.CharField(
        label="주민등록번호",
        required=False,
        widget=forms.TextInput(attrs={"autocomplete": "off"}),
    )
    account_number = forms.CharField(
        label="계좌번호",
        required=False,
        widget=forms.TextInput(attrs={"autocomplete": "off"}),
    )

    class Meta:
        model = WorkerMaster
        fields = [
            "name",
            "rrn",
            "phone",
            "address",
            "bank_name",
            "bank_code",
            "account_number",
            "account_holder",
            "nationality_code",
            "visa_code",
            "comwel_job_code",
            "cwma_job_name",
            "default_labor_role",
            "retirement_deduction_eligible",
            "active",
        ]
        widgets = {
            "address": forms.Textarea(attrs={"rows": 3}),
        }
        labels = {
            "name": "성명",
            "phone": "전화번호",
            "address": "주소",
            "bank_name": "은행명",
            "bank_code": "은행코드",
            "account_holder": "예금주",
            "nationality_code": "국적코드",
            "visa_code": "비자코드",
            "comwel_job_code": "근로복지공단 직종코드",
            "cwma_job_name": "건설근로자공제회 직종명",
            "default_labor_role": "기본 노무 역할",
            "retirement_deduction_eligible": "퇴직공제 대상",
            "active": "사용중",
        }

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        instance = getattr(self, "instance", None)
        role_queryset = LaborRole.objects.filter(is_active=True)
        if instance and instance.pk and instance.default_labor_role_id:
            role_queryset = role_queryset | LaborRole.objects.filter(
                id=instance.default_labor_role_id
            )
        self.fields["default_labor_role"].queryset = role_queryset.order_by(
            "sort_order", "code"
        )
        if instance and instance.pk:
            if instance.rrn_masked:
                self.fields["rrn"].help_text = f"현재 값: {instance.rrn_masked}"
            if instance.account_number_masked:
                self.fields["account_number"].help_text = f"현재 값: {instance.account_number_masked}"
        for field_name, field in self.fields.items():
            field.widget.attrs.setdefault("class", "form-control")
            if field_name in ("retirement_deduction_eligible", "active"):
                field.widget.attrs["class"] = ""

    def clean_name(self):
        value = str(self.cleaned_data.get("name") or "").strip()
        if not value:
            raise forms.ValidationError("성명을 입력해 주세요.")
        return value

    def clean_rrn(self):
        return str(self.cleaned_data.get("rrn") or "").strip()

    def clean_account_number(self):
        return str(self.cleaned_data.get("account_number") or "").strip()

    def clean(self):
        cleaned = super().clean()
        rrn = cleaned.get("rrn") or ""
        if not rrn and not getattr(self.instance, "rrn_encrypted", ""):
            self.add_error("rrn", "주민등록번호를 입력해 주세요.")
        return cleaned


class LaborWorkLedgerForm(forms.ModelForm):
    source = forms.ChoiceField(choices=LaborWorkLedgerSource.choices)
    status = forms.ChoiceField(choices=LaborWorkLedgerStatus.choices)

    class Meta:
        model = LaborWorkLedger
        fields = [
            "work_date",
            "worker",
            "actual_project",
            "report_project",
            "labor_role",
            "work_unit",
            "work_hours",
            "unit_wage",
            "income_tax",
            "local_tax",
            "employment_insurance",
            "pension",
            "health_insurance",
            "detail_work_type",
            "source",
            "status",
            "timesheet_ref",
            "cost_ref",
        ]
        labels = {
            "work_date": "근무일",
            "worker": "근로자",
            "actual_project": "실제 근무 프로젝트",
            "report_project": "보고 프로젝트",
            "labor_role": "노무 역할",
            "work_unit": "공수",
            "work_hours": "근무시간",
            "unit_wage": "단가",
            "income_tax": "소득세",
            "local_tax": "지방세",
            "employment_insurance": "고용보험",
            "pension": "국민연금",
            "health_insurance": "건강보험",
            "detail_work_type": "세부 작업유형",
            "source": "출처",
            "status": "상태",
            "timesheet_ref": "출역부 연결",
            "cost_ref": "원가실적 연결",
        }

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.fields["worker"].queryset = WorkerMaster.objects.order_by("name", "id")
        self.fields["actual_project"].queryset = Project.objects.order_by("name")
        self.fields["report_project"].queryset = Project.objects.order_by("name")
        self.fields["labor_role"].queryset = LaborRole.objects.order_by("sort_order", "code")
        self.fields["timesheet_ref"].queryset = Timesheet.objects.select_related("project").order_by("-work_date", "-id")
        self.fields["cost_ref"].queryset = CostActual.objects.select_related("project").order_by("-report_date", "-id")
        self.fields["report_project"].required = False
        self.fields["timesheet_ref"].required = False
        self.fields["cost_ref"].required = False
        for field in self.fields.values():
            field.widget.attrs.setdefault("class", "form-control")

    def clean(self):
        cleaned = super().clean()
        actual_project = cleaned.get("actual_project")
        if actual_project and not cleaned.get("report_project"):
            cleaned["report_project"] = actual_project
        return cleaned


class ElectronicCardImportBatchUploadForm(forms.Form):
    year_month = forms.CharField(label="기준월")
    project = forms.ModelChoiceField(
        label="현장",
        queryset=Project.objects.none(),
        empty_label="현장을 선택하세요",
    )
    source_file = forms.FileField(label="전자카드 원본 파일")

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.fields["project"].queryset = Project.objects.order_by("name")
        self.fields["year_month"].widget = forms.TextInput(
            attrs={"class": "input", "placeholder": "YYYY-MM"}
        )
        self.fields["project"].widget.attrs.setdefault("class", "input")
        self.fields["source_file"].widget.attrs.setdefault("class", "input")

    def clean_year_month(self):
        value = str(self.cleaned_data.get("year_month") or "").strip()
        if not value:
            raise ValidationError("기준월을 입력해 주세요.")
        parts = value.split("-", 1)
        if len(parts) != 2:
            raise ValidationError("기준월 형식은 YYYY-MM 이어야 합니다.")
        try:
            year = int(parts[0])
            month = int(parts[1])
        except ValueError as exc:
            raise ValidationError("기준월 형식은 YYYY-MM 이어야 합니다.") from exc
        if month < 1 or month > 12:
            raise ValidationError("기준월 형식은 YYYY-MM 이어야 합니다.")
        return f"{year:04d}-{month:02d}"


class ElectronicCardImportBatchFilterForm(forms.Form):
    month = forms.CharField(label="기준월", required=False)
    project = forms.ModelChoiceField(
        label="현장",
        queryset=Project.objects.none(),
        required=False,
        empty_label="전체 현장",
    )
    status = forms.ChoiceField(
        label="상태",
        required=False,
        choices=[("", "전체 상태"), *ElectronicCardImportBatchStatus.choices],
    )

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.fields["project"].queryset = Project.objects.order_by("name")
        for field in self.fields.values():
            field.widget.attrs.setdefault("class", "input")
