from django import forms
from django.core.exceptions import ValidationError

from .models import LegalEntityCreditRating, LegalEntityLicense, LegalEntityLicenseConstructionPerformance


PERFORMANCE_EVIDENCE_ALLOWED_EXTENSIONS = {"pdf", "xlsx", "xls", "png", "jpg", "jpeg"}
PERFORMANCE_EVIDENCE_MAX_BYTES = 20 * 1024 * 1024


def _validate_performance_evidence_file(file_obj):
    extension = file_obj.name.rsplit(".", 1)[-1].lower() if "." in file_obj.name else ""
    if extension not in PERFORMANCE_EVIDENCE_ALLOWED_EXTENSIONS:
        raise ValidationError("PDF, Excel 또는 이미지(PNG/JPG) 파일만 첨부할 수 있습니다.")
    if file_obj.size > PERFORMANCE_EVIDENCE_MAX_BYTES:
        raise ValidationError("파일 용량은 20MB 이하만 첨부할 수 있습니다.")
    return file_obj


class LegalEntityLicenseForm(forms.ModelForm):
    class Meta:
        model = LegalEntityLicense
        fields = [
            "license_type",
            "registration_number",
            "registered_on",
            "registered_by",
            "valid_from",
            "valid_to",
            "is_active",
            "evidence_note",
        ]
        widgets = {
            "registered_on": forms.DateInput(attrs={"type": "date"}),
            "valid_from": forms.DateInput(attrs={"type": "date"}),
            "valid_to": forms.DateInput(attrs={"type": "date"}),
            "evidence_note": forms.Textarea(attrs={"rows": 2}),
        }

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        for field in self.fields.values():
            field.widget.attrs.setdefault("class", "input")


class LegalEntityLicenseConstructionPerformanceForm(forms.ModelForm):
    evidence_file = forms.FileField(label="실적증명서 파일", required=False)

    class Meta:
        model = LegalEntityLicenseConstructionPerformance
        fields = [
            "license",
            "work_category",
            "external_category_code",
            "as_of_date",
            "three_year_amount",
            "five_year_amount",
            "source",
            "evidence_note",
        ]
        labels = {
            "license": "적용 면허",
            "work_category": "공종",
            "external_category_code": "외부 공종 코드",
            "as_of_date": "실적 기준일",
            "three_year_amount": "최근 3년 시공 실적(원)",
            "five_year_amount": "최근 5년 시공 실적(원)",
            "source": "실적 출처",
            "evidence_note": "증빙·비고",
        }
        widgets = {
            "as_of_date": forms.DateInput(attrs={"type": "date"}),
            "three_year_amount": forms.NumberInput(attrs={"min": 0, "step": 1}),
            "five_year_amount": forms.NumberInput(attrs={"min": 0, "step": 1}),
            "evidence_note": forms.Textarea(attrs={"rows": 2}),
        }

    def __init__(self, *args, legal_entity=None, **kwargs):
        super().__init__(*args, **kwargs)
        licenses = LegalEntityLicense.objects.filter(is_active=True)
        if legal_entity is not None:
            licenses = licenses.filter(legal_entity=legal_entity)
        self.fields["license"].queryset = licenses.order_by("license_type", "registration_number")
        self.fields["license"].label_from_instance = lambda item: f"{item.license_type} · {item.registration_number}"
        for field in self.fields.values():
            field.widget.attrs.setdefault("class", "input")
        self.fields["evidence_file"].widget.attrs["accept"] = ".pdf,.xlsx,.xls,.png,.jpg,.jpeg"

    def clean_evidence_file(self):
        file_obj = self.cleaned_data.get("evidence_file")
        return _validate_performance_evidence_file(file_obj) if file_obj else None


class LegalEntityLicenseConstructionPerformanceEvidenceUploadForm(forms.Form):
    file = forms.FileField(label="실적증명서 파일")

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.fields["file"].widget.attrs.update({
            "class": "input",
            "accept": ".pdf,.xlsx,.xls,.png,.jpg,.jpeg",
        })

    def clean_file(self):
        return _validate_performance_evidence_file(self.cleaned_data["file"])


class LegalEntityCreditRatingForm(forms.ModelForm):
    evidence_file = forms.FileField(label="신용평가서 파일", required=False)

    class Meta:
        model = LegalEntityCreditRating
        fields = ["rating_agency", "rating_grade", "assessed_on", "valid_until", "evidence_note"]
        labels = {
            "rating_agency": "평가기관",
            "rating_grade": "신용평가등급",
            "assessed_on": "평가 기준일",
            "valid_until": "유효 종료일",
            "evidence_note": "증빙·비고",
        }
        widgets = {
            "assessed_on": forms.DateInput(attrs={"type": "date"}),
            "valid_until": forms.DateInput(attrs={"type": "date"}),
            "evidence_note": forms.Textarea(attrs={"rows": 2}),
        }

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        for field in self.fields.values():
            field.widget.attrs.setdefault("class", "input")
        self.fields["evidence_file"].widget.attrs["accept"] = ".pdf,.xlsx,.xls,.png,.jpg,.jpeg"

    def clean_evidence_file(self):
        file_obj = self.cleaned_data.get("evidence_file")
        return _validate_performance_evidence_file(file_obj) if file_obj else None


class LegalEntityCreditRatingEvidenceUploadForm(forms.Form):
    file = forms.FileField(label="신용평가서 파일")

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.fields["file"].widget.attrs.update({
            "class": "input",
            "accept": ".pdf,.xlsx,.xls,.png,.jpg,.jpeg",
        })

    def clean_file(self):
        return _validate_performance_evidence_file(self.cleaned_data["file"])
