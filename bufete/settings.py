import os
from pathlib import Path
import dj_database_url
from dotenv import load_dotenv

load_dotenv()

BASE_DIR = Path(__file__).resolve().parent.parent



DEBUG = os.environ.get("DEBUG", "false").lower() == "true"
if DEBUG:
    os.environ["OAUTHLIB_INSECURE_TRANSPORT"] = "1"
    
# ===== Seguridad / entorno =====
SECRET_KEY = os.environ.get("SECRET_KEY", "change-me")
DEBUG = os.environ.get("DEBUG", "false").lower() == "true"

ALLOWED_HOSTS = os.environ.get(
    "ALLOWED_HOSTS",
    "confidencia.onrender.com,.onrender.com,localhost,127.0.0.1"
).split(",")

CSRF_TRUSTED_ORIGINS = [
    "https://confidencia.onrender.com",
    "https://*.onrender.com",
]

SECURE_PROXY_SSL_HEADER = ("HTTP_X_FORWARDED_PROTO", "https")
if not DEBUG:
    SESSION_COOKIE_SECURE = True
    CSRF_COOKIE_SECURE = True

# ===== Google Drive / Service Account =====
GOOGLE_SHARED_DRIVE_ID = os.getenv("GOOGLE_SHARED_DRIVE_ID", "")
GOOGLE_SERVICE_ACCOUNT_JSON = os.getenv("GOOGLE_SERVICE_ACCOUNT_JSON")
GOOGLE_SERVICE_ACCOUNT_FILE = os.getenv("GOOGLE_SERVICE_ACCOUNT_FILE")

if GOOGLE_SERVICE_ACCOUNT_JSON and not GOOGLE_SERVICE_ACCOUNT_FILE:
    import tempfile
    sa_path = Path(tempfile.gettempdir()) / "google_sa.json"
    sa_path.write_text(GOOGLE_SERVICE_ACCOUNT_JSON, encoding="utf-8")
    os.environ["GOOGLE_APPLICATION_CREDENTIALS"] = str(sa_path)
elif GOOGLE_SERVICE_ACCOUNT_FILE:
    os.environ["GOOGLE_APPLICATION_CREDENTIALS"] = GOOGLE_SERVICE_ACCOUNT_FILE

# ===== Apps =====
INSTALLED_APPS = [
    'django.contrib.admin',
    'django.contrib.auth',
    'django.contrib.contenttypes',
    'django.contrib.sessions',
    'django.contrib.messages',
    'django.contrib.staticfiles',
    'rest_framework',
    'django_filters',
    'widget_tweaks',
    'core',
    'accounts',
    'clients',
    'cases',
    'documents',
    'audit',
]

# ===== Middleware =====
MIDDLEWARE = [
    'django.middleware.security.SecurityMiddleware',
    *(['whitenoise.middleware.WhiteNoiseMiddleware'] if not DEBUG else []),
    'django.contrib.sessions.middleware.SessionMiddleware',
    'django.middleware.common.CommonMiddleware',
    'django.middleware.csrf.CsrfViewMiddleware',
    'django.contrib.auth.middleware.AuthenticationMiddleware',
    'django.contrib.messages.middleware.MessageMiddleware',
    'django.middleware.clickjacking.XFrameOptionsMiddleware',
]

ROOT_URLCONF = 'bufete.urls'
WSGI_APPLICATION = 'bufete.wsgi.application'

TEMPLATES = [{
    'BACKEND': 'django.template.backends.django.DjangoTemplates',
    'DIRS': [BASE_DIR / "templates"],
    'APP_DIRS': True,
    'OPTIONS': {
        'context_processors': [
            'django.template.context_processors.debug',
            'django.template.context_processors.request',
            'django.contrib.auth.context_processors.auth',
            'django.contrib.messages.context_processors.messages',
        ],
    },
}]

# ===== Base de datos =====
if os.environ.get("DATABASE_URL"):
    db = dj_database_url.config(conn_max_age=600, ssl_require=False)
    db.setdefault("OPTIONS", {})
    db["OPTIONS"]["sslmode"] = "disable"
    DATABASES = {"default": db}
else:
    DATABASES = {
        'default': {
            "ENGINE": "django.db.backends.postgresql",
            "NAME": os.getenv("DB_NAME", "bufete_dev"),
            "USER": os.getenv("DB_USER", "bufete_user"),
            "PASSWORD": os.getenv("DB_PASS", "bufete_pass"),
            "HOST": os.getenv("DB_HOST", "127.0.0.1"),
            "PORT": os.getenv("DB_PORT", "5432"),
        }
    }

# ===== Idioma y Zona horaria =====
LANGUAGE_CODE = 'es-cl'   # idioma único (sin internacionalización)
TIME_ZONE = 'America/Santiago'
USE_I18N = False
USE_TZ = True

# ===== Archivos estáticos =====
STATIC_URL = '/static/'
STATIC_ROOT = BASE_DIR / "staticfiles"
STATICFILES_DIRS = [BASE_DIR / "static"] if (BASE_DIR / "static").exists() else []

if not DEBUG:
    STATICFILES_STORAGE = "whitenoise.storage.CompressedManifestStaticFilesStorage"

# ===== Autenticación =====
DEFAULT_AUTO_FIELD = 'django.db.models.BigAutoField'
AUTH_USER_MODEL = 'accounts.Usuario'
LOGIN_URL = "accounts:login"
LOGIN_REDIRECT_URL = "core:home"


GOOGLE_CALENDAR_CREDENTIALS = os.getenv("GOOGLE_CALENDAR_CREDENTIALS", "")
GOOGLE_REDIRECT_URI = os.getenv("GOOGLE_REDIRECT_URI", "http://127.0.0.1:8000/accounts/google/callback/")
GOOGLE_CALENDAR_SCOPES = [
    "https://www.googleapis.com/auth/calendar.readonly",
    "https://www.googleapis.com/auth/calendar.events",
    "openid", "email", "profile",
]


# === Google OAuth (Calendar) ===
GOOGLE_OAUTH_CLIENT_SECRETS_FILE = (
    os.getenv("GOOGLE_OAUTH_CLIENT_SECRETS_FILE", "")
    or os.getenv("GOOGLE_OAUTH_CLIENT_FILE", "")  # compat con tu .env actual
)
GOOGLE_OAUTH_CLIENT_SECRETS_FILE = os.getenv("GOOGLE_OAUTH_CLIENT_FILE", "").strip()
GOOGLE_OAUTH_CLIENT_SECRETS_JSON = os.getenv("GOOGLE_OAUTH_CLIENT_JSON", "").strip()

GOOGLE_OAUTH_SECRETS_RESOLVED = ""
if GOOGLE_OAUTH_CLIENT_SECRETS_JSON:
    import tempfile
    from pathlib import Path
    tmp = Path(tempfile.gettempdir()) / "google_oauth_client_secret.json"
    tmp.write_text(GOOGLE_OAUTH_CLIENT_SECRETS_JSON, encoding="utf-8")
    GOOGLE_OAUTH_SECRETS_RESOLVED = str(tmp)
elif GOOGLE_OAUTH_CLIENT_SECRETS_FILE:
    GOOGLE_OAUTH_SECRETS_RESOLVED = GOOGLE_OAUTH_CLIENT_SECRETS_FILE

SESSION_COOKIE_SECURE = False
SESSION_COOKIE_SAMESITE = "Lax"    