# core/google_drive.py
from __future__ import annotations
import io, os, json
from pathlib import Path
from typing import Optional, Dict, List

from django.conf import settings
from googleapiclient.discovery import build
from googleapiclient.http import MediaFileUpload, MediaIoBaseDownload
from google.oauth2.credentials import Credentials
from google.oauth2 import service_account
from google.auth.transport.requests import Request as GoogleRequest

# Permisos mínimos: archivos creados por tu app
SCOPES = ["https://www.googleapis.com/auth/drive.file"]

# ---------- Helpers de rutas/vars ----------
def _base_dir() -> Path:
    try:
        return Path(settings.BASE_DIR)
    except Exception:
        return Path.cwd()

def _keys_dir() -> Path:
    return _base_dir() / "keys"

def _tokens_dir() -> Path:
    # Puedes cambiarlo con GOOGLE_TOKENS_DIR (ya lo tienes en App Settings)
    d = os.getenv("GOOGLE_TOKENS_DIR", str(_keys_dir() / "tokens")).strip()
    p = Path(d)
    p.mkdir(parents=True, exist_ok=True)
    return p

def _token_path() -> Path:
    # Nombre explícito para Drive
    return _tokens_dir() / "token.json"

def _client_secret_file() -> Optional[Path]:
    # 1) Variable con JSON embebido
    js = os.getenv("GOOGLE_OAUTH_CLIENT_SECRETS_JSON", "").strip()
    if js:
        tmp = _tokens_dir() / "client_secret_web.embedded.json"
        tmp.write_text(js, encoding="utf-8")
        return tmp

    # 2) Archivo en /keys (convención local/prod)
    f = _keys_dir() / "client_secret_web.json"
    if f.exists():
        return f

    # 3) Ruta entregada por entorno (opcional)
    env_path = os.getenv("GOOGLE_OAUTH_CLIENT_SECRETS_FILE", "").strip()
    if env_path and Path(env_path).exists():
        return Path(env_path)

    return None

def _configured_root_folder() -> Optional[str]:
    # Para CUENTA GMAIL normal: usa el ID de carpeta (no es shared drive)
    folder_id = os.getenv("GOOGLE_DRIVE_FOLDER_ID", "").strip()
    return folder_id or None

def _is_shared_drive() -> bool:
    # Desactívalo por defecto (tu caso es GMail normal)
    v = os.getenv("GOOGLE_IS_SHARED_DRIVE", "").strip().lower()
    return v in ("1", "true", "yes")

def _with_drive_params(params: Dict) -> Dict:
    # Si algún día usas UNA Unidad Compartida, rellena GOOGLE_SHARED_DRIVE_ID y activa GOOGLE_IS_SHARED_DRIVE
    shared_id = getattr(settings, "GOOGLE_SHARED_DRIVE_ID", "") or os.getenv("GOOGLE_SHARED_DRIVE_ID", "")
    shared_id = shared_id.strip()
    if _is_shared_drive() and shared_id:
        params.update({
            "corpora": "drive",
            "driveId": shared_id,
            "includeItemsFromAllDrives": True,
            "supportsAllDrives": True,
        })
    return params

# ---------- Construcción de credenciales ----------
def _build_creds():
    """
    ORDEN:
    1) Si existe keys/tokens/token.json => usar OAuth del usuario (y refrescar si hace falta).
    2) Si NO existe el token:
       - Si DEV_USE_OAUTH=1 y hay client_secret => PERMITIR flujo local (solo cuando DEBUG/CLI),
         pero en servidor produciremos error claro para que subas el token.
    3) Si nada de lo anterior, caer a Service Account (solo útil con Shared Drives o impersonación).
    """
    # 1) TOKEN PRIMERO (sirve tanto en local como en Azure)
    token_path = _token_path()
    if token_path.exists():
        # token.json en formato de Credentials.to_json()
        try:
            creds = Credentials.from_authorized_user_file(str(token_path), SCOPES)
            if creds and creds.expired and creds.refresh_token:
                creds.refresh(GoogleRequest())
                token_path.write_text(creds.to_json(), encoding="utf-8")
            return creds
        except Exception:
            # Si el token está corrupto, lo ignoramos para reintentar flujo/SA
            pass

    # 2) Flujo OAuth instalado (SOLO para correr en LOCAL y generar token.json)
    if os.getenv("DEV_USE_OAUTH", "").strip().lower() in ("1", "true"):
        client_file = _client_secret_file()
        if not client_file:
            raise RuntimeError("Falta keys/client_secret_web.json o GOOGLE_OAUTH_CLIENT_SECRETS_JSON para iniciar OAuth (DEV_USE_OAUTH=1).")

        # Si estamos en Azure (WEBSITE_SITE_NAME definido), NO intentamos abrir navegador:
        # Debes generar el token en local y subirlo a /home/site/wwwroot/keys/tokens/token.json
        if os.getenv("WEBSITE_SITE_NAME"):
            raise RuntimeError(
                "OAuth interactivo no se ejecuta en Azure. "
                "Genera token.json en tu equipo (python manage.py <comando_oauth_local>) "
                "y súbelo a /home/site/wwwroot/keys/tokens/token.json."
            )

        # Local: ejecuta el flujo e instala token.json
        from google_auth_oauthlib.flow import InstalledAppFlow
        flow = InstalledAppFlow.from_client_secrets_file(str(client_file), SCOPES)
        creds = flow.run_local_server(port=0)
        token_path.parent.mkdir(parents=True, exist_ok=True)
        token_path.write_text(creds.to_json(), encoding="utf-8")
        return creds

    # 3) Service Account (fallback)
    sa_json = os.getenv("GOOGLE_SERVICE_ACCOUNT_JSON", "").strip()
    if sa_json:
        info = json.loads(sa_json)
        return service_account.Credentials.from_service_account_info(info, scopes=SCOPES)

    sa_file = os.getenv("GOOGLE_SERVICE_ACCOUNT_FILE", "").strip()
    if sa_file and Path(sa_file).exists():
        return service_account.Credentials.from_service_account_file(sa_file, scopes=SCOPES)

    raise RuntimeError(
        "No hay credenciales de Drive: sube keys/tokens/token.json (OAuth) "
        "o configura GOOGLE_SERVICE_ACCOUNT_JSON/FILE."
    )

def _svc():
    # cache_discovery=False reduce I/O
    return build("drive", "v3", credentials=_build_creds(), cache_discovery=False)

# ---------- Operaciones ----------
def list_root(max_items: int = 10) -> List[Dict]:
    service = _svc()
    folder = _configured_root_folder()

    if folder and not _is_shared_drive():
        q = f"trashed=false and '{folder}' in parents"
        params = {"q": q, "pageSize": max_items, "fields": "files(id,name,mimeType,parents,modifiedTime,webViewLink)"}
        return service.files().list(**params).execute().get("files", [])

    params = dict(pageSize=max_items, fields="files(id,name,mimeType,parents,modifiedTime,webViewLink)")
    params = _with_drive_params(params)
    return service.files().list(**params).execute().get("files", [])

def ensure_folder(name: str, parent_id: Optional[str] = None) -> str:
    service = _svc()
    effective_parent = parent_id or _configured_root_folder()

    q = f"mimeType='application/vnd.google-apps.folder' and trashed=false and name='{name}'"
    if effective_parent:
        q += f" and '{effective_parent}' in parents"

    params = _with_drive_params({"q": q, "fields": "files(id,name)"})
    found = service.files().list(**params).execute().get("files", [])
    if found:
        return found[0]["id"]

    body = {"name": name, "mimeType": "application/vnd.google-apps.folder"}
    if effective_parent:
        body["parents"] = [effective_parent]

    create_params = {"body": body, "fields": "id"}
    if _is_shared_drive():
        create_params["supportsAllDrives"] = True

    return service.files().create(**create_params).execute()["id"]

def upload_file(local_path: str, filename: str, parent_id: Optional[str], mime_type="application/octet-stream") -> Dict:
    service = _svc()
    effective_parent = parent_id or _configured_root_folder()
    if not effective_parent:
        raise RuntimeError("Debes configurar GOOGLE_DRIVE_FOLDER_ID o pasar parent_id para evitar subir al root.")

    media = MediaFileUpload(local_path, mimetype=mime_type, resumable=True)
    body = {"name": filename, "parents": [effective_parent]}
    params = {"body": body, "media_body": media, "fields": "id,name,mimeType,webViewLink,webContentLink"}
    if _is_shared_drive():
        params["supportsAllDrives"] = True

    return service.files().create(**params).execute()

def download_file(file_id: str) -> bytes:
    service = _svc()
    req = service.files().get_media(fileId=file_id, supportsAllDrives=_is_shared_drive())
    buf = io.BytesIO()
    downloader = MediaIoBaseDownload(buf, req)
    done = False
    while not done:
        _, done = downloader.next_chunk()
    buf.seek(0)
    return buf.read()

def list_files(parent_id: str, page_size: int = 100) -> List[Dict]:
    service = _svc()
    params = {
        "q": f"'{parent_id}' in parents and trashed=false",
        "fields": "files(id,name,mimeType,modifiedTime,size,webViewLink)",
        "pageSize": page_size,
    }
    params = _with_drive_params(params)
    return service.files().list(**params).execute().get("files", [])

