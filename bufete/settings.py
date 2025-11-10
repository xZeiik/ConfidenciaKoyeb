import os
import json
import tempfile
from pathlib import Path
import dj_database_url

BASE_DIR = Path(__file__).resolve().parent.parent

# ===== Entorno / seguridad =====
SECRET_KEY = os.getenv("SECRET_KEY", "change-me")
DEBUG = os.getenv("DEBUG", "false").lower() == "true"

# Permite OAuth sobre HTTP sólo en DEV
if DEBUG:
    os.environ["OAUTHLIB_INSECURE_TRANSPORT"] = "1"

APP_BASE_URL = os.getenv("APP_BASE_URL", "http://127.0.0.1:8000").rstrip("/")

# ALLOWED_HOSTS desde env o default para Azure
ALLOWED_HOSTS = os.getenv(
    "ALLOWED_HOSTS",
    ".azurewebsites.net,localhost,127.0.0.1"
).split(",")

# CSRF: orígenes confiables (usar URLs con esquema)
CSRF_TRUSTED_ORIGINS = list({
    APP_BASE_URL if APP_BASE_URL.startswith("http") else f"https://{APP_BASE_URL}",
    "https://*.azurewebsites.net",
})

SECURE_PROXY_SSL_HEADER = ("HTTP_X_FORWARDED_PROTO", "https")
SESSION_COOKIE_SECURE = not DEBUG
CSRF_COOKIE_SECURE = not DEBUG
SESSION_COOKIE_SAMESITE = "Lax"
USE_X_FORWARDED_HOST = True

# Endurece seguridad en producción
if not DEBUG:
    SECURE_SSL_REDIRECT = True
    SECURE_HSTS_SECONDS = int(os.getenv("SECURE_HSTS_SECONDS", "31536000"))  # 1 año
    SECURE_HSTS_INCLUDE_SUBDOMAINS = True
    SECURE_HSTS_PRELOAD = True
    SECURE_CONTENT_TYPE_NOSNIFF = True
    SECURE_BROWSER_XSS_FILTER = True
    X_FRAME_OPTIONS = "DENY"
    REFERRER_POLICY = "strict-origin-when-cross-origin"

# ===== Apps =====
INSTALLED_APPS = [
    "django.contrib.admin", "django.contrib.auth", "django.contrib.contenttypes",
    "django.contrib.sessions", "django.contrib.messages", "django.contrib.staticfiles",
    "rest_framework", "django_filters", "widget_tweaks",
    "core", "accounts", "clients", "cases", "documents", "audit",
]

# ===== Middleware =====
MIDDLEWARE = [
    "django.middleware.security.SecurityMiddleware",
    # WhiteNoise inmediatamente después de SecurityMiddleware
    "whitenoise.middleware.WhiteNoiseMiddleware",
    "django.contrib.sessions.middleware.SessionMiddleware",
    "django.middleware.common.CommonMiddleware",
    "django.middleware.csrf.CsrfViewMiddleware",
    "django.contrib.auth.middleware.AuthenticationMiddleware",
    "django.contrib.messages.middleware.MessageMiddleware",
    "django.middleware.clickjacking.XFrameOptionsMiddleware",
]

ROOT_URLCONF = "bufete.urls"
WSGI_APPLICATION = "bufete.wsgi.application"

TEMPLATES = [{
    "BACKEND": "django.template.backends.django.DjangoTemplates",
    "DIRS": [BASE_DIR / "templates"],
    "APP_DIRS": True,
    "OPTIONS": {"context_processors": [
        "django.template.context_processors.debug",
        "django.template.context_processors.request",
        "django.contrib.auth.context_processors.auth",
        "django.contrib.messages.context_processors.messages",
    ]},
}]

# ===== Base de datos (Azure PostgreSQL Flexible Server) =====
# Prioriza DATABASE_URL con sslmode=require
if os.getenv("DATABASE_URL"):
    DATABASES = {
        "default": dj_database_url.parse(
            os.environ["DATABASE_URL"], conn_max_age=600, ssl_require=True
        )
    }
else:
    DATABASES = {
        "default": {
            "ENGINE": "django.db.backends.postgresql",
            "NAME": os.getenv("DB_NAME", "bufete_dev"),
            "USER": os.getenv("DB_USER", "bufete_user"),
            "PASSWORD": os.getenv("DB_PASS", "bufete_pass"),
            "HOST": os.getenv("DB_HOST", "127.0.0.1"),
            "PORT": os.getenv("DB_PORT", "5432"),
            "OPTIONS": {"sslmode": "require"},
        }
    }

# ===== Idioma / TZ =====
LANGUAGE_CODE = "es-cl"
TIME_ZONE = "America/Santiago"
USE_I18N = False
USE_TZ = True

# ===== Estáticos =====
STATIC_URL = "/static/"
STATIC_ROOT = BASE_DIR / "staticfiles"
if (BASE_DIR / "static").exists():
    STATICFILES_DIRS = [BASE_DIR / "static"]

if not DEBUG:
    STATICFILES_STORAGE = "whitenoise.storage.CompressedManifestStaticFilesStorage"

# ===== Auth =====
DEFAULT_AUTO_FIELD = "django.db.models.BigAutoField"
AUTH_USER_MODEL = "accounts.Usuario"
LOGIN_URL = "accounts:login"
LOGIN_REDIRECT_URL = "core:home"

# ===== Logging (útil en Azure Streaming Logs) =====
LOGGING = {
    "version": 1,
    "disable_existing_loggers": False,
    "handlers": {"console": {"class": "logging.StreamHandler"}},
    "root": {"handlers": ["console"], "level": os.getenv("LOG_LEVEL", "INFO")},
}

# ===== Google Calendar (OAuth por usuario) =====
GOOGLE_REDIRECT_URI = os.getenv(
    "GOOGLE_REDIRECT_URI",
    APP_BASE_URL + "/accounts/google/callback/"
)

GOOGLE_CALENDAR_SCOPES = (
    ["https://www.googleapis.com/auth/calendar.events"]
    if os.getenv("GOOGLE_CAL_RW", "0") == "1"
    else ["https://www.googleapis.com/auth/calendar.readonly"]
)

GOOGLE_OAUTH_CLIENT_ID = os.getenv("GOOGLE_OAUTH_CLIENT_ID", "")
GOOGLE_OAUTH_CLIENT_SECRET = os.getenv("GOOGLE_OAUTH_CLIENT_SECRET", "")

# Compat: acepta ambos nombres de variable para el JSON del cliente
_raw_oauth_json = (
    os.getenv("GOOGLE_OAUTH_CLIENT_SECRETS_JSON", "").strip()
    or os.getenv("GOOGLE_OAUTH_CLIENT_JSON", "").strip()
)

# Ruta/archivo que usarán las vistas si requieren un client_secrets.json físico
GOOGLE_OAUTH_SECRETS_RESOLVED = ""
if _raw_oauth_json:
    tmp = Path(tempfile.gettempdir()) / "google_oauth_client_secret.json"
    tmp.write_text(_raw_oauth_json, encoding="utf-8")
    GOOGLE_OAUTH_SECRETS_RESOLVED = str(tmp)

# Para código que espera nombres concretos:
GOOGLE_OAUTH_CLIENT_SECRETS_JSON = _raw_oauth_json  # contenido (si existe)
GOOGLE_OAUTH_CLIENT_SECRETS_FILE = os.getenv("GOOGLE_OAUTH_CLIENT_SECRETS_FILE", "").strip() or GOOGLE_OAUTH_SECRETS_RESOLVED

# ===== Google Drive (Service Account, centralizado) =====
GOOGLE_SHARED_DRIVE_ID = os.getenv("GOOGLE_SHARED_DRIVE_ID", "").strip()

# Acepta JSON inline o ruta a archivo
GOOGLE_SERVICE_ACCOUNT_JSON = os.getenv("GOOGLE_SERVICE_ACCOUNT_JSON", "").strip()
GOOGLE_SERVICE_ACCOUNT_FILE = os.getenv("GOOGLE_SERVICE_ACCOUNT_FILE", "").strip()

if GOOGLE_SERVICE_ACCOUNT_JSON and not GOOGLE_SERVICE_ACCOUNT_FILE:
    sa_path = Path(tempfile.gettempdir()) / "google_sa.json"
    sa_path.write_text(GOOGLE_SERVICE_ACCOUNT_JSON, encoding="utf-8")
    os.environ["GOOGLE_APPLICATION_CREDENTIALS"] = str(sa_path)
elif GOOGLE_SERVICE_ACCOUNT_FILE:
    os.environ["GOOGLE_APPLICATION_CREDENTIALS"] = GOOGLE_SERVICE_ACCOUNT_FILE

