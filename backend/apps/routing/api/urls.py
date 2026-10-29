"""Routing app URLs, mounted under /api/v1/ by the project URL conf."""

from __future__ import annotations

from django.urls import path

from .views import (
    CorridorForecastView,
    HealthView,
    PlacesView,
    RouteAnalysisView,
)

app_name = "routing"

urlpatterns = [
    path("health", HealthView.as_view(), name="health"),
    path("route-analysis", RouteAnalysisView.as_view(), name="route-analysis"),
    path(
        "corridor-forecast",
        CorridorForecastView.as_view(),
        name="corridor-forecast",
    ),
    path("places", PlacesView.as_view(), name="places"),
]
