# core/google_drive.py
import io, os, json, pathlib
from typing import Optional, Dict, List
from django.conf import settings
from googleapiclient.discovery import build
from googleapiclient.http import MediaFileUpload, MediaIoBaseDownload

SCOPES = ["https://www.googleapis.com/auth/drive"]  # o "drive.file" si quieres restringir

def _shared_drive_id() -> str:
    return getattr(settings, "GOOGLE_SHARED_DRIVE_ID", "") or os.getenv("GOOGLE_SHARED_DRIVE_ID", "") or ""

def _project_root() -> pathlib.Path:
    # BASE_DIR (manage.py dir) si existe, o cwd
    try:
        from django.conf import settings as dj_settings
        return pathlib.Path(dj_settings.BASE_DIR)
    except Exception:
        return pathlib.Path.cwd()

def _build_creds():
    # 1) Si estamos en DEV y queremos OAuth “installed app”
    if os.getenv("DEV_USE_OAUTH", "") in ("1", "true", "True"):
        from google.oauth2.credentials import Credentials as UserCreds
        from google_auth_oauthlib.flow import InstalledAppFlow
        token_path = _project_root() / "token.json"
        creds = None
        if token_path.exists():
            creds = UserCreds.from_authorized_user_file(str(token_path), SCOPES)
        if not creds or not creds.valid:
            if creds and creds.expired and creds.refresh_token:
                from google.auth.transport.requests import Request
                creds.refresh(Request())
            else:
                client_file = os.getenv("GOOGLE_OAUTH_CLIENT_FILE") or getattr(settings, "GOOGLE_OAUTH_CLIENT_FILE", "")
                if not client_file:
                    raise RuntimeError("Falta GOOGLE_OAUTH_CLIENT_FILE para OAuth dev.")
                flow = InstalledAppFlow.from_client_secrets_file(client_file, SCOPES)
                creds = flow.run_local_server(port=0)
            # guarda token para reutilizar
            with open(token_path, "w", encoding="utf-8") as f:
                f.write(creds.to_json())
        return creds

    # 2) Intentar ADC (prod en GCP con SA adjunta)
    try:
        import google.auth
        creds, _ = google.auth.default(scopes=SCOPES)
        if creds:
            return creds
    except Exception:
        pass

    # 3) Service Account por JSON en ENV
    sa_json = os.getenv("GOOGLE_SERVICE_ACCOUNT_JSON")
    if sa_json:
        from google.oauth2 import service_account
        info = json.loads(sa_json)
        return service_account.Credentials.from_service_account_info(info, scopes=SCOPES)

    # 4) Service Account por archivo
    sa_file = getattr(settings, "GOOGLE_SERVICE_ACCOUNT_FILE", "") or os.getenv("GOOGLE_SERVICE_ACCOUNT_FILE", "")
    if sa_file:
        from google.oauth2 import service_account
        return service_account.Credentials.from_service_account_file(sa_file, scopes=SCOPES)

    raise RuntimeError("No hay credenciales configuradas (OAuth dev / ADC / SA JSON / SA FILE).")

def _svc():
    return build("drive", "v3", credentials=_build_creds())

def _with_drive_params(params: Dict) -> Dict:
    """Añade parámetros de Shared Drive solo si hay GOOGLE_SHARED_DRIVE_ID."""
    if _shared_drive_id():
        params.update({
            "corpora": "drive",
            "driveId": _shared_drive_id(),
            "includeItemsFromAllDrives": True,
            "supportsAllDrives": True,
        })
    return params

def list_root(max_items=10) -> List[Dict]:
    service = _svc()
    params = dict(pageSize=max_items, fields="files(id,name,mimeType,parents,modifiedTime,webViewLink)")
    params = _with_drive_params(params)
    return service.files().list(**params).execute().get("files", [])

def ensure_folder(name: str, parent_id: Optional[str] = None) -> str:
    service = _svc()
    # Si hay Shared Drive y no hay parent, usa la raíz de la unidad
    effective_parent = parent_id or (_shared_drive_id() or None)

    q = "mimeType='application/vnd.google-apps.folder' and trashed=false and name='%s'" % name
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

def upload_file(local_path: str, filename: str, parent_id: str, mime_type="application/octet-stream") -> Dict:
    service = _svc()
    media = MediaFileUpload(local_path, mimetype=mime_type, resumable=True)
    body = {"name": filename, "parents": [parent_id] if parent_id else []}
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


# core/google_drive.py (agregar)
from typing import Dict, List

def list_files(parent_id: str, page_size: int = 100) -> List[Dict]:
    """
    Lista archivos visibles (no borrados) dentro de una carpeta de Drive.
    Soporta Shared Drives si GOOGLE_SHARED_DRIVE_ID está definido en settings/.env.
    """
    service = _svc()
    params = {
        "q": f"'{parent_id}' in parents and trashed=false",
        "fields": "files(id,name,mimeType,modifiedTime,size,webViewLink)",
        "pageSize": page_size,
    }
    # Shared Drive (Unidad compartida) si aplica
    shared_id = getattr(settings, "GOOGLE_SHARED_DRIVE_ID", "") or ""
    if shared_id:
        params.update({
            "corpora": "drive",
            "driveId": shared_id,
            "includeItemsFromAllDrives": True,
            "supportsAllDrives": True,
        })
    return service.files().list(**params).execute().get("files", [])
