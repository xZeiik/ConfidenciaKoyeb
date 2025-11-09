from django import forms
from .models import Cliente

class ClienteForm(forms.ModelForm):
    class Meta:
        model = Cliente
        fields = ["nombre_completo", "rut", "correo", "telefono", "direccion", "notas", "es_sensible"]
        widgets = {
            "nombre_completo": forms.TextInput(attrs={"class": "form-control"}),
            "rut": forms.TextInput(attrs={"class": "form-control"}),
            "correo": forms.EmailInput(attrs={"class": "form-control"}),
            "telefono": forms.TextInput(attrs={"class": "form-control"}),
            "direccion": forms.Textarea(attrs={"class": "form-control", "rows": 2}),
            "notas": forms.Textarea(attrs={"class": "form-control", "rows": 3}),
            "es_sensible": forms.CheckboxInput(attrs={"class": "form-check-input"}),
        }
        labels = {
            "nombre_completo": "Nombre completo",
            "rut": "RUT",
            "correo": "Correo",
            "telefono": "Teléfono",
            "direccion": "Dirección",
            "notas": "Notas",
            "es_sensible": "¿Datos sensibles?",
        }
