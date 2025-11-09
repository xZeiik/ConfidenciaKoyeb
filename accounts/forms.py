from django import forms
from .models import Usuario
from django.contrib.auth.forms import PasswordChangeForm

class UsuarioEditForm(forms.ModelForm):
    class Meta:
        model = Usuario
        fields = ["first_name", "last_name", "email", "is_active"]
        labels = {
            "first_name": "Nombre",
            "last_name": "Apellido",
            "email": "Correo electrónico",
            "is_active": "Cuenta activa",
        }



class AbogadoCrearForm(forms.ModelForm):
    password1 = forms.CharField(label="Contraseña", widget=forms.PasswordInput)
    password2 = forms.CharField(label="Confirmar contraseña", widget=forms.PasswordInput)

    class Meta:
        model = Usuario
        fields = ["username", "first_name", "last_name", "email"]

    def clean(self):
        data = super().clean()
        if data.get("password1") != data.get("password2"):
            raise forms.ValidationError("Las contraseñas no coinciden.")
        return data        
    


class AccountEmailForm(forms.ModelForm):
    class Meta:
        model = Usuario
        fields = ["email"]
        widgets = {
            "email": forms.EmailInput(attrs={"class": "form-control", "placeholder": "tucorreo@dominio.cl"})
        }    