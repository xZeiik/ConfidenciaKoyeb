# bufete/cases/forms.py
from django import forms
from .models import Caso

class CasoForm(forms.ModelForm):
    class Meta:
        model = Caso
        fields = ["cliente", "titulo", "descripcion", "estado", "categoria"]
        widgets = {
            "cliente": forms.Select(attrs={"class": "form-select"}),
            "titulo": forms.TextInput(attrs={"class": "form-control"}),
            "descripcion": forms.Textarea(attrs={"class": "form-control", "rows": 4}),
            "estado": forms.Select(attrs={"class": "form-select"}),
        }
        labels = {
            "cliente": "Cliente",
            "titulo": "Título",
            "descripcion": "Descripción",
            "estado": "Estado",
        }
