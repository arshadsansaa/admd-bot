from django import forms
from django.contrib.auth import authenticate
from .models import BotCredential


class SignInForm(forms.Form):
    email = forms.EmailField(
        widget=forms.EmailInput(attrs={'placeholder': 'Email Address', 'class': 'form-control'})
    )
    password = forms.CharField(
        widget=forms.PasswordInput(attrs={'placeholder': 'Password', 'class': 'form-control'})
    )

    def clean(self):
        cleaned_data = super().clean()
        email = cleaned_data.get('email')
        password = cleaned_data.get('password')

        if email and password:
            self.user = authenticate(username=email, password=password)
            if self.user is None:
                raise forms.ValidationError('Invalid email or password.')
            if not self.user.is_active:
                raise forms.ValidationError('This account is inactive.')
        return cleaned_data

    def get_user(self):
        return self.user


class BotCredentialForm(forms.ModelForm):
    class Meta:
        model = BotCredential
        fields = ['username', 'password', 'office_key']
        widgets = {
            'username': forms.TextInput(attrs={'placeholder': 'AdvancedMD Username', 'class': 'form-control'}),
            'password': forms.TextInput(attrs={'placeholder': 'AdvancedMD Password', 'class': 'form-control'}),
            'office_key': forms.TextInput(attrs={'placeholder': 'Office Key', 'class': 'form-control'}),
        }

