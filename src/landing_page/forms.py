from django import forms

from .models import JoinRequest, ProjectIdea


class JoinForm(forms.ModelForm):
    class Meta:
        model = JoinRequest
        fields = ['name', 'email', 'grade', 'message']
        labels = {'message': 'Anything you want us to know? (optional)'}
        widgets = {'message': forms.Textarea(attrs={'rows': 4})}


class IdeaForm(forms.ModelForm):
    class Meta:
        model = ProjectIdea
        fields = ['source', 'title', 'description', 'name', 'email']
        labels = {
            'source': 'What kind of idea is this?',
            'name': 'Your name (optional)',
            'email': 'Your email (optional)',
        }
        widgets = {'description': forms.Textarea(attrs={'rows': 5})}
