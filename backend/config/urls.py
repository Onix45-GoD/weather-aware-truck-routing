"""Root URL configuration.

    GET  /api/v1/health          liveness + which providers are configured
    POST /api/v1/route-analysis  the full weather-aware route analysis
    GET  /api/v1/weather-tiles/<layer>/<z>/<x>/<y>.png
                                 OpenWeatherMap raster tiles, proxied so the
                                 key stays on the server

Note on the path: Milestone 1's plan sketched this endpoint as
`/api/v1/analyze`. It ships as `/api/v1/route-analysis`, which says what it
returns rather than what it does. Nothing consumed the earlier name -- the
frontend is still a scaffold -- so there is no compatibility shim to keep.
"""

from django.urls import include, path

urlpatterns = [
    path("api/v1/", include("apps.routing.api.urls")),
]
