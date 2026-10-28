import json
import os
import sys

from . import config

cfg = config.load()

BASE_DIR = config.BACKEND_DIR
DATA_DIR = config.DATA_DIR
SECRET_KEY = cfg["secret_key"]
DEBUG = os.environ.get("BUILDWEB_DEBUG") == "1"
TESTING = len(sys.argv) > 1 and sys.argv[1] == "test"
VERSION = os.environ.get("BUILDWEB_VERSION", "dev")
ADMIN_PORT = int(os.environ.get("BUILDWEB_PORT", "5050"))

# The editor only listens on 127.0.0.1; the public hosting server serves published sites on the LAN,
# so any Host header is accepted.
ALLOWED_HOSTS = ["*"]

INSTALLED_APPS = [
    "django.contrib.admin",
    "django.contrib.auth",
    "django.contrib.contenttypes",
    "django.contrib.sessions",
    "django.contrib.messages",
    "django.contrib.staticfiles",
    "builder",
]

MIDDLEWARE = [
    "builder.middleware.PublicSiteMiddleware",
    "django.middleware.security.SecurityMiddleware",
    "django.contrib.sessions.middleware.SessionMiddleware",
    "django.middleware.common.CommonMiddleware",
    "django.middleware.csrf.CsrfViewMiddleware",
    "django.contrib.auth.middleware.AuthenticationMiddleware",
    "builder.middleware.LocalAdminMiddleware",
    "builder.middleware.DatabaseSafeModeMiddleware",
    "django.contrib.messages.middleware.MessageMiddleware",
]

ROOT_URLCONF = "buildweb.urls"

TEMPLATES = [
    {
        "BACKEND": "django.template.backends.django.DjangoTemplates",
        "DIRS": [],
        "APP_DIRS": True,
        "OPTIONS": {
            "context_processors": [
                "django.template.context_processors.request",
                "django.contrib.auth.context_processors.auth",
                "django.contrib.messages.context_processors.messages",
                "builder.context.app_context",
            ],
        },
    },
]

WSGI_APPLICATION = "buildweb.wsgi.application"

# BUILDWEB_DB_OVERRIDE lets the database migration tool run manage.py against a target database.
_db = json.loads(os.environ["BUILDWEB_DB_OVERRIDE"]) if os.environ.get("BUILDWEB_DB_OVERRIDE") else cfg["db"]
# run.py sets BUILDWEB_DB_FAILED when MySQL is unreachable at start: fall back to SQLite in safe mode
# (only the settings page works) so the user can fix the connection from the app.
DB_FAILED = os.environ.get("BUILDWEB_DB_FAILED", "")
if DB_FAILED and not os.environ.get("BUILDWEB_DB_OVERRIDE"):
    _db = dict(config.DEFAULTS["db"])
DATABASES = {"default": config.django_database(_db)}
DB_ENGINE = _db.get("engine", "sqlite")

DEFAULT_AUTO_FIELD = "django.db.models.BigAutoField"
AUTH_PASSWORD_VALIDATORS = []

LANGUAGE_CODE = "th"
TIME_ZONE = "Asia/Bangkok"
USE_I18N = True
USE_TZ = True

STATIC_URL = "/static/"
STATIC_ROOT = DATA_DIR / "static"
MEDIA_URL = "/media/"
MEDIA_ROOT = DATA_DIR / "media"
EXPORT_DIR = DATA_DIR / "exports"

DATA_UPLOAD_MAX_MEMORY_SIZE = 50 * 1024 * 1024
FILE_UPLOAD_MAX_MEMORY_SIZE = 10 * 1024 * 1024
DATA_UPLOAD_MAX_NUMBER_FIELDS = 10000

SESSION_COOKIE_NAME = "buildweb_session"
CSRF_COOKIE_NAME = "buildweb_csrf"
SESSION_COOKIE_AGE = 60 * 60 * 24 * 365
X_FRAME_OPTIONS = "SAMEORIGIN"

LOGGING = {
    "version": 1,
    "disable_existing_loggers": False,
    "handlers": {"console": {"class": "logging.StreamHandler"}},
    "root": {"handlers": ["console"], "level": "WARNING"},
    "loggers": {"buildweb": {"handlers": ["console"], "level": "INFO", "propagate": False}},
}
