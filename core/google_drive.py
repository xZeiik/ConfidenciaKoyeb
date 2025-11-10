# core/google_drive.py
from __future__ import annotations

import io
import os
import json
from pathlib import Path
from typing import Dict, List, Optional

from django.conf import settings
from googleapiclient.discovery import build
from googleapiclient.http import MediaFileUpload, MediaIoBaseDownload
from google.oauth2.credentials import Credentials
from google.auth.transport.requests import Request as GoogleRequest

# Permisos acotados a archivos que crea la app
SCOPES = ["https://www.googleapis.com/auth/drive.file"]


# ---------------------------
# Helpers de rutas / claves
# ---------------------------

def _keys_dir() -> Path:
    try:
        return Path(settings.BASE_DIR) / "keys"
    except Exception:
        return Path.cwd() / "keys"

def _token_path() -> Path:
    # Si settings define GOOGLE_TOKEN_FILE, úsalo; si no, /keys/token.json
    p = getattr(settings, "GOOGLE_TOKEN_FILE", "")
    return Path(p) if p else (_keys_dir() / "token.json")

def _client_secret_path() -> Optional[str]:
    """
    Ruta al client_secret_web.json para el flujo local (solo si DEV_USE_OAUTH=1).
    Busca en:
      1) settings.GOOGLE_OAUTH_CLIENT_SECRETS_FILE
      2) settings.GOOGLE_OAUTH_CLIENT_FILE (compat)
      3) /keys/client_secret_web.json
      4) env GOOGLE_OAUTH_CLIENT_SECRETS_FILE / GOOGLE_OAUTH_CLIENT_FILE
    """
    c = (
        getattr(settings, "GOOGLE_OAUTH_CLIENT_SECRETS_FILE", "")
        or getattr(settings, "GOOGLE_OAUTH_CLIENT_FILE", "")
        or str(_keys_dir() / "client_secret_web.json")
        or os.getenv("GOOGLE_OAUTH_CLIENT_SECRETS_FILE", "")
        or os.getenv("GOOGLE_OAUTH_CLIENT_FILE", "")
    )
    c = str(c).strip()
    return c if c and Path(c).exists() else None

def _sa_file_path() -> Optional[str]:
    """
    Ruta a service_account.json si existe:
      1) GOOGLE_APPLICATION_CREDENTIALS
      2) /keys/service_account.json
      3) settings.GOOGLE_SERVICE_ACCOUNT_FILE / env
    """
    gac = os.getenv("GOOGLE_APPLICATION_CREDENTIALS", "")
    if gac and Path(gac).exists():
        return gac
    p = _keys_dir() / "service_account.json"
    if p.exists():
        return str(p)
    f = (
        getattr(settings, "GOOGLE_SERVICE_ACCOUNT_FILE", "")
        or os.getenv("GOOGLE_SERVICE_ACCOUNT_FILE", "")
    ).strip()
    return f if f and Path(f).exists() else None

def _shared_drive_id() -> str:
    """ID de la unidad compartida (déjalo vacío para cuenta Gmail normal)."""
    return (
        getattr(settings, "GOOGLE_SHARED_DRIVE_ID", "")
        or os.getenv("GOOGLE_SHARED_DRIVE_ID", "")
        or ""
    ).strip()


# ---------------------------
# Credenciales
# ---------------------------

def _build_creds():
    """
    Orden:
      1) OAuth de usuario via keys/token.json (authorized_user JSON) → usa cuota del usuario (recomendado).
         - Se refresca y reescribe el token si expira.
      2) Si no hay token y DEV_USE_OAUTH=1 → iniciar flujo local con client_secret_web.json (solo entorno dev/local).
      3) Service Account (si existe). Útil para automatizaciones o si usas Shared Drive/impersonación.
    """
    # 1) OAuth con token.json
    tpath = _token_path()
    if tpath.exists():
        creds = Credentials.from_authorized_user_file(str(tpath), SCOPES)
        if getattr(creds, "expired", False) and getattr(creds, "refresh_token", None):
            creds.refresh(GoogleRequest())
            # reescribir token en formato JSON authorized_user
            tpath.parent.mkdir(parents=True, exist_ok=True)
            tpath.write_text(creds.to_json(), encoding="utf-8")
        return creds

    # 2) Flujo local si se habilita explícitamente
    if os.getenv("DEV_USE_OAUTH", "").lower() in ("1", "true", "yes"):
        from google_auth_oauthlib.flow import InstalledAppFlow
        client_path = _client_secret_path()
        if not client_path:
            raise RuntimeError("Falta keys/client_secret_web.json para iniciar OAuth (DEV_USE_OAUTH=1).")
        flow = InstalledAppFlow.from_client_secrets_file(client_path, SCOPES)
        creds = flow.run_local_server(port=0)
        # guardar token para futuros despliegues
        tpath.parent.mkdir(parents=True, exist_ok=True)
        tpath.write_text(creds.to_json(), encoding="utf-8")
        return creds

    # 3) Service Account (opcional)
    sa_json = os.getenv("GOOGLE_SERVICE_ACCOUNT_JSON", "").strip()
    imp = os.getenv("DRIVE_IMPERSONATE_EMAIL", "").strip()  # si usas domain-wide delegation
    if sa_json:
        from google.oauth2 import service_account
        info = json.loads(sa_json)
        creds = service_account.Credentials.from_service_account_info(info, scopes=SCOPES)
        return creds.with_subject(imp) if imp else creds

    sa_file = _sa_file_path()
    if sa_file:
        from google.oauth2 import service_account
        creds = service_account.Credentials.from_service_account_file(sa_file, scopes=SCOPES)
        return creds.with_subject(imp) if imp else creds

    raise RuntimeError(
        "No hay credenciales para Google Drive. "
        "Provee keys/token.json (OAuth) o una Service Account."
    )


# ---------------------------
# Servicio base / parámetros
# ---------------------------

def _svc():
    # cache_discovery=False reduce IO en Azure
    return build("drive", "v3", credentials=_build_creds(), cache_discovery=False)

def _with_drive_params(params: Dict) -> Dict:
    """Añade flags de Shared Drive solo si hay GOOGLE_SHARED_DRIVE_ID."""
    sd = _shared_drive_id()
    if sd:
        params.update({
            "corpora": "drive",
            "driveId": sd,
            "includeItemsFromAllDrives": True,
            "supportsAllDrives": True,
        })
    return params


# ---------------------------
# Operaciones principales
# ---------------------------

def list_root(max_items: int = 10) -> List[Dict]:
    """
    Lista archivos visibles en la raíz lógica.
    - Con Shared Drive: lista la raíz de la unidad compartida.
    - Sin Shared Drive: lista raíz del usuario (no recomendado) o filtra por tu carpeta raíz si la usas en consultas.
    """
    service = _svc()
    params = dict(pageSize=max_items, fields="files(id,name,mimeType,modifiedTime,webViewLink)")
    params = _with_drive_params(params)
    return service.files().list(**params).execute().get("files", [])

def ensure_folder(name: str, parent_id: Optional[str] = None) -> str:
    """Crea (o devuelve) una carpeta con nombre `name` (dentro de parent_id o de la raíz de la unidad)."""
    service = _svc()
    effective_parent = parent_id or (_shared_drive_id() or None)

    q = f"mimeType='application/vnd.google-apps.folder' and trashed=false and name='{name}'"
    if effective_parent:
        q += f" and '{effective_parent}' in parents"

    search_params = _with_drive_params({"q": q, "fields": "files(id,name)"})
    found = service.files().list(**search_params).execute().get("files", [])
    if found:
        return found[0]["id"]

    body = {"name": name, "mimeType": "application/vnd.google-apps.folder"}
    if effective_parent:
        body["parents"] = [effective_parent]

    create_params = {"body": body, "fields": "id"}
    if _shared_drive_id():
        create_params["supportsAllDrives"] = True

    return service.files().create(**create_params).execute()["id"]

def upload_file(local_path: str, filename: str, parent_id: Optional[str],
                mime_type: str = "application/octet-stream") -> Dict:
    """
    Sube un archivo a la carpeta indicada.
    Recomendación: siempre pasa un parent_id válido (carpeta en “Mi unidad” o en la unidad compartida).
    """
    service = _svc()
    media = MediaFileUpload(local_path, mimetype=mime_type, resumable=True)
    body = {"name": filename}
    if parent_id:
        body["parents"] = [parent_id]

    params = {"body": body, "media_body": media, "fields": "id,name,mimeType,webViewLink,webContentLink"}
    if _shared_drive_id():
        params["supportsAllDrives"] = True

    return service.files().create(**params).execute()

def download_file(file_id: str) -> bytes:
    service = _svc()
    req = service.files().get_media(fileId=file_id, supportsAllDrives=bool(_shared_drive_id()))
    buf = io.BytesIO()
    downloader = MediaIoBaseDownload(buf, req)
    done = False
    while not done:
        _, done = downloader.next_chunk()
    buf.seek(0)
    return buf.read()

def list_files(parent_id: str, page_size: int = 100) -> List[Dict]:
    """Lista archivos dentro de una carpeta."""
    service = _svc()
    params = {
        "q": f"'{parent_id}' in parents and trashed=false",
        "fields": "files(id,name,mimeType,modifiedTime,size,webViewLink)",
        "pageSize": page_size,
    }
    params = _with_drive_params(params)
    return service.files().list(**params).execute().get("files", [])
