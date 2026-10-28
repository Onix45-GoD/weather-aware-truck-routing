"""Settings shared by every environment.

Deliberately minimal. This project has no models, no migrations and no
persistence requirement, so `django.contrib.auth`, `sessions`, `admin` and the
database are all absent. Adding them back would be unused surface area.
"""

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
