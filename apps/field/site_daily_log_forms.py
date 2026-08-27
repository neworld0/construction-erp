from django import forms
from django.forms import inlineformset_factory

from apps.projects.models import ProjectWorkProgressMapping

from .models import SiteDailyLog, SiteDailyLogWorkLine


class SiteDailyLogForm(forms.ModelForm):
    class Meta:
        model = SiteDailyLog
        fields = ["project", "report_date", "today_work", "tomorrow_work", "special_notes"]
        widgets = {
            "report_date": forms.DateInput(attrs={"type": "date"}),
            "today_work": forms.Textarea(attrs={"rows": 4}),
            "tomorrow_work": forms.Textarea(attrs={"rows": 3}),
            "special_notes": forms.Textarea(attrs={"rows": 3}),
        }

    def __init__(self, *args, projects=None, **kwargs):
        super().__init__(*args, **kwargs)
        if projects is not None:
            self.fields["project"].queryset = projects


class SiteDailyLogWorkLineForm(forms.ModelForm):
    class Meta:
        model = SiteDailyLogWorkLine
        fields = ["progress_mapping", "uom", "today_qty", "memo"]

    def __init__(self, *args, project=None, **kwargs):
        super().__init__(*args, **kwargs)
        mappings = ProjectWorkProgressMapping.objects.none()
        if project is not None:
            mappings = ProjectWorkProgressMapping.objects.filter(
                project=project, is_active=True
            ).select_related("wbs_item", "schedule_task", "uom")
        self.fields["progress_mapping"].queryset = mappings
        if self.instance and self.instance.progress_mapping_id:
            self.fields["uom"].queryset = self.fields["uom"].queryset.filter(
                id=self.instance.progress_mapping.uom_id
            )

    def clean(self):
        cleaned = super().clean()
        mapping = cleaned.get("progress_mapping")
        if mapping is not None:
            cleaned["uom"] = mapping.uom
            self.instance.uom = mapping.uom
        return cleaned


SiteDailyLogWorkLineFormSet = inlineformset_factory(
    SiteDailyLog,
    SiteDailyLogWorkLine,
    form=SiteDailyLogWorkLineForm,
    extra=1,
    can_delete=True,
)
