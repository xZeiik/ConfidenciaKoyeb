# core/google_drive.py
from __future__ import annotations

import io
import os
import json
import pickle
from pathlib import Path
from typing import Dict, List, Optional

from django.conf import settings
from googleapiclient.discovery import build
from googleapiclient.http import MediaFileUpload, MediaIoBaseDownload
from google.oauth2 import service_account
from google.oauth2.credentials import Credentials
from google.auth.transport.requests import Request as GoogleRequest

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

def _root_container_id() -> str:
    """
    Contenedor raíz donde operar:
      - FolderId de Mi unidad (carpeta normal)
      - DriveId si usas unidad compartida (activar GOOGLE_IS_SHARED_DRIVE=true)
    """
    return (
        getattr(settings, "GOOGLE_SHARED_DRIVE_ID", "")
        or os.getenv("GOOGLE_SHARED_DRIVE_ID", "")
        or ""
    ).strip()

def _sa_file_path() -> Optional[str]:
    """
    Devuelve la ruta al service_account.json resolviendo en orden:
    1) GOOGLE_APPLICATION_CREDENTIALS
    2) keys/service_account.json
    3) GOOGLE_SERVICE_ACCOUNT_FILE
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
# Credenciales (OAuth primero; SA fallback)
# ---------------------------

def _oauth_token_path() -> Path:
    # settings.GOOGLE_TOKEN_FILE (p.ej. BASE_DIR/keys/token.json)
    token_file = getattr(settings, "GOOGLE_TOKEN_FILE", "")
    return Path(token_file) if token_file else (_keys_dir() / "token.json")

def _build_creds():
    """
    Prioriza OAuth de usuario (token.json). Si no existe, usa Service Account.
    - OAuth: sube con la cuota del usuario → evita 403 "Service Accounts do not have storage quota".
    - SA: para automatizaciones o si configuraste impersonación en Workspace.
    """
    # 1) OAuth
    token_path = _oauth_token_path()
    if token_path.exists():
        with open(token_path, "rb") as f:
            creds: Credentials = pickle.load(f)
        # Refresca si es necesario (si hay refresh_token)
        if getattr(creds, "expired", False) and getattr(creds, "refresh_token", None):
            creds.refresh(GoogleRequest())
            with open(token_path, "wb") as f:
                pickle.dump(creds, f)
        return creds

    # 2) Service Account (fallback)
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
        "No hay credenciales para Google Drive: falta keys/token.json (OAuth) "
        "y no se encontró Service Account. Autoriza en /cuentas/google/drive/connect/ "
        "o configura la SA."
    )

def _svc():
    # cache_discovery=False reduce IO en Azure
    return build("drive", "v3", credentials=_build_creds(), cache_discovery=False)

def _with_drive_params(params: Dict) -> Dict:
    """
    Añade parámetros de Shared Drive solo si GOOGLE_IS_SHARED_DRIVE=true.
    Si usas una carpeta normal (Mi unidad), no agrega nada.
    """
    root_id = _root_container_id()
    if _is_shared_drive_enabled() and root_id:
        params.update({
            "corpora": "drive",
            "driveId": root_id,
            "includeItemsFromAllDrives": True,
            "supportsAllDrives": True,
        })
    return params

# ---------------------------
# Operaciones de alto nivel
# ---------------------------

def list_root(max_items: int = 10) -> List[Dict]:
    """
    Lista elementos de la raíz lógica:
      - Shared drive: raíz de la unidad
      - Carpeta normal: hijos de esa carpeta
      - Sin contenedor: lista raíz del identity actual (no recomendado)
    """
    service = _svc()

    # Si NO es shared drive y hay carpeta raíz, filtra por padre
    root_id = _root_container_id()
    if not _is_shared_drive_enabled() and root_id:
        q = f"trashed=false and '{root_id}' in parents"
        params = {"q": q, "pageSize": max_items,
                  "fields": "files(id,name,mimeType,parents,modifiedTime,webViewLink)"}
        return service.files().list(**params).execute().get("files", [])

    # Shared drive o sin root_id → deja que Drive liste según contexto
    params = dict(
        pageSize=max_items,
        fields="files(id,name,mimeType,parents,modifiedTime,webViewLink)"
    )
    params = _with_drive_params(params)
    return service.files().list(**params).execute().get("files", [])

def ensure_folder(name: str, parent_id: Optional[str] = None) -> str:
    """
    Crea (o devuelve) una carpeta con nombre `name`.
    - Si no pasas parent_id:
        * Shared drive: usa raíz del drive (GOOGLE_SHARED_DRIVE_ID como driveId)
        * Carpeta normal: usa el folderId configurado en GOOGLE_SHARED_DRIVE_ID
    """
    service = _svc()
    effective_parent = parent_id or (_root_container_id() or None)

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
    if _is_shared_drive_enabled() and _root_container_id():
        create_params["supportsAllDrives"] = True

    return service.files().create(**create_params).execute()["id"]

def upload_file(local_path: str, filename: str, parent_id: Optional[str],
                mime_type: str = "application/octet-stream") -> Dict:
    """
    Sube un archivo. Si parent_id viene vacío, usa como fallback el contenedor configurado.
    Si tampoco hay contenedor, lanza error para evitar subir al root de la SA (sin cuota).
    Con OAuth NO hay problema de cuota; con SA sin impersonación, sí lo habría.
    """
    service = _svc()
    effective_parent = parent_id or (_root_container_id() or None)
    if not effective_parent:
        raise RuntimeError(
            "No se especificó parent_id y no hay carpeta/drive root (GOOGLE_SHARED_DRIVE_ID). "
            "Se evita subir al root por seguridad y para no topar la cuota de SA."
        )

    media = MediaFileUpload(local_path, mimetype=mime_type, resumable=True)
    body = {"name": filename, "parents": [effective_parent]}

    params = {
        "body": body,
        "media_body": media,
        "fields": "id,name,mimeType,webViewLink,webContentLink"
    }
    if _is_shared_drive_enabled() and _root_container_id():
        params["supportsAllDrives"] = True

    return service.files().create(**params).execute()

def download_file(file_id: str) -> bytes:
    service = _svc()
    req = service.files().get_media(
        fileId=file_id,
        supportsAllDrives=bool(_is_shared_drive_enabled() and _root_container_id())
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
    Funciona igual para carpeta en Mi unidad y para carpetas dentro de una unidad compartida.
    """
    service = _svc()
    params = {
        "q": f"'{parent_id}' in parents and trashed=false",
        "fields": "files(id,name,mimeType,modifiedTime,size,webViewLink)",
        "pageSize": page_size,
    }
    params = _with_drive_params(params)
    return service.files().list(**params).execute().get("files", [])

