from __future__ import annotations

from django import forms
from django.core.exceptions import ValidationError

from apps.core.rbac.models import Role, ProjectAssignment
from apps.projects.models import Project
from apps.cost.models import CostItem

from .models import (
    Adjustment,
    AdjustmentTargetType,
    ClosingPeriod,
    ClosingStatus,
)


TARGET_TYPE_CHOICES = [
    (AdjustmentTargetType.COST, "원가"),
    (AdjustmentTargetType.LABOR, "인건비"),
    (AdjustmentTargetType.INVENTORY, "재고"),
]


class AdjustmentForm(forms.ModelForm):
    period = forms.ChoiceField(label="마감 월")
    amount_delta = forms.CharField(label="정정 금액")

    class Meta:
        model = Adjustment
        fields = ["project", "target_type", "cbs", "amount_delta", "reason", "period"]

    def __init__(self, *args, user=None, role=None, **kwargs):
        super().__init__(*args, **kwargs)
        self.user = user
        self.role = role

        if role == Role.FIELD and user:
            project_ids = ProjectAssignment.objects.filter(
                user=user, is_active=True
            ).values_list("project_id", flat=True)
            self.fields["project"].queryset = Project.objects.filter(id__in=project_ids)
        else:
            self.fields["project"].queryset = Project.objects.all()
        self.fields["project"].label = "프로젝트"

        closed_periods = ClosingPeriod.objects.filter(status=ClosingStatus.CLOSED).order_by("-year", "-month")
        self.fields["period"].choices = [
            (f"{period.year}-{period.month:02d}", f"{period.legal_entity.name} · {period.year}년 {period.month}월")
            for period in closed_periods
        ] or [("", "마감된 월이 없습니다.")]

        self.fields["target_type"].choices = TARGET_TYPE_CHOICES
        self.fields["target_type"].label = "대상"

        cbs_qs = CostItem.objects.all().order_by("code")
        if role == Role.FIELD:
            cbs_qs = cbs_qs.filter(is_active=True)
        self.fields["cbs"].queryset = cbs_qs
        self.fields["cbs"].required = False
        self.fields["cbs"].label = "CBS (선택)"
        self.fields["cbs"].label_from_instance = (
            lambda obj: f"{obj.code} - {obj.get_display_name()}"
        )

        self.fields["reason"].label = "사유"
        for field in self.fields.values():
            css_class = field.widget.attrs.get("class", "")
            field.widget.attrs["class"] = f"{css_class} form-control".strip()

    def clean_amount_delta(self):
        raw_value = self.cleaned_data.get("amount_delta")
        if raw_value is None:
            raise ValidationError("정정 금액을 입력하세요.")
        if isinstance(raw_value, str):
            raw_value = raw_value.replace(",", "").strip()
        try:
            value = int(raw_value)
        except (TypeError, ValueError):
            raise ValidationError("정정 금액은 숫자여야 합니다.")
        return value

    def clean_period(self):
        value = (self.cleaned_data.get("period") or "").strip()
        if not value or "-" not in value:
            raise ValidationError("마감 월을 선택하세요.")
        year_str, month_str = value.split("-", 1)
        try:
            year = int(year_str)
            month = int(month_str)
        except ValueError as exc:
            raise ValidationError("마감 월 형식이 올바르지 않습니다.") from exc
        project = self.cleaned_data.get("project")
        if project is None:
            raise ValidationError("프로젝트를 먼저 선택하세요.")
        is_closed = ClosingPeriod.objects.filter(
            legal_entity=project.legal_entity, year=year, month=month, status=ClosingStatus.CLOSED
        ).exists()
        if not is_closed:
            raise ValidationError("마감된 월만 선택할 수 있습니다.")
        self.cleaned_data["period_year"] = year
        self.cleaned_data["period_month"] = month
        return value


class AdjustmentDecisionForm(forms.Form):
    note = forms.CharField(label="반려 사유", widget=forms.Textarea, required=True)
