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
from google.oauth2 import service_account

SCOPES = ["https://www.googleapis.com/auth/drive"]  # usa "drive.file" si quieres restringir

# ---------------------------
# Helpers de ubicación / claves
# ---------------------------

def _keys_dir() -> Path:
    try:
        return Path(settings.BASE_DIR) / "keys"
    except Exception:
        return Path.cwd() / "keys"

def _is_shared_drive_enabled() -> bool:
    """
    Controla si debemos tratar GOOGLE_SHARED_DRIVE_ID como una UNIDAD COMPARTIDA.
    Por defecto False, así una carpeta normal funciona sin parámetros de shared drive.
    """
    v = os.getenv("GOOGLE_IS_SHARED_DRIVE", "").strip().lower()
    return v in ("1", "true", "yes")

def _shared_drive_id() -> str:
    return (
        getattr(settings, "GOOGLE_SHARED_DRIVE_ID", "")
        or os.getenv("GOOGLE_SHARED_DRIVE_ID", "")
        or ""
    ).strip()

def _sa_file_path() -> Optional[str]:
    """
    Devuelve la ruta al service_account.json resolviendo en orden:
    1) GOOGLE_APPLICATION_CREDENTIALS (ya resuelto por settings.py)
    2) keys/service_account.json
    3) GOOGLE_SERVICE_ACCOUNT_FILE explícito
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
    )
    f = f.strip()
    if f and Path(f).exists():
        return f

    return None

# ---------------------------
# Credenciales (Service Account)
# ---------------------------

def _build_creds():
    """
    Prioriza Service Account (producción).
    - JSON inline: GOOGLE_SERVICE_ACCOUNT_JSON
    - Archivo: keys/service_account.json o GOOGLE_APPLICATION_CREDENTIALS/GOOGLE_SERVICE_ACCOUNT_FILE
    Soporta impersonación con DRIVE_IMPERSONATE_EMAIL.
    """
    sa_json = os.getenv("GOOGLE_SERVICE_ACCOUNT_JSON", "").strip()
    imp = os.getenv("DRIVE_IMPERSONATE_EMAIL", "").strip()

    if sa_json:
        info = json.loads(sa_json)
        creds = service_account.Credentials.from_service_account_info(info, scopes=SCOPES)
        return creds.with_subject(imp) if imp else creds

    sa_file = _sa_file_path()
    if sa_file:
        creds = service_account.Credentials.from_service_account_file(sa_file, scopes=SCOPES)
        return creds.with_subject(imp) if imp else creds

    raise RuntimeError(
        "No hay credenciales de Google Drive (Service Account). "
        "Define GOOGLE_SERVICE_ACCOUNT_JSON o sube keys/service_account.json."
    )

def _svc():
    # cache_discovery=False reduce IO en Azure
    return build("drive", "v3", credentials=_build_creds(), cache_discovery=False)

def _with_drive_params(params: Dict) -> Dict:
    """
    Añade parámetros de Shared Drive solo si GOOGLE_IS_SHARED_DRIVE=true.
    Si usas una carpeta normal (Mi unidad), no agrega nada.
    """
    if _is_shared_drive_enabled() and _shared_drive_id():
        params.update({
            "corpora": "drive",
            "driveId": _shared_drive_id(),
            "includeItemsFromAllDrives": True,
            "supportsAllDrives": True,
        })
    return params

# ---------------------------
# Operaciones de alto nivel
# ---------------------------

def list_root(max_items: int = 10) -> List[Dict]:
    service = _svc()
    params = dict(
        pageSize=max_items,
        fields="files(id,name,mimeType,parents,modifiedTime,webViewLink)"
    )
    params = _with_drive_params(params)
    return service.files().list(**params).execute().get("files", [])

def ensure_folder(name: str, parent_id: Optional[str] = None) -> str:
    """
    Crea (o devuelve) una carpeta con nombre `name`.
    - Si hay Shared Drive y no pasas parent_id, usa la raíz de la unidad compartida.
    """
    service = _svc()
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
    if _is_shared_drive_enabled() and _shared_drive_id():
        create_params["supportsAllDrives"] = True

    return service.files().create(**create_params).execute()["id"]

def upload_file(local_path: str, filename: str, parent_id: Optional[str], mime_type: str = "application/octet-stream") -> Dict:
    service = _svc()
    media = MediaFileUpload(local_path, mimetype=mime_type, resumable=True)
    body = {"name": filename, "parents": [parent_id] if parent_id else []}
    params = {"body": body, "media_body": media, "fields": "id,name,mimeType,webViewLink,webContentLink"}
    if _is_shared_drive_enabled() and _shared_drive_id():
        params["supportsAllDrives"] = True
    return service.files().create(**params).execute()

def download_file(file_id: str) -> bytes:
    service = _svc()
    req = service.files().get_media(
        fileId=file_id,
        supportsAllDrives=bool(_is_shared_drive_enabled() and _shared_drive_id())
    )
    buf = io.BytesIO()
    downloader = MediaIoBaseDownload(buf, req)
    done = False
    while not done:
        _, done = downloader.next_chunk()
    buf.seek(0)
    return buf.read()

def list_files(parent_id: str, page_size: int = 100) -> List[Dict]:
    """
    Lista archivos no borrados dentro de una carpeta.
    Soporta Shared Drive si GOOGLE_SHARED_DRIVE_ID está definido y habilitado.
    """
    service = _svc()
    params = {
        "q": f"'{parent_id}' in parents and trashed=false",
        "fields": "files(id,name,mimeType,modifiedTime,size,webViewLink)",
        "pageSize": page_size,
    }
    params = _with_drive_params(params)
    return service.files().list(**params).execute().get("files", [])

