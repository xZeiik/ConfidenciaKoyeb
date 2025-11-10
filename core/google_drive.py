# core/google_drive.py
from __future__ import annotations

import io, os, json
from pathlib import Path
from typing import Dict, List, Optional

from django.conf import settings
from googleapiclient.discovery import build
from googleapiclient.http import MediaFileUpload, MediaIoBaseDownload
from google.oauth2.credentials import Credentials
from google.auth.transport.requests import Request as GoogleRequest

SCOPES = ["https://www.googleapis.com/auth/drive.file"]


# ---------------------------
# Rutas y helpers
# ---------------------------

def _keys_candidates() -> list[Path]:
    """Posibles ubicaciones del directorio keys en local y Azure."""
    cands = []
    try:
        cands.append(Path(settings.BASE_DIR) / "keys")  # paquete desplegado
    except Exception:
        pass
    cands.append(Path("/home/site/wwwroot/keys"))       # Azure wwwroot
    cands.append(Path.cwd() / "keys")                   # fallback
    # por si el usuario define algo explícito
    env_dir = os.getenv("APP_KEYS_DIR", "").strip()
    if env_dir:
        cands.insert(0, Path(env_dir))
    return cands

def _find_first(path_rel: str) -> Optional[Path]:
    """Busca la primera coincidencia existente del path relativo en las carpetas candidates."""
    # prioridad a una ruta absoluta en env
    abs_env = os.getenv(path_rel.upper().replace("/", "_"), "").strip()
    if abs_env and Path(abs_env).exists():
        return Path(abs_env)

    for base in _keys_candidates():
        p = base / path_rel
        if p.exists():
            return p
    return None

def _token_path() -> Optional[Path]:
    # settings override
    p = getattr(settings, "GOOGLE_TOKEN_FILE", "")
    if p and Path(p).exists():
        return Path(p)
    # env override
    p = os.getenv("GOOGLE_TOKEN_FILE", "").strip()
    if p and Path(p).exists():
        return Path(p)
    # buscar en candidates
    return _find_first("token.json")

def _client_secret_path() -> Optional[str]:
    # settings/env explícitos
    for key in ("GOOGLE_OAUTH_CLIENT_SECRETS_FILE", "GOOGLE_OAUTH_CLIENT_FILE"):
        p = getattr(settings, key, "") or os.getenv(key, "")
        p = str(p).strip()
        if p and Path(p).exists():
            return p
    # buscar archivo típico
    p = _find_first("client_secret_web.json")
    return str(p) if p else None

def _sa_file_path() -> Optional[str]:
    p = os.getenv("GOOGLE_APPLICATION_CREDENTIALS", "").strip()
    if p and Path(p).exists():
        return p
    p2 = getattr(settings, "GOOGLE_SERVICE_ACCOUNT_FILE", "") or os.getenv("GOOGLE_SERVICE_ACCOUNT_FILE", "")
    p2 = p2.strip()
    if p2 and Path(p2).exists():
        return p2
    p3 = _find_first("service_account.json")
    return str(p3) if p3 else None

def _shared_drive_id() -> str:
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
    1) Usa token OAuth de usuario (keys/token.json o /home/site/wwwroot/keys/token.json).
       - Refresca y reescribe si expira.
    2) Si NO hay token y DEV_USE_OAUTH=1 → inicia flujo local (solo dev), necesita client_secret_web.json.
    3) Si no, intenta Service Account (útil con Shared Drive o impersonación).
    """
    # 1) OAuth con token.json
    tpath = _token_path()
    if tpath and tpath.exists():
        creds = Credentials.from_authorized_user_file(str(tpath), SCOPES)
        if getattr(creds, "expired", False) and getattr(creds, "refresh_token", None):
            creds.refresh(GoogleRequest())
            tpath.parent.mkdir(parents=True, exist_ok=True)
            tpath.write_text(creds.to_json(), encoding="utf-8")
        return creds

    # 2) Flujo OAuth local (solo si lo pides explícitamente)
    if os.getenv("DEV_USE_OAUTH", "").lower() in ("1", "true", "yes"):
        from google_auth_oauthlib.flow import InstalledAppFlow
        client_path = _client_secret_path()
        if not client_path:
            raise RuntimeError("Falta keys/client_secret_web.json para iniciar OAuth (DEV_USE_OAUTH=1).")
        flow = InstalledAppFlow.from_client_secrets_file(client_path, SCOPES)
        creds = flow.run_local_server(port=0)
        # guarda token para próximos despliegues
        save_to = _token_path() or (_find_first("") or Path("/home/site/wwwroot/keys")) / "token.json"
        save_to.parent.mkdir(parents=True, exist_ok=True)
        save_to.write_text(creds.to_json(), encoding="utf-8")
        return creds

    # 3) Service Account (opcional)
    sa_json = os.getenv("GOOGLE_SERVICE_ACCOUNT_JSON", "").strip()
    imp = os.getenv("DRIVE_IMPERSONATE_EMAIL", "").strip()
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

    raise RuntimeError("No hay credenciales para Google Drive (token.json u objeto Service Account).")


# ---------------------------
# Servicio y utilitarios
# ---------------------------

def _svc():
    return build("drive", "v3", credentials=_build_creds(), cache_discovery=False)

def _with_drive_params(params: Dict) -> Dict:
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
# Operaciones
# ---------------------------

def list_root(max_items=10) -> List[Dict]:
    service = _svc()
    params = dict(pageSize=max_items, fields="files(id,name,mimeType,modifiedTime,webViewLink)")
    params = _with_drive_params(params)
    return service.files().list(**params).execute().get("files", [])

def ensure_folder(name: str, parent_id: Optional[str] = None) -> str:
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
    from googleapiclient.http import MediaIoBaseDownload
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
