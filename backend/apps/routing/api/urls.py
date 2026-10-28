"""Routing app URLs, mounted under /api/v1/ by the project URL conf."""

from __future__ import annotations

from django.urls import path

from .views import HealthView, RouteAnalysisView, WeatherTileView

app_name = "routing"

urlpatterns = [
    path("health", HealthView.as_view(), name="health"),
    path("route-analysis", RouteAnalysisView.as_view(), name="route-analysis"),
    path(
        "weather-tiles/<str:layer>/<int:z>/<int:x>/<int:y>.png",
        WeatherTileView.as_view(),
        name="weather-tile",
    ),
]
