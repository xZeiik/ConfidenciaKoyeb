# accounts/views_calendar.py
import json
import os
from datetime import datetime

from django.conf import settings
from django.contrib import messages
from django.shortcuts import redirect, render
from django.urls import reverse
from django.utils import timezone
from django.views.decorators.http import require_http_methods
from django.http import HttpResponseBadRequest

from google_auth_oauthlib.flow import Flow
from google.oauth2.credentials import Credentials
from googleapiclient.discovery import build
from google.auth.transport.requests import Request as GoogleRequest
from google.auth.exceptions import RefreshError, GoogleAuthError
from googleapiclient.errors import HttpError

from django.contrib.auth.decorators import login_required
from .models import GoogleOAuthToken  


# ---- Scopes: SOLO Calendar (lectura/creación/edición)
CAL_SCOPE = "https://www.googleapis.com/auth/calendar"
SCOPES = [CAL_SCOPE]


# =========================
# Helpers configuración
# =========================
def _load_client_config():
    """
    1) Intenta GOOGLE_OAUTH_CLIENT_SECRETS_JSON (contenido JSON)
    2) Luego GOOGLE_OAUTH_CLIENT_SECRETS_FILE (ruta a archivo)
    """
    js = getattr(settings, "GOOGLE_OAUTH_CLIENT_SECRETS_JSON", "") or os.getenv("GOOGLE_OAUTH_CLIENT_SECRETS_JSON", "")
    if js:
        try:
            return json.loads(js)
        except Exception:
            pass

    path = getattr(settings, "GOOGLE_OAUTH_CLIENT_SECRETS_FILE", "") or os.getenv("GOOGLE_OAUTH_CLIENT_SECRETS_FILE", "")
    if path and os.path.exists(path):
        with open(path, "r", encoding="utf-8") as f:
            return json.load(f)

    return None


def _redirect_uri(request):
    # Debe coincidir exactamente con lo registrado en Google Cloud Console
    return request.build_absolute_uri(reverse("accounts:google_callback"))


def _fmt_dt(value):
    """Formatea dateTime/date de Google a algo legible."""
    if not value:
        return "—"
    if "dateTime" in value and value["dateTime"]:
        try:
            dt = datetime.fromisoformat(value["dateTime"].replace("Z", "+00:00"))
            return timezone.localtime(dt).strftime("%d-%m-%Y %H:%M")
        except Exception:
            return value["dateTime"]
    if "date" in value and value["date"]:
        return f"{value['date']} (todo el día)"
    return "—"



def _db_get_user_creds(user):
    try:
        tok = GoogleOAuthToken.objects.get(user=user)
        return Credentials.from_authorized_user_info(json.loads(tok.credentials_json), SCOPES)
    except GoogleOAuthToken.DoesNotExist:
        return None

def _db_save_user_creds(user, creds):
    data = creds.to_json()
    GoogleOAuthToken.objects.update_or_create(
        user=user,
        defaults={"credentials_json": data},
    )

def _db_clear_user_creds(user):
    GoogleOAuthToken.objects.filter(user=user).delete()


# =========================
# Helpers OAuth / sesión
# =========================
def _clear_google_session(request):
    """Elimina claves de sesión relacionadas a OAuth para evitar loops."""
    for k in ("google_creds", "google_oauth_state", "google_oauth_redirect_uri", "oauth_retry_once"):
        request.session.pop(k, None)
    request.session.modified = True


def _get_valid_creds(request):
    """
    1) Intenta sesión (rápido).
    2) Si no hay, intenta BD por usuario.
    3) Si expira y hay refresh_token, refresca y guarda de vuelta (sesión + BD).
    """
    creds = None

    # 1) sesión
    data = request.session.get("google_creds")
    if data:
        try:
            creds = Credentials.from_authorized_user_info(json.loads(data), SCOPES)
        except Exception:
            creds = None

    # 2) BD
    if not creds and request.user.is_authenticated:
        creds = _db_get_user_creds(request.user)
        if creds:
            request.session["google_creds"] = creds.to_json()

    if not creds:
        return None

    # Refresh si corresponde
    if creds.expired:
        if not creds.refresh_token:
            return None
        creds.refresh(GoogleRequest())
        # persistir
        request.session["google_creds"] = creds.to_json()
        if request.user.is_authenticated:
            _db_save_user_creds(request.user, creds)

    # Verificar scope mínimo
    scopes = set(getattr(creds, "scopes", []) or [])
    if CAL_SCOPE not in scopes and not any(s.startswith(CAL_SCOPE + ".") for s in scopes):
        return None

    return creds

# =========================
# Flujo OAuth
# =========================
@login_required
def conectar_google_calendar(request):
    """
    Inicia el flujo OAuth en Google.
    Si ya hay credenciales válidas, redirige a listado (evita bucle).
    """
    try:
        existing = _get_valid_creds(request)
        if existing and not existing.expired:
            return redirect("accounts:gcal_eventos")
    except Exception:
        pass

    # Limpiar estado previo del flujo
    request.session.pop("google_oauth_state", None)
    request.session.pop("google_oauth_redirect_uri", None)

    cfg = _load_client_config()
    if not cfg:
        messages.error(request, "No se encontraron credenciales OAuth de Google.")
        return redirect("accounts:gcal_eventos")

    flow = Flow.from_client_config(cfg, scopes=SCOPES, redirect_uri=_redirect_uri(request))
    # No usamos include_granted_scopes para evitar unión con otros permisos (Drive, etc.)
    auth_url, state = flow.authorization_url(
        access_type="offline",
        prompt="consent",  # asegura refresh_token en dev
        # include_granted_scopes="true",  # ❌ NO usar, provoca “Scope has changed…”
    )
    request.session["google_oauth_state"] = state
    request.session["google_oauth_redirect_uri"] = _redirect_uri(request)
    request.session.modified = True
    return redirect(auth_url)


def google_callback(request):
    cfg = _load_client_config()
    if not cfg:
        messages.error(request, "No se encontraron credenciales OAuth de Google.")
        return redirect("accounts:gcal_eventos")

    state = request.session.get("google_oauth_state")
    redirect_uri = request.session.get("google_oauth_redirect_uri")
    if not state or not redirect_uri:
        messages.error(request, "Sesión OAuth inválida. Vuelve a conectar el calendario.")
        return redirect("accounts:gcal_eventos")

    flow = Flow.from_client_config(cfg, scopes=SCOPES, state=state, redirect_uri=redirect_uri)
    try:
        flow.fetch_token(authorization_response=request.build_absolute_uri())
    except GoogleAuthError as e:
        messages.error(request, f"Error de autenticación con Google: {e}")
        return redirect("accounts:gcal_eventos")
    except Exception as e:
        messages.error(request, f"No se pudo completar el intercambio de token: {e}")
        return redirect("accounts:gcal_eventos")

    creds = flow.credentials
    if not creds.refresh_token:
        request.session.pop("google_creds", None)
        messages.warning(request, "No se recibió refresh_token. Vuelve a conectar y acepta permisos.")
        return redirect("accounts:gcal_eventos")

    # Guarda en sesión (opcional) y BD (persistente por usuario)
    request.session["google_creds"] = creds.to_json()
    if request.user.is_authenticated:
        _db_save_user_creds(request.user, creds)

    messages.success(request, "Google Calendar conectado correctamente.")
    return redirect("accounts:gcal_eventos")

@login_required
def google_disconnect(request):
    _clear_google_session(request)
    if request.user.is_authenticated:
        _db_clear_user_creds(request.user)  # ← borra vinculación permanente
    messages.info(request, "Se desconectó Google Calendar.")
    return redirect("accounts:gcal_eventos")

@login_required
def google_reconnect(request):
    _clear_google_session(request)
    if request.user.is_authenticated:
        _db_clear_user_creds(request.user)  # limpia también BD
    messages.info(request, "Vamos a reconectar Google Calendar.")
    return redirect("accounts:google_connect")


# =========================
# Vistas de eventos
# =========================
@login_required
def gcal_eventos(request):
    """
    Si no hay token válido, NO redirige automáticamente: muestra página con botones.
    """
    connected = False
    events = []
    error_msg = None

    creds = _get_valid_creds(request)
    if creds:
        try:
            service = build("calendar", "v3", credentials=creds)
            now_iso = timezone.now().isoformat()
            res = service.events().list(
                calendarId="primary",
                timeMin=now_iso,
                singleEvents=True,
                orderBy="startTime",
                maxResults=10,
            ).execute()
            events = res.get("items", [])
            connected = True
        except RefreshError:
            _clear_google_session(request)
            error_msg = "El token expiró o fue revocado. Vuelve a conectar tu Google Calendar."
        except HttpError as e:
            error_msg = f"No se pudieron obtener eventos: {e}"
        except Exception as e:
            error_msg = f"No se pudieron obtener eventos: {e}"

    ctx = {
        "events": events,
        "connected": connected,
        "error_msg": error_msg,
        "_fmt_dt": _fmt_dt,  # por si quieres usarlo en el template
    }
    return render(request, "accounts/gcal_eventos.html", ctx)


@require_http_methods(["GET", "POST"])
def gcal_crear_evento(request):
    """Crea un nuevo evento en Google Calendar."""
    if request.method == "POST":
        try:
            creds = _get_valid_creds(request)
            if not creds:
                messages.error(request, "Primero debes conectar tu Google Calendar.")
                return redirect("accounts:gcal_eventos")

            service = build("calendar", "v3", credentials=creds)

            summary = (request.POST.get("summary") or "").strip()
            if not summary:
                messages.error(request, "El título del evento es obligatorio.")
                return redirect("accounts:gcal_crear_evento")

            tz = "America/Santiago"
            if "all_day" in request.POST:
                start = {"date": request.POST.get("start_date"), "timeZone": tz}
                end   = {"date": request.POST.get("end_date"),   "timeZone": tz}
            else:
                start_dt = datetime.fromisoformat(request.POST.get("start_dt"))
                end_dt   = datetime.fromisoformat(request.POST.get("end_dt"))
                start = {"dateTime": start_dt.isoformat(), "timeZone": tz}
                end   = {"dateTime": end_dt.isoformat(),   "timeZone": tz}

            attendees_raw = (request.POST.get("attendees") or "").strip()
            attendees = [{"email": e.strip()} for e in attendees_raw.split(",") if e.strip()]

            reminders = {"useDefault": True}
            if request.POST.get("reminder_popup") or request.POST.get("reminder_email"):
                reminders = {"useDefault": False, "overrides": []}
                if request.POST.get("reminder_popup"):
                    reminders["overrides"].append({"method": "popup", "minutes": int(request.POST["reminder_popup"])})
                if request.POST.get("reminder_email"):
                    reminders["overrides"].append({"method": "email", "minutes": int(request.POST["reminder_email"])})

            event_data = {
                "summary": summary,
                "location": (request.POST.get("location") or None),
                "description": (request.POST.get("description") or None),
                "start": start,
                "end": end,
                "attendees": attendees or None,
                "reminders": reminders,
                "visibility": request.POST.get("visibility") or "default",
            }

            calendar_id = request.POST.get("calendar_id", "primary")
            service.events().insert(calendarId=calendar_id, body=event_data).execute()
            messages.success(request, "Evento creado correctamente.")
            return redirect("accounts:gcal_eventos")

        except RefreshError:
            messages.error(request, "El token fue revocado o expiró. Vuelve a conectar tu Google Calendar.")
            _clear_google_session(request)
            return redirect("accounts:google_connect")
        except HttpError as e:
            messages.error(request, f"Error de API de Google Calendar: {e}")
            return redirect("accounts:gcal_eventos")
        except Exception as e:
            messages.error(request, f"Error al crear el evento: {e}")
            return redirect("accounts:gcal_eventos")

    # GET -> formulario
    return render(request, "accounts/gcal_crear_evento.html")


def _event_initial_from_google(event):
    """Mapea el evento de Google a initial para el formulario de edición."""
    init = {
        "summary": event.get("summary", ""),
        "location": event.get("location", ""),
        "description": event.get("description", ""),
        "visibility": event.get("visibility", "default"),
        "attendees": ", ".join([a.get("email", "") for a in event.get("attendees", []) if a.get("email")]),
        "all_day": False,
        "start_date": "",
        "end_date": "",
        "start_dt": "",
        "end_dt": "",
    }
    start = event.get("start") or {}
    end = event.get("end") or {}
    if "date" in start or "date" in end:
        init["all_day"] = True
        init["start_date"] = start.get("date", "")
        init["end_date"] = end.get("date", "")
    else:
        init["start_dt"] = (start.get("dateTime") or "").replace("Z", "+00:00")
        init["end_dt"] = (end.get("dateTime") or "").replace("Z", "+00:00")
    return init

@login_required
def gcal_event_detail(request, event_id):
    """Muestra detalle de un evento (acepta ?calendar_id=..., por defecto 'primary')."""
    calendar_id = request.GET.get("calendar_id", "primary")
    try:
        creds = _get_valid_creds(request)
        if not creds:
            messages.error(request, "Primero debes conectar tu Google Calendar.")
            return redirect("accounts:gcal_eventos")

        service = build("calendar", "v3", credentials=creds)
        event = service.events().get(calendarId=calendar_id, eventId=event_id).execute()

        ctx = {
            "event": event,
            "calendar_id": calendar_id,
            "start_txt": _fmt_dt(event.get("start")),
            "end_txt": _fmt_dt(event.get("end")),
            "attendees": event.get("attendees", []),
            "reminders": event.get("reminders", {}),
        }
        return render(request, "accounts/gcal_event_detail.html", ctx)

    except RefreshError:
        messages.error(request, "El token fue revocado o expiró. Vuelve a conectar tu Google Calendar.")
        _clear_google_session(request)
        return redirect("accounts:google_connect")
    except HttpError as e:
        messages.error(request, f"No se pudo obtener el evento: {e}")
        return redirect("accounts:gcal_eventos")
    except Exception as e:
        messages.error(request, f"Error: {e}")
        return redirect("accounts:gcal_eventos")


@require_http_methods(["GET", "POST"])
def gcal_event_edit(request, event_id):
    """Edita un evento existente (acepta ?calendar_id=..., por defecto 'primary')."""
    calendar_id = request.GET.get("calendar_id", "primary")
    try:
        creds = _get_valid_creds(request)
        if not creds:
            messages.error(request, "Primero debes conectar tu Google Calendar.")
            return redirect("accounts:gcal_eventos")

        service = build("calendar", "v3", credentials=creds)
        event = service.events().get(calendarId=calendar_id, eventId=event_id).execute()

        if request.method == "POST":
            summary = (request.POST.get("summary") or "").strip()
            if not summary:
                messages.error(request, "El título es obligatorio.")
                return redirect(request.path + f"?calendar_id={calendar_id}")

            tz = "America/Santiago"
            if "all_day" in request.POST:
                start = {"date": request.POST.get("start_date"), "timeZone": tz}
                end   = {"date": request.POST.get("end_date"),   "timeZone": tz}
            else:
                start_dt = datetime.fromisoformat(request.POST.get("start_dt"))
                end_dt   = datetime.fromisoformat(request.POST.get("end_dt"))
                start = {"dateTime": start_dt.isoformat(), "timeZone": tz}
                end   = {"dateTime": end_dt.isoformat(),   "timeZone": tz}

            attendees_raw = (request.POST.get("attendees") or "").strip()
            attendees = [{"email": e.strip()} for e in attendees_raw.split(",") if e.strip()]

            reminders = {"useDefault": True}
            if request.POST.get("reminder_popup") or request.POST.get("reminder_email"):
                reminders = {"useDefault": False, "overrides": []}
                if request.POST.get("reminder_popup"):
                    reminders["overrides"].append({"method": "popup", "minutes": int(request.POST["reminder_popup"])})
                if request.POST.get("reminder_email"):
                    reminders["overrides"].append({"method": "email", "minutes": int(request.POST["reminder_email"])})

            patch = {
                "summary": summary,
                "location": (request.POST.get("location") or None),
                "description": (request.POST.get("description") or None),
                "start": start,
                "end": end,
                "attendees": attendees or None,
                "reminders": reminders,
                "visibility": request.POST.get("visibility") or "default",
            }

            service.events().patch(calendarId=calendar_id, eventId=event_id, body=patch).execute()
            messages.success(request, "Evento actualizado correctamente.")
            return redirect(f"{reverse('accounts:gcal_event_detail', args=[event_id])}?calendar_id={calendar_id}")

        # GET: pintar formulario con datos actuales
        initial = _event_initial_from_google(event)
        return render(
            request,
            "accounts/gcal_event_edit.html",
            {"event": event, "calendar_id": calendar_id, "initial": initial},
        )

    except RefreshError:
        messages.error(request, "El token fue revocado o expiró. Vuelve a conectar tu Google Calendar.")
        _clear_google_session(request)
        return redirect("accounts:google_connect")
    except HttpError as e:
        messages.error(request, f"No se pudo editar el evento: {e}")
        return redirect("accounts:gcal_eventos")
    except Exception as e:
        messages.error(request, f"Error: {e}")
        return redirect("accounts:gcal_eventos")


@require_http_methods(["POST"])
@login_required
def gcal_event_delete(request, event_id):
    """Elimina un evento. Recibe calendar_id en POST (por defecto 'primary')."""
    calendar_id = request.POST.get("calendar_id", "primary")
    try:
        creds = _get_valid_creds(request)
        if not creds:
            messages.error(request, "Primero debes conectar tu Google Calendar.")
            return redirect("accounts:gcal_eventos")

        service = build("calendar", "v3", credentials=creds)
        service.events().delete(calendarId=calendar_id, eventId=event_id).execute()
        messages.success(request, "Evento eliminado.")
        return redirect("accounts:gcal_eventos")

    except RefreshError:
        messages.error(request, "El token fue revocado o expiró. Vuelve a conectar tu Google Calendar.")
        _clear_google_session(request)
        return redirect("accounts:google_connect")
    except HttpError as e:
        messages.error(request, f"No se pudo eliminar el evento: {e}")
        return redirect("accounts:gcal_eventos")
    except Exception as e:
        messages.error(request, f"Error: {e}")
        return redirect("accounts:gcal_eventos")
