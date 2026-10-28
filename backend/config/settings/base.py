"""Settings shared by every environment.

Deliberately minimal. This project has no models, no migrations and no
persistence requirement, so `django.contrib.auth`, `sessions`, `admin` and the
database are all absent. Adding them back would be unused surface area.
"""

import os
from pathlib import Path

BASE_DIR = Path(__file__).resolve().parent.parent.parent

INSTALLED_APPS = [
    "django.contrib.staticfiles",
    "corsheaders",
    "rest_framework",
    "apps.routing",
]

# Order matters: SecurityMiddleware first so its headers apply to everything,
# CorsMiddleware before CommonMiddleware so CORS headers survive redirects,
# and XFrameOptionsMiddleware last to apply X_FRAME_OPTIONS (which is inert
# without it).
MIDDLEWARE = [
    "django.middleware.security.SecurityMiddleware",
    "corsheaders.middleware.CorsMiddleware",
    "django.middleware.common.CommonMiddleware",
    "django.middleware.clickjacking.XFrameOptionsMiddleware",
]

# CSRF protection is deliberately absent. This is a stateless JSON API with no
# cookies, no sessions and no authentication, so there are no ambient
# credentials for a cross-site request to ride on. Adding the middleware would
# silence the check without changing the threat model.
SILENCED_SYSTEM_CHECKS = ["security.W003"]

ROOT_URLCONF = "config.urls"
WSGI_APPLICATION = "config.wsgi.application"
ASGI_APPLICATION = "config.asgi.application"

TEMPLATES = [
    {
        "BACKEND": "django.template.backends.django.DjangoTemplates",
        "DIRS": [],
        "APP_DIRS": True,
        "OPTIONS": {"context_processors": []},
    }
]

# No database: the domain core is pure computation and nothing is persisted.
DATABASES: dict[str, dict[str, object]] = {}

LANGUAGE_CODE = "en-us"
TIME_ZONE = "UTC"
USE_I18N = False
USE_TZ = True

STATIC_URL = "static/"
STATIC_ROOT = BASE_DIR / "staticfiles"

DEFAULT_AUTO_FIELD = "django.db.models.BigAutoField"

REST_FRAMEWORK = {
    "DEFAULT_RENDERER_CLASSES": ["rest_framework.renderers.JSONRenderer"],
    "DEFAULT_PARSER_CLASSES": ["rest_framework.parsers.JSONParser"],
    "UNAUTHENTICATED_USER": None,
    "DEFAULT_AUTHENTICATION_CLASSES": [],
    "DEFAULT_PERMISSION_CLASSES": [],
}

# --- Provider selection -----------------------------------------------------
# Names match .env.example. `fixtures` is the default everywhere so the project
# runs, and its whole test suite passes, with no credentials of any kind.
ROUTING_PROVIDER = os.environ.get("ROUTING_PROVIDER", "fixtures")
GEOCODING_PROVIDER = os.environ.get("GEOCODING_PROVIDER", "fixtures")
WEATHER_PROVIDER = os.environ.get("WEATHER_PROVIDER", "open-meteo")

# Read here, never logged and never returned by any endpoint. The provider
# layer reports only whether a key is *present* -- see
# `apps.routing.providers.factory.provider_status`.
TOMTOM_API_KEY = os.environ.get("TOMTOM_API_KEY", "")

# Cache TTLs in seconds. Geocoding results are effectively static; forecasts
# are refreshed on the half hour; routes change with traffic.
PROVIDER_CACHE_TTL = {
    "geocoding": int(os.environ.get("CACHE_TTL_GEOCODING", 60 * 60 * 24 * 30)),
    "routing": int(os.environ.get("CACHE_TTL_ROUTING", 60 * 10)),
    "weather": int(os.environ.get("CACHE_TTL_WEATHER", 60 * 30)),
}

# In-process cache. Deliberately not Redis: nothing here needs to survive a
# restart or be shared between processes, and adding a broker would be a new
# deployment dependency for no benefit at this scale.
CACHES = {
    "default": {
        "BACKEND": "django.core.cache.backends.locmem.LocMemCache",
        "LOCATION": "weather-routing-providers",
        "TIMEOUT": 600,
        "OPTIONS": {"MAX_ENTRIES": 2000, "CULL_FREQUENCY": 4},
    }
}
