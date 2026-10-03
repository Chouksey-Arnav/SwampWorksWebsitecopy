from django import forms

from .models import Report, Subject


class BookingForm(forms.Form):
    subject = forms.ModelChoiceField(queryset=Subject.objects.none(), empty_label='Choose a subject', label='What do you need help with?')
    note = forms.CharField(
        required=False, max_length=300, label='Anything your tutor should know? (optional)',
        widget=forms.Textarea(attrs={'rows': 3, 'maxlength': 300, 'placeholder': 'e.g. Chapter 4 practice test, quadratics, essay thesis'}),
    )

    def __init__(self, *args, tutor, **kwargs):
        super().__init__(*args, **kwargs)
        self.fields['subject'].queryset = tutor.subjects.all()


class ReportForm(forms.ModelForm):
    class Meta:
        model = Report
        fields = ['reason', 'details']
        labels = {'reason': 'What happened?', 'details': 'Tell us more (optional)'}
        widgets = {
            'reason': forms.RadioSelect,
            'details': forms.Textarea(attrs={'rows': 4, 'maxlength': 1000}),
        }
