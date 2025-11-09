from django.contrib import admin
from .models import Caso, AccesoCaso, ArchivoCaso, ArchivoEvento

@admin.register(Caso)
class CasoAdmin(admin.ModelAdmin):
    list_display = ("titulo", "cliente", "abogado_responsable", "estado", "categoria", "creado_en")
    list_filter = ("estado", "categoria", "abogado_responsable")
    search_fields = ("titulo", "cliente__nombre_completo", "cliente__rut")

@admin.register(AccesoCaso)
class AccesoCasoAdmin(admin.ModelAdmin):
    list_display = ("caso", "abogado", "puede_editar")
    list_filter = ("puede_editar",)
    search_fields = ("caso__titulo", "abogado__username")

@admin.register(ArchivoCaso)
class ArchivoCasoAdmin(admin.ModelAdmin):
    list_display = ("nombre", "caso", "tipo_mime", "tamano", "modificado_en", "subido_por")
    search_fields = ("nombre", "caso__codigo_caso", "caso__titulo")





@admin.register(ArchivoEvento)
class ArchivoEventoAdmin(admin.ModelAdmin):
    list_display = ("caso", "archivo", "accion", "usuario", "ip", "creado_en")
    list_filter = ("accion", "creado_en")
    search_fields = ("detalle", "archivo__nombre", "caso__codigo_caso")    