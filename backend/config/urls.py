"""Root URL configuration.

    GET  /api/v1/health          liveness + which providers are configured
    POST /api/v1/route-analysis  the full weather-aware route analysis
    POST /api/v1/corridor-forecast  the selected route's checkpoints at every
                                 hour from +0 to +48 after the analysis
                                 reference time, classified (display only)
    GET  /api/v1/places?q=       place-name suggestions for the trip form

Note on the path: Milestone 1's plan sketched this endpoint as
`/api/v1/analyze`. It ships as `/api/v1/route-analysis`, which says what it
returns rather than what it does. Nothing consumed the earlier name -- the
frontend is still a scaffold -- so there is no compatibility shim to keep.
"""

from django.urls import include, path

urlpatterns = [
    path("api/v1/", include("apps.routing.api.urls")),
]
