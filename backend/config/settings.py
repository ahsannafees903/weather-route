"""Environment-based settings for the routing API.

Local defaults run the development server with no secrets. Production
(Render) sets DJANGO_DEBUG=false and a generated DJANGO_SECRET_KEY.
"""

from __future__ import annotations

import os
import sys
from pathlib import Path

BASE_DIR = Path(__file__).resolve().parent.parent

SECRET_KEY = os.environ.get("DJANGO_SECRET_KEY", "dev-only-change-me")
DEBUG = os.environ.get("DJANGO_DEBUG", "true").lower() in {"1", "true", "yes", "on"}

_hosts = os.environ.get("DJANGO_ALLOWED_HOSTS", "*")
ALLOWED_HOSTS = [host.strip() for host in _hosts.split(",") if host.strip()]

INSTALLED_APPS = [
    "django.contrib.staticfiles",
    "corsheaders",
    "planner",
]

MIDDLEWARE = [
    "corsheaders.middleware.CorsMiddleware",
    "django.middleware.security.SecurityMiddleware",
    "whitenoise.middleware.WhiteNoiseMiddleware",
    "django.middleware.common.CommonMiddleware",
]

ROOT_URLCONF = "config.urls"
WSGI_APPLICATION = "config.wsgi.application"
ASGI_APPLICATION = "config.asgi.application"

DATABASES = {
    "default": {
        "ENGINE": "django.db.backends.sqlite3",
        "NAME": BASE_DIR / "db.sqlite3",
    }
}

LANGUAGE_CODE = "en-us"
TIME_ZONE = "UTC"
USE_I18N = True
USE_TZ = True

STATIC_URL = "static/"
STATIC_ROOT = BASE_DIR / "staticfiles"
STATIC_ROOT.mkdir(exist_ok=True)
STORAGES = {
    "staticfiles": {
        "BACKEND": "whitenoise.storage.CompressedStaticFilesStorage",
    },
}

DEFAULT_AUTO_FIELD = "django.db.models.BigAutoField"
APPEND_SLASH = False

_testing = "test" in sys.argv
if _testing:
    CACHES = {
        "default": {
            "BACKEND": "django.core.cache.backends.locmem.LocMemCache",
            "LOCATION": "planner-tests",
        }
    }
else:
    CACHE_DIR = BASE_DIR / ".cache"
    CACHE_DIR.mkdir(exist_ok=True)
    CACHES = {
        "default": {
            "BACKEND": "django.core.cache.backends.filebased.FileBasedCache",
            "LOCATION": str(CACHE_DIR),
            "TIMEOUT": 60 * 30,
            "OPTIONS": {"MAX_ENTRIES": 5000},
        }
    }

# A demo API with no credentials. Restrict this in a real deployment by
# setting CORS_ALLOW_ALL_ORIGINS=false and listing the frontend origin.
CORS_ALLOW_ALL_ORIGINS = os.environ.get("CORS_ALLOW_ALL_ORIGINS", "true").lower() in {
    "1",
    "true",
    "yes",
    "on",
}
if not CORS_ALLOW_ALL_ORIGINS:
    CORS_ALLOWED_ORIGINS = [
        origin.strip()
        for origin in os.environ.get("CORS_ALLOWED_ORIGINS", "").split(",")
        if origin.strip()
    ]

SECURE_PROXY_SSL_HEADER = ("HTTP_X_FORWARDED_PROTO", "https")

NOMINATIM_URL = os.environ.get(
    "NOMINATIM_URL", "https://nominatim.openstreetmap.org/search"
)
NOMINATIM_USER_AGENT = os.environ.get(
    "NOMINATIM_USER_AGENT",
    "WeatherAwareTruckRouting/1.0 (educational take-home assessment)",
)
NOMINATIM_MIN_INTERVAL = float(os.environ.get("NOMINATIM_MIN_INTERVAL", "1.1"))
OSRM_URL = os.environ.get("OSRM_URL", "https://router.project-osrm.org")
OPEN_METEO_URL = os.environ.get(
    "OPEN_METEO_URL", "https://api.open-meteo.com/v1/forecast"
)
HTTP_TIMEOUT_SECONDS = float(os.environ.get("HTTP_TIMEOUT_SECONDS", "25"))
UPSTREAM_RETRY_SLEEP_SECONDS = float(os.environ.get("UPSTREAM_RETRY_SLEEP_SECONDS", "0.5"))

if _testing:
    NOMINATIM_MIN_INTERVAL = 0.0
    UPSTREAM_RETRY_SLEEP_SECONDS = 0.0

LOGGING = {
    "version": 1,
    "disable_existing_loggers": False,
    "handlers": {"console": {"class": "logging.StreamHandler"}},
    "root": {"handlers": ["console"], "level": "INFO"},
}
