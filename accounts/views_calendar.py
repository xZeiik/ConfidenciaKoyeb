# accounts/views_calendar.py
from __future__ import annotations

import json
import os
from datetime import datetime

from django.conf import settings
from django.contrib import messages
from django.contrib.auth.decorators import login_required
from django.http import HttpResponseBadRequest
from django.shortcuts import redirect, render
from django.urls import reverse
from django.utils import timezone
from django.views.decorators.http import require_http_methods

from google_auth_oauthlib.flow import Flow
from google.oauth2.credentials import Credentials
from googleapiclient.discovery import build
from google.auth.transport.requests import Request as GoogleRequest
from google.auth.exceptions import RefreshError

from .models import GoogleOAuthToken  # tabla para persistir tokens por usuario

# =========================
# Scopes (RO/RW por env)
# =========================
_CAL_RW = os.getenv("GOOGLE_CAL_RW", "0") in ("1", "true", "True")
CAL_SCOPES = (
    ["https://www.googleapis.com/auth/calendar.events"]  # RW
    if _CAL_RW else
    ["https://www.googleapis.com/auth/calendar.readonly"]  # RO
)

# =========================
# Helpers de configuración
# =========================
def _client_secrets_path() -> str:
    """
    settings.py ya resolvió GOOGLE_OAUTH_CLIENT_SECRETS_FILE desde:
      - GOOGLE_OAUTH_CLIENT(SECRETS)_JSON (inline → tmp file), o
      - keys/client_secret_web.json
    """
    path = getattr(settings, "GOOGLE_OAUTH_CLIENT_SECRETS_FILE", "").strip()
    if not path:
        raise RuntimeError(
            "Falta GOOGLE_OAUTH_CLIENT_SECRETS_FILE/JSON. "
            "Sube keys/client_secret_web.json o define GOOGLE_OAUTH_CLIENT_SECRETS_JSON."
        )
    if not os.path.exists(path):
        raise RuntimeError(f"El archivo de client secrets no existe: {path}")
    return path

def _redirect_uri(request):
    # Debe coincidir EXACTO con el registrado en Google Cloud
    # (p.ej. https://confidencia.azurewebsites.net/accounts/google/callback/)
    return request.build_absolute_uri(reverse("accounts:google_callback"))

def _fmt_dt(value):
    """Formatea dateTime/date de Google en horario local."""
    if not value:
        return "—"
    if "dateTime" in value and value["dateTime"]:
        try:
            dt = datetime.fromisoformat(value["dateTime"].replace("Z", "+00:00"))
            if timezone.is_naive(dt):
                dt = timezone.make_aware(dt, timezone=timezone.utc)
            return timezone.localtime(dt).strftime("%d-%m-%Y %H:%M")
        except Exception:
            return value["dateTime"]
    if "date" in value and value["date"]:
        return f"{value['date']} (todo el día)"
    return "—"

# =========================
# Persistencia en BD
# =========================
def _db_get_user_creds(user):
    try:
        tok = GoogleOAuthToken.objects.get(user=user)
        return Credentials.from_authorized_user_info(json.loads(tok.credentials_json), CAL_SCOPES)
    except GoogleOAuthToken.DoesNotExist:
        return None

def _db_save_user_creds(user, creds: Credentials):
    GoogleOAuthToken.objects.update_or_create(
        user=user,
        defaults={"credentials_json": creds.to_json()},
    )

def _db_clear_user_creds(user):
    GoogleOAuthToken.objects.filter(user=user).delete()

# =========================
# Sesión / Creds válidas
# =========================
def _clear_google_session(request):
    for k in ("google_creds", "google_oauth_state", "google_oauth_redirect_uri"):
        request.session.pop(k, None)
    request.session.modified = True

def _get_valid_creds(request):
    """
    1) Intenta sesión → 2) BD → 3) refresca si expirada (con refresh_token).
    Valida que el scope actual incluya el requerido.
    """
    creds = None

    # 1) sesión
    raw = request.session.get("google_creds")
    if raw:
        try:
            creds = Credentials.from_authorized_user_info(json.loads(raw), CAL_SCOPES)
        except Exception:
            creds = None

    # 2) BD
    if not creds and request.user.is_authenticated:
        creds = _db_get_user_creds(request.user)
        if creds:
            request.session["google_creds"] = creds.to_json()

    if not creds:
        return None

    # 3) refresh si expiró
    if creds.expired:
        if not creds.refresh_token:
            return None
        creds.refresh(GoogleRequest())
        request.session["google_creds"] = creds.to_json()
        if request.user.is_authenticated:
            _db_save_user_creds(request.user, creds)

    # 4) verificar scope
    scopes = set(getattr(creds, "scopes", []) or [])
    if not any(s in scopes for s in CAL_SCOPES):
        return None

    return creds

# =========================
# Flujo OAuth
# =========================
@login_required
def google_connect(request):
    """
    Inicia OAuth. Si ya hay token válido, va directo a eventos.
    """
    existing = _get_valid_creds(request)
    if existing and not existing.expired:
        return redirect("accounts:gcal_eventos")

    # limpiar estado
    request.session.pop("google_oauth_state", None)
    request.session.pop("google_oauth_redirect_uri", None)

    try:
        flow = Flow.from_client_secrets_file(
            _client_secrets_path(),
            scopes=CAL_SCOPES,
            redirect_uri=_redirect_uri(request),
        )
    except Exception as e:
        messages.error(request, f"No se encontraron credenciales OAuth de Google: {e}")
        return redirect("accounts:gcal_eventos")

    auth_url, state = flow.authorization_url(
        access_type="offline",
        prompt="consent",           # asegura refresh_token si no existía
        include_granted_scopes=False
    )
    request.session["google_oauth_state"] = state
    request.session["google_oauth_redirect_uri"] = _redirect_uri(request)
    request.session.modified = True
    return redirect(auth_url)

@login_required
def google_callback(request):
    state = request.session.get("google_oauth_state")
    redirect_uri = request.session.get("google_oauth_redirect_uri")
    if not state or not redirect_uri:
        messages.error(request, "Sesión OAuth inválida. Vuelve a conectar el calendario.")
        return redirect("accounts:gcal_eventos")

    try:
        flow = Flow.from_client_secrets_file(
            _client_secrets_path(),
            scopes=CAL_SCOPES,
            state=state,
            redirect_uri=redirect_uri,
        )
        flow.fetch_token(authorization_response=request.build_absolute_uri())
        creds = flow.credentials
    except Exception as e:
        messages.error(request, f"No se pudo completar el intercambio de token: {e}")
        return redirect("accounts:gcal_eventos")

    if not creds.refresh_token:
        _clear_google_session(request)
        messages.warning(request, "No se recibió refresh_token. Vuelve a conectar y concede permisos.")
        return redirect("accounts:gcal_eventos")

    request.session["google_creds"] = creds.to_json()
    _db_save_user_creds(request.user, creds)

    messages.success(request, "Google Calendar conectado correctamente.")
    return redirect("accounts:gcal_eventos")

@login_required
def google_disconnect(request):
    _clear_google_session(request)
    _db_clear_user_creds(request.user)
    messages.info(request, "Se desconectó Google Calendar.")
    return redirect("accounts:gcal_eventos")

@login_required
def google_reconnect(request):
    _clear_google_session(request)
    _db_clear_user_creds(request.user)
    messages.info(request, "Vamos a reconectar Google Calendar.")
    return redirect("accounts:google_connect")

# =========================
# Vistas de eventos
# =========================
@login_required
def gcal_eventos(request):
    """
    Si no hay token válido, se muestra página con botones (no redirige solo).
    """
    connected, events, error_msg = False, [], None
    creds = _get_valid_creds(request)
    if creds:
        try:
            service = build("calendar", "v3", credentials=creds, cache_discovery=False)
            now_iso = timezone.now().astimezone(timezone.utc).isoformat()
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
            _db_clear_user_creds(request.user)
            error_msg = "El token expiró o fue revocado. Vuelve a conectar tu Google Calendar."
        except Exception as e:
            error_msg = f"No se pudieron obtener eventos: {e}"

    ctx = {"events": events, "connected": connected, "error_msg": error_msg, "_fmt_dt": _fmt_dt}
    return render(request, "accounts/gcal_eventos.html", ctx)

@require_http_methods(["GET", "POST"])
@login_required
def gcal_crear_evento(request):
    """Crea evento en Google Calendar."""
    if request.method == "POST":
        try:
            creds = _get_valid_creds(request)
            if not creds:
                messages.error(request, "Primero debes conectar tu Google Calendar.")
                return redirect("accounts:gcal_eventos")

            service = build("calendar", "v3", credentials=creds, cache_discovery=False)

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
            _db_clear_user_creds(request.user)
            return redirect("accounts:google_connect")
        except Exception as e:
            messages.error(request, f"Error al crear el evento: {e}")
            return redirect("accounts:gcal_eventos")

    # GET -> formulario
    return render(request, "accounts/gcal_crear_evento.html")

def _event_initial_from_google(event):
    """Mapea evento de Google → initial del form de edición."""
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
    """Detalle de un evento (?calendar_id=..., por defecto 'primary')."""
    calendar_id = request.GET.get("calendar_id", "primary")
    try:
        creds = _get_valid_creds(request)
        if not creds:
            messages.error(request, "Primero debes conectar tu Google Calendar.")
            return redirect("accounts:gcal_eventos")

        service = build("calendar", "v3", credentials=creds, cache_discovery=False)
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
        _db_clear_user_creds(request.user)
        return redirect("accounts:google_connect")
    except Exception as e:
        messages.error(request, f"No se pudo obtener el evento: {e}")
        return redirect("accounts:gcal_eventos")

@require_http_methods(["GET", "POST"])
@login_required
def gcal_event_edit(request, event_id):
    """Edita evento existente (?calendar_id=..., por defecto 'primary')."""
    calendar_id = request.GET.get("calendar_id", "primary")
    try:
        creds = _get_valid_creds(request)
        if not creds:
            messages.error(request, "Primero debes conectar tu Google Calendar.")
            return redirect("accounts:gcal_eventos")

        service = build("calendar", "v3", credentials=creds, cache_discovery=False)
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

        # GET
        initial = _event_initial_from_google(event)
        return render(
            request,
            "accounts/gcal_event_edit.html",
            {"event": event, "calendar_id": calendar_id, "initial": initial},
        )

    except RefreshError:
        messages.error(request, "El token fue revocado o expiró. Vuelve a conectar tu Google Calendar.")
        _clear_google_session(request)
        _db_clear_user_creds(request.user)
        return redirect("accounts:google_connect")
    except Exception as e:
        messages.error(request, f"No se pudo editar el evento: {e}")
        return redirect("accounts:gcal_eventos")

@require_http_methods(["POST"])
@login_required
def gcal_event_delete(request, event_id):
    """Elimina un evento (POST con calendar_id, por defecto 'primary')."""
    calendar_id = request.POST.get("calendar_id", "primary")
    try:
        creds = _get_valid_creds(request)
        if not creds:
            messages.error(request, "Primero debes conectar tu Google Calendar.")
            return redirect("accounts:gcal_eventos")

        service = build("calendar", "v3", credentials=creds, cache_discovery=False)
        service.events().delete(calendarId=calendar_id, eventId=event_id).execute()
        messages.success(request, "Evento eliminado.")
        return redirect("accounts:gcal_eventos")

    except RefreshError:
        messages.error(request, "El token fue revocado o expiró. Vuelve a conectar tu Google Calendar.")
        _clear_google_session(request)
        _db_clear_user_creds(request.user)
        return redirect("accounts:google_connect")
    except Exception as e:
        messages.error(request, f"No se pudo eliminar el evento: {e}")
        return redirect("accounts:gcal_eventos")

