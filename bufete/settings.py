import os, json, tempfile
from pathlib import Path
import dj_database_url

BASE_DIR = Path(__file__).resolve().parent.parent

# ===== Entorno / seguridad =====
SECRET_KEY = os.getenv("SECRET_KEY", "change-me")
DEBUG = os.getenv("DEBUG", "false").lower() == "true"
if DEBUG:
    os.environ["OAUTHLIB_INSECURE_TRANSPORT"] = "1"

APP_BASE_URL = os.getenv("APP_BASE_URL", "http://127.0.0.1:8000").rstrip("/")

ALLOWED_HOSTS = os.getenv(
    "ALLOWED_HOSTS",
    ".azurewebsites.net,localhost,127.0.0.1"
).split(",")

CSRF_TRUSTED_ORIGINS = list({
    os.getenv("CSRF_ORIGIN", APP_BASE_URL),
    "https://*.azurewebsites.net",
})

SECURE_PROXY_SSL_HEADER = ("HTTP_X_FORWARDED_PROTO", "https")
SESSION_COOKIE_SECURE = not DEBUG
CSRF_COOKIE_SECURE = not DEBUG
SESSION_COOKIE_SAMESITE = "Lax"

# ===== Apps =====
INSTALLED_APPS = [
    "django.contrib.admin","django.contrib.auth","django.contrib.contenttypes",
    "django.contrib.sessions","django.contrib.messages","django.contrib.staticfiles",
    "rest_framework","django_filters","widget_tweaks",
    "core","accounts","clients","cases","documents","audit",
]

# ===== Middleware =====
MIDDLEWARE = [
    "django.middleware.security.SecurityMiddleware",
    *([] if DEBUG else ["whitenoise.middleware.WhiteNoiseMiddleware"]),
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

# ===== Google Calendar / OAuth =====
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

# Permite pegar el JSON completo del cliente en una sola env (opcional)
GOOGLE_OAUTH_CLIENT_JSON = os.getenv("GOOGLE_OAUTH_CLIENT_JSON", "").strip()
GOOGLE_OAUTH_SECRETS_RESOLVED = ""
if GOOGLE_OAUTH_CLIENT_JSON:
    tmp = Path(tempfile.gettempdir()) / "google_oauth_client_secret.json"
    tmp.write_text(GOOGLE_OAUTH_CLIENT_JSON, encoding="utf-8")
    GOOGLE_OAUTH_SECRETS_RESOLVED = str(tmp)
else:
    GOOGLE_OAUTH_SECRETS_RESOLVED = os.getenv("GOOGLE_OAUTH_CLIENT_SECRETS_FILE", "").strip()

# ===== Google Drive / Service Account (opcional) =====
GOOGLE_SHARED_DRIVE_ID = os.getenv("GOOGLE_SHARED_DRIVE_ID", "")
GOOGLE_SERVICE_ACCOUNT_JSON = os.getenv("GOOGLE_SERVICE_ACCOUNT_JSON", "").strip()
GOOGLE_SERVICE_ACCOUNT_FILE = os.getenv("GOOGLE_SERVICE_ACCOUNT_FILE", "").strip()

if GOOGLE_SERVICE_ACCOUNT_JSON and not GOOGLE_SERVICE_ACCOUNT_FILE:
    sa_path = Path(tempfile.gettempdir()) / "google_sa.json"
    sa_path.write_text(GOOGLE_SERVICE_ACCOUNT_JSON, encoding="utf-8")
    os.environ["GOOGLE_APPLICATION_CREDENTIALS"] = str(sa_path)
elif GOOGLE_SERVICE_ACCOUNT_FILE:
    os.environ["GOOGLE_APPLICATION_CREDENTIALS"] = GOOGLE_SERVICE_ACCOUNT_FILE
