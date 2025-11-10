# accounts/urls.py
from django.urls import path
from . import views
from . import views_calendar as gviews
from . import views_drive_oauth as dviews


app_name = "accounts"

urlpatterns = [
    # ---- Autenticación ----
    path("login/", views.login_view, name="login"),
    path("logout/", views.logout_view, name="logout"),
    path("cuenta/", views.detalle_cuenta, name="detalle_cuenta"),

    # ---- Gestión de abogados ----
    path("abogados/", views.listar_abogados, name="listar_abogados"),
    path("abogados/nuevo/", views.crear_abogado, name="crear_abogado"),
    path("abogados/<int:pk>/editar/", views.editar_abogado, name="editar_abogado"),

    # ---- Google Calendar ----
    path("google/connect/", gviews.conectar_google_calendar, name="google_connect"),
    path("google/reconnect/", gviews.google_reconnect, name="google_reconnect"),
    path("google/disconnect/", gviews.google_disconnect, name="google_disconnect"),
    path("google/callback/", gviews.google_callback, name="google_callback"),
    path("google/eventos/", gviews.gcal_eventos, name="gcal_eventos"),
    path("google/crear-evento/", gviews.gcal_crear_evento, name="gcal_crear_evento"),
    path("google/eventos/<str:event_id>/", gviews.gcal_event_detail, name="gcal_event_detail"),
    path("google/eventos/<str:event_id>/editar/", gviews.gcal_event_edit, name="gcal_event_edit"),
    path("google/eventos/<str:event_id>/eliminar/", gviews.gcal_event_delete, name="gcal_event_delete"),

        # ---- OAuth de Google Drive (separado de Calendar) ----
    path("google/drive/connect/", dviews.google_drive_connect, name="google_drive_connect"),
    path("google/drive/callback/", dviews.google_drive_callback, name="google_drive_callback"),
    path("google/drive/disconnect/", dviews.google_drive_disconnect, name="google_drive_disconnect"),

    # Diagnóstico opcional (ya lo tenías apuntando a dviews)
    path("google/whoami/", dviews.google_whoami, name="google_whoami"),    
]
