# accounts/urls.py
from django.urls import path
from . import views
from . import views_calendar as gviews

app_name = "accounts"

urlpatterns = [
    path("login/", views.login_view, name="login"),
    path("logout/", views.logout_view, name="logout"),
    path("cuenta/", views.detalle_cuenta, name="detalle_cuenta"),

    # Google Calendar
    path("google/connect/", gviews.conectar_google_calendar, name="google_connect"),
    path("google/reconnect/", gviews.google_reconnect, name="google_reconnect"),
    path("google/disconnect/", gviews.google_disconnect, name="google_disconnect"),
    path("google/callback/", gviews.google_callback, name="google_callback"),
    path("google/eventos/", gviews.gcal_eventos, name="gcal_eventos"),
    path("google/crear-evento/", gviews.gcal_crear_evento, name="gcal_crear_evento"),
    path("google/eventos/<str:event_id>/", gviews.gcal_event_detail, name="gcal_event_detail"),
    path("google/eventos/<str:event_id>/editar/", gviews.gcal_event_edit, name="gcal_event_edit"),
    path("google/eventos/<str:event_id>/eliminar/", gviews.gcal_event_delete, name="gcal_event_delete"),
]
