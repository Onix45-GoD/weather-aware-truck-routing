"""Local development settings."""

from .base import *  # noqa: F401,F403

DEBUG = True

# Development-only placeholder. Production reads DJANGO_SECRET_KEY from the
# environment (see config/settings/prod.py); no real secret lives in the repo.
SECRET_KEY = "django-insecure-dev-only-not-used-in-production"

ALLOWED_HOSTS = ["localhost", "127.0.0.1", "[::1]"]

CORS_ALLOWED_ORIGINS = ["http://localhost:5173", "http://127.0.0.1:5173"]
