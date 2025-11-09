from django.contrib import admin
from .models import Cliente

@admin.register(Cliente)
class ClienteAdmin(admin.ModelAdmin):
    list_display = ("nombre_completo", "rut", "correo", "telefono", "creado_en", "es_sensible")
    search_fields = ("nombre_completo", "rut", "correo", "telefono")
    list_filter = ("es_sensible",)