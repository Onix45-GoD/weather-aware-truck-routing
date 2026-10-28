"""Settings shared by every environment.

Deliberately minimal. This project has no models, no migrations and no
persistence requirement, so `django.contrib.auth`, `sessions`, `admin` and the
database are all absent. Adding them back would be unused surface area.
"""

import os
from pathlib import Path

from dotenv import load_dotenv

BASE_DIR = Path(__file__).resolve().parent.parent.parent

# Load `backend/.env` when present, for local development. It is gitignored,
# and real credentials must only ever live there -- never in a tracked file,
# and never in a `VITE_*` variable, which ships to the browser.
#
# `override=False` means a variable already set in the real environment wins,
# so a deployment's configuration is never silently replaced by a stray file.
#
# **Never under pytest.** The suite must be hermetic: it asserts that the
# defaults need no credentials, and it must behave the same on a machine with
# a populated `.env` as on CI without one. Loading the file here made a test
# fail only on developer machines, which is exactly the class of bug that
# wastes an afternoon.
_RUNNING_TESTS = "PYTEST_VERSION" in os.environ

if not _RUNNING_TESTS:
    load_dotenv(BASE_DIR / ".env", override=False)

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

# Enables the weather-map tile proxy (`/api/v1/weather-tiles/...`). Optional:
# without it the endpoint answers 503 and the UI disables the overlay toggle.
# The key is only ever sent server-to-server; the browser gets tile bytes.
OPENWEATHERMAP_API_KEY = os.environ.get("OPENWEATHERMAP_API_KEY", "")

# Cache TTLs in seconds. Geocoding results are effectively static; forecasts
# are refreshed on the half hour; routes change with traffic; weather tiles
# are current conditions and go stale fastest.
PROVIDER_CACHE_TTL = {
    "geocoding": int(os.environ.get("CACHE_TTL_GEOCODING", 60 * 60 * 24 * 30)),
    "routing": int(os.environ.get("CACHE_TTL_ROUTING", 60 * 10)),
    "weather": int(os.environ.get("CACHE_TTL_WEATHER", 60 * 30)),
    # OpenWeatherMap refreshes its map tiles roughly every ten minutes.
    "weather_tiles": int(os.environ.get("CACHE_TTL_WEATHER_TILES", 60 * 10)),
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
