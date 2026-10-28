"""Root URL configuration.

Milestone 1 exposes only a health probe. The `/api/v1/analyze` endpoint is
added in Milestone 3 once the provider adapters exist.
"""

from django.http import HttpRequest, JsonResponse
from django.urls import path


def health(_request: HttpRequest) -> JsonResponse:
    return JsonResponse({"status": "ok", "milestone": 1})


urlpatterns = [
    path("api/v1/health", health, name="health"),
]
