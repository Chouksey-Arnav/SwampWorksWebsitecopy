from django import forms
from django.contrib.auth.forms import UserCreationForm

from .models import User


class CustomUserCreationForm(UserCreationForm):
    first_name = forms.CharField(
        required=False, max_length=30, label='First name (optional)',
        help_text='This is the name your tutor sees. Leave it blank to use your username. First name only is fine.',
    )
    email = forms.EmailField(required=True, help_text="We'll email you booking confirmations. Tutors never see it.")

    class Meta:
        model = User
        fields = ['first_name', 'username', 'email', 'password1', 'password2']

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.fields['first_name'].widget.attrs.update(autocomplete='given-name', autofocus=True)
        self.fields['username'].widget.attrs.update(autocomplete='username')
        self.fields['username'].help_text = 'Letters, numbers and @/./+/-/_ only.'
        self.fields['email'].widget.attrs.update(autocomplete='email')
        self.fields['password1'].widget.attrs.update(autocomplete='new-password')
        self.fields['password2'].widget.attrs.update(autocomplete='new-password')

    def clean_email(self):
        email = self.cleaned_data['email']
        if User.objects.filter(email__iexact=email).exists():
            raise forms.ValidationError('That email is already in use.')
        return email
