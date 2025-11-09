from django.urls import path
from .views_archivos import (
    ListadoCasosArchivosView,
    ListaArchivosCasoView,
    SubirArchivoCasoView,
    DescargarArchivoCasoView,
    VerArchivoCasoView,
    EditarArchivoCasoView,
    FicherosRecientesView,
    CambiarEstadoCasoView,
    CambiarCategoriaCasoView,
)
from .views import crear_caso
from .views_busqueda import BuscarCasosView  
from .views import CasoDetailView  # o donde tengas la vista de detalle

app_name = "cases"

urlpatterns = [
    path("archivos/", ListadoCasosArchivosView.as_view(), name="listado_casos_archivos"),
    path("<int:caso_id>/archivos/", ListaArchivosCasoView.as_view(), name="archivos_caso"),
    path("<int:caso_id>/archivos/subir/", SubirArchivoCasoView.as_view(), name="subir_archivo_caso"),
    path("archivos/<str:file_id>/descargar/", DescargarArchivoCasoView.as_view(), name="descargar_archivo_caso"),
    path("archivos/<str:file_id>/ver/", VerArchivoCasoView.as_view(), name="ver_archivo_caso"),
    path("archivos/<str:file_id>/editar/", EditarArchivoCasoView.as_view(), name="editar_archivo_caso"),
    path("ficheros/", FicherosRecientesView.as_view(), name="ficheros_recientes"),
    path("<int:caso_id>/estado/", CambiarEstadoCasoView.as_view(), name="cambiar_estado_caso"),
    path("<int:caso_id>/categoria/", CambiarCategoriaCasoView.as_view(), name="cambiar_categoria_caso"),
    path("buscar/", BuscarCasosView.as_view(), name="casos_buscar"),
    path("<int:pk>/", CasoDetailView.as_view(), name="detalle_caso"),  # /casos/1/


    path("nuevo/", crear_caso, name="crear_caso"),

    # 👉 Alias para plantillas antiguas:
    path("<int:caso_id>/", ListaArchivosCasoView.as_view(), name="detalle"),
]
