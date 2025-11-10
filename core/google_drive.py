# core/google_drive.py
import io, os, json, pathlib
from typing import Optional, Dict, List
from django.conf import settings
from googleapiclient.discovery import build
from googleapiclient.http import MediaFileUpload, MediaIoBaseDownload

# Permisos solo sobre los archivos creados por tu app
SCOPES = ["https://www.googleapis.com/auth/drive.file"]

# ---------------------------
# Helpers básicos
# ---------------------------

def _shared_drive_id() -> str:
    """Usa si tienes una unidad compartida; vacío para cuentas Gmail normales."""
    return getattr(settings, "GOOGLE_SHARED_DRIVE_ID", "") or os.getenv("GOOGLE_SHARED_DRIVE_ID", "") or ""

def _project_root() -> pathlib.Path:
    """Ruta base del proyecto (BASE_DIR)"""
    try:
        from django.conf import settings as dj_settings
        return pathlib.Path(dj_settings.BASE_DIR)
    except Exception:
        return pathlib.Path.cwd()

# ---------------------------
# Credenciales
# ---------------------------

def _build_creds():
    """
    1) Si DEV_USE_OAUTH=1 → usa flujo OAuth (token.json + client_secret_web.json)
       → Ideal para cuentas Gmail personales (usa la cuota del usuario).
    2) Si no, intenta usar Service Account (solo válido si usas Shared Drive o impersonación).
    """
    if os.getenv("DEV_USE_OAUTH", "").lower() in ("1", "true"):
        from google.oauth2.credentials import Credentials as UserCreds
        from google_auth_oauthlib.flow import InstalledAppFlow
        from google.auth.transport.requests import Request

        token_path = _project_root() / "keys" / "token.json"
        client_path = _project_root() / "keys" / "client_secret_web.json"
        creds = None

        if token_path.exists():
            creds = UserCreds.from_authorized_user_file(str(token_path), SCOPES)

        # Si no hay token o expiró
        if not creds or not creds.valid:
            if creds and creds.expired and creds.refresh_token:
                creds.refresh(Request())
            else:
                if not client_path.exists():
                    raise RuntimeError("Falta keys/client_secret_web.json para OAuth.")
                flow = InstalledAppFlow.from_client_secrets_file(str(client_path), SCOPES)
                creds = flow.run_local_server(port=0)

            # Guarda el token actualizado
            token_path.parent.mkdir(exist_ok=True)
            with open(token_path, "w", encoding="utf-8") as f:
                f.write(creds.to_json())

        return creds

    # === Service Account (fallback, solo si se configuró explícitamente) ===
    sa_json = os.getenv("GOOGLE_SERVICE_ACCOUNT_JSON", "").strip()
    if sa_json:
        from google.oauth2 import service_account
        info = json.loads(sa_json)
        return service_account.Credentials.from_service_account_info(info, scopes=SCOPES)

    sa_file = getattr(settings, "GOOGLE_SERVICE_ACCOUNT_FILE", "") or os.getenv("GOOGLE_SERVICE_ACCOUNT_FILE", "")
    if sa_file and os.path.exists(sa_file):
        from google.oauth2 import service_account
        return service_account.Credentials.from_service_account_file(sa_file, scopes=SCOPES)

    raise RuntimeError(
        "No hay credenciales configuradas.\n"
        "Activa DEV_USE_OAUTH=1 y asegúrate de tener keys/client_secret_web.json y keys/token.json."
    )

# ---------------------------
# Servicio base
# ---------------------------

def _svc():
    return build("drive", "v3", credentials=_build_creds(), cache_discovery=False)

def _with_drive_params(params: Dict) -> Dict:
    """Añade soporte de Shared Drives solo si aplica."""
    shared_id = _shared_drive_id()
    if shared_id:
        params.update({
            "corpora": "drive",
            "driveId": shared_id,
            "includeItemsFromAllDrives": True,
            "supportsAllDrives": True,
        })
    return params

# ---------------------------
# Operaciones principales
# ---------------------------

def list_root(max_items=10) -> List[Dict]:
    """Lista los archivos en la raíz (Mi unidad o Shared Drive si aplica)."""
    service = _svc()
    params = dict(pageSize=max_items, fields="files(id,name,mimeType,modifiedTime,webViewLink)")
    params = _with_drive_params(params)
    return service.files().list(**params).execute().get("files", [])

def ensure_folder(name: str, parent_id: Optional[str] = None) -> str:
    """Crea (o retorna) una carpeta con nombre `name`."""
    service = _svc()
    effective_parent = parent_id or (_shared_drive_id() or None)

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
    if _shared_drive_id():
        create_params["supportsAllDrives"] = True

    return service.files().create(**create_params).execute()["id"]

def upload_file(local_path: str, filename: str, parent_id: Optional[str], mime_type="application/octet-stream") -> Dict:
    """Sube un archivo a la carpeta indicada."""
    service = _svc()
    media = MediaFileUpload(local_path, mimetype=mime_type, resumable=True)
    body = {"name": filename, "parents": [parent_id] if parent_id else []}
    params = {"body": body, "media_body": media, "fields": "id,name,mimeType,webViewLink,webContentLink"}
    if _shared_drive_id():
        params["supportsAllDrives"] = True
    return service.files().create(**params).execute()

def download_file(file_id: str) -> bytes:
    """Descarga un archivo por ID."""
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

    return service.files().list(**params).execute().get("files", [])

