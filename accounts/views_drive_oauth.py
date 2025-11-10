# accounts/views_drive_oauth.py
import pickle
from pathlib import Path
from django.conf import settings
from django.http import HttpResponse, HttpResponseBadRequest, HttpResponseRedirect
from django.urls import reverse
from google_auth_oauthlib.flow import Flow
from google.oauth2.credentials import Credentials
from google.auth.transport.requests import Request as GoogleRequest
from googleapiclient.discovery import build

# Dónde se guarda el token OAuth (un único owner para la app)
TOKEN_PATH = Path(getattr(settings, "GOOGLE_TOKEN_FILE", str(Path(settings.BASE_DIR) / "keys" / "token.json")))
CLIENT_FILE = getattr(settings, "GOOGLE_OAUTH_CLIENT_SECRETS_FILE", "")
SCOPES = ["https://www.googleapis.com/auth/drive"]

def _resolve_redirect_uri(request):
    """
    Usa settings.GOOGLE_DRIVE_REDIRECT_URI si existe; si no, construye la URL del callback por reverse.
    """
    configured = getattr(settings, "GOOGLE_DRIVE_REDIRECT_URI", "").strip()
    if configured:
        return configured
    return request.build_absolute_uri(reverse("accounts:google_drive_callback"))

def google_drive_connect(request):
    if not CLIENT_FILE or not Path(CLIENT_FILE).exists():
        return HttpResponseBadRequest("Falta keys/client_secret_web.json o GOOGLE_OAUTH_CLIENT_SECRETS_FILE.")
    redirect_uri = _resolve_redirect_uri(request)
    flow = Flow.from_client_secrets_file(CLIENT_FILE, scopes=SCOPES, redirect_uri=redirect_uri)
    auth_url, state = flow.authorization_url(
        access_type="offline", include_granted_scopes="true", prompt="consent"
    )
    request.session["google_drive_oauth_state"] = state
    return HttpResponseRedirect(auth_url)

def google_drive_callback(request):
    state = request.session.get("google_drive_oauth_state")
    if not state:
        return HttpResponseBadRequest("Estado OAuth inválido. Inicia la conexión nuevamente.")
    if not CLIENT_FILE or not Path(CLIENT_FILE).exists():
        return HttpResponseBadRequest("Falta keys/client_secret_web.json o GOOGLE_OAUTH_CLIENT_SECRETS_FILE.")
    redirect_uri = _resolve_redirect_uri(request)
    flow = Flow.from_client_secrets_file(CLIENT_FILE, scopes=SCOPES, redirect_uri=redirect_uri, state=state)
    flow.fetch_token(authorization_response=request.build_absolute_uri())
    creds = flow.credentials
    TOKEN_PATH.parent.mkdir(parents=True, exist_ok=True)
    with open(TOKEN_PATH, "wb") as f:
        pickle.dump(creds, f)
    return HttpResponse("✅ Google Drive autorizado. Ya puedes subir archivos desde la app.")

def google_drive_disconnect(request):
    if TOKEN_PATH.exists():
        TOKEN_PATH.unlink()
    return HttpResponse("🔌 Token de Google Drive eliminado.")

def google_whoami(request):
    if not TOKEN_PATH.exists():
        return HttpResponseBadRequest("No hay token guardado. Conecta primero.")
    with open(TOKEN_PATH, "rb") as f:
        creds: Credentials = pickle.load(f)
    if getattr(creds, "expired", False) and getattr(creds, "refresh_token", None):
        creds.refresh(GoogleRequest())
        with open(TOKEN_PATH, "wb") as f:
            pickle.dump(creds, f)
    svc = build("drive", "v3", credentials=creds, cache_discovery=False)
    about = svc.about().get(fields="user(emailAddress,displayName)").execute()
    return HttpResponse(str(about))
