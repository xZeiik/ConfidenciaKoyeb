# google_calendar.py
from __future__ import annotations

import os
from pathlib import Path
from typing import Optional, Tuple

from django.conf import settings
from google_auth_oauthlib.flow import Flow
from google.oauth2.credentials import Credentials
from googleapiclient.discovery import build

# Ajusta scopes según necesidad (RW o RO)
CAL_SCOPES = [
    # "https://www.googleapis.com/auth/calendar.events",  # RW
    "https://www.googleapis.com/auth/calendar.readonly",  # RO
]

# ---------------------------
# Ubicaciones persistentes
# ---------------------------

def _tokens_dir() -> Path:
    base = os.getenv("GOOGLE_TOKENS_DIR", "/home/site/wwwroot/keys/tokens")
    p = Path(base)
    p.mkdir(parents=True, exist_ok=True)
    return p

def _client_secrets_path() -> str:
    """
    settings.py ya resolvió GOOGLE_OAUTH_CLIENT_SECRETS_FILE
    desde:
      - GOOGLE_OAUTH_CLIENT_SECRETS_JSON / GOOGLE_OAUTH_CLIENT_JSON (inline → tmp file)
      - keys/client_secret_web.json
    """
    path = getattr(settings, "GOOGLE_OAUTH_CLIENT_SECRETS_FILE", "").strip()
    if not path or not Path(path).exists():
        raise RuntimeError(
            "Falta GOOGLE_OAUTH_CLIENT_SECRETS_FILE/JSON para Calendar OAuth. "
            "Define GOOGLE_OAUTH_CLIENT_SECRETS_JSON o sube keys/client_secret_web.json."
        )
    return path

def token_file_for_user(user_id: int) -> Path:
    return _tokens_dir() / f"user_{user_id}.json"

# ---------------------------
# Flujo OAuth
# ---------------------------

def build_flow(state: Optional[str] = None) -> Flow:
    return Flow.from_client_secrets_file(
        _client_secrets_path(),
        scopes=CAL_SCOPES,
        redirect_uri=settings.GOOGLE_REDIRECT_URI,
        state=state
    )

def authorization_url(state: Optional[str] = None, login_hint: Optional[str] = None) -> Tuple[str, str]:
    """
    Devuelve (auth_url, state). Guarda state para validarlo en el callback si lo usas.
    """
    flow = build_flow(state=state)
    # access_type="offline" para refresh_token
    # include_granted_scopes=True para incremental auth
    auth_url, new_state = flow.authorization_url(
        access_type="offline",
        include_granted_scopes=True,
        prompt="consent",           # fuerza refresh_token si no existe
        login_hint=login_hint or None
    )
    return auth_url, new_state

def exchange_code_for_credentials(code: str) -> Credentials:
    flow = build_flow()
    flow.fetch_token(code=code)
    return flow.credentials

# ---------------------------
# Tokens por usuario
# ---------------------------

def get_user_creds(user_id: int) -> Optional[Credentials]:
    tf = token_file_for_user(user_id)
    if tf.exists():
        try:
            return Credentials.from_authorized_user_file(str(tf), CAL_SCOPES)
        except Exception:
            # Token corrupto → lo ignoramos
            return None
    return None

def save_user_creds(user_id: int, creds: Credentials) -> None:
    tf = token_file_for_user(user_id)
    tf.write_text(creds.to_json(), encoding="utf-8")

def get_calendar_service(user_id: int):
    """
    Obtiene el servicio Calendar para el usuario (requiere token previamente guardado).
    """
    creds = get_user_creds(user_id)
    if not creds or not creds.valid:
        # Nota: aquí podrías intentar creds.refresh(Request()) si prefieres refrescar silenciosamente.
        raise RuntimeError("No hay token válido de Google Calendar para este usuario. Debe conectar su cuenta.")
    return build("calendar", "v3", credentials=creds, cache_discovery=False)

# ---------------------------
# Utilidades de alto nivel
# ---------------------------

def list_upcoming_events(user_id: int, max_results: int = 10, calendar_id: str = "primary") -> list:
    """
    Lista próximos eventos del usuario.
    """
    from datetime import datetime, timezone
    service = get_calendar_service(user_id)
    now_iso = datetime.now(timezone.utc).isoformat()

    events_result = service.events().list(
        calendarId=calendar_id,
        timeMin=now_iso,
        maxResults=max_results,
        singleEvents=True,
        orderBy="startTime",
    ).execute()

    return events_result.get("items", [])

