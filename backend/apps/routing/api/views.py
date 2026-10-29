"""HTTP views.

The view does three things and nothing else: validate, delegate, shape. Every
routing, weather and risk decision happens below it.
"""

from __future__ import annotations

import logging
import time

from rest_framework import status
from rest_framework.request import Request
from rest_framework.response import Response
from rest_framework.views import APIView

from apps.routing.providers.errors import ProviderError
from apps.routing.providers.factory import provider_status
from apps.routing.services.analysis import analyse_trip
from apps.routing.services.corridor import forecast_corridor
from apps.routing.services.errors import AnalysisError
from apps.routing.services.places import suggest_places

from .corridor import CorridorForecastRequestSerializer, serialise_corridor
from .errors import error_response, exception_to_response
from .serializers import RouteAnalysisRequestSerializer, serialise_analysis
from .throttling import ScopedThrottle

__all__ = ["CorridorForecastView", "HealthView", "PlacesView", "RouteAnalysisView"]

logger = logging.getLogger(__name__)

#: A place name is short; anything longer is not a search, it is a mistake.
MAX_QUERY_LENGTH = 120


class HealthView(APIView):
    """Liveness probe, plus which providers are configured.

    Reports only whether a credential is *present*, never any part of its
    value, so this is safe to expose and safe to log.
    """

    def get(self, _request: Request) -> Response:
        return Response({"status": "ok", "providers": provider_status()})


class RouteAnalysisView(APIView):
    """`POST /api/v1/route-analysis` -- the whole assessment in one call.

    Stateless: nothing is stored, no session is read, and two identical
    requests produce identical output for identical provider responses.
    """

    throttle_classes = [ScopedThrottle]
    throttle_scope = "analysis"

    def post(self, request: Request) -> Response:
        serializer = RouteAnalysisRequestSerializer(data=request.data)
        if not serializer.is_valid():
            # Field-level errors, so the form can attach each message to the
            # input that caused it.
            return error_response(
                code="INVALID_REQUEST",
                message="The trip details could not be validated.",
                http_status=status.HTTP_400_BAD_REQUEST,
                details=serializer.errors,
            )

        try:
            analysis_request = serializer.to_analysis_request()
        except ValueError as exc:
            # The service dataclass enforces the same invariants the
            # serializer does; reaching here means they disagreed, which is a
            # bug worth surfacing rather than a 500.
            return error_response(
                code="INVALID_REQUEST",
                message=str(exc),
                http_status=status.HTTP_400_BAD_REQUEST,
            )

        started = time.perf_counter()
        try:
            result = analyse_trip(analysis_request)
        except (ProviderError, AnalysisError) as exc:
            return exception_to_response(exc)
        except Exception as exc:  # noqa: BLE001 - deliberate catch-all
            return exception_to_response(exc)

        payload = serialise_analysis(result)
        # Notes raised while interpreting the input -- chiefly daylight-saving
        # oddities -- belong with the analysis warnings, not in a separate
        # channel the client has to remember to read.
        if serializer.input_warnings:
            payload["warnings"] = serializer.input_warnings + payload["warnings"]
        payload["meta"]["elapsed_ms"] = round(
            (time.perf_counter() - started) * 1000.0, 1
        )

        # A trip with no safe route is a successful analysis, not an error:
        # the answer "do not drive this" is exactly what the caller asked for.
        return Response(payload, status=status.HTTP_200_OK)


class CorridorForecastView(APIView):
    """`POST /api/v1/corridor-forecast` -- the 0-48 h corridor frames.

    Display-only. Frame +N is `reference_at + N hours` at every checkpoint,
    classified with the same domain functions as the analysis. It cannot
    change the departure, the ETAs or the recommendation (D28); it is a
    second view of the same forecast, not a second analysis.
    """

    throttle_classes = [ScopedThrottle]
    throttle_scope = "corridor"

    def post(self, request: Request) -> Response:
        serializer = CorridorForecastRequestSerializer(data=request.data)
        if not serializer.is_valid():
            return error_response(
                code="INVALID_REQUEST",
                message="The corridor request could not be validated.",
                http_status=status.HTTP_400_BAD_REQUEST,
                details=serializer.errors,
            )
        data = serializer.validated_data

        started = time.perf_counter()
        try:
            result = forecast_corridor(
                data["reference_at"],
                data["load_weight_lb"],
                serializer.corridor_checkpoints(),
            )
        except ValueError as exc:
            # The serializer enforces the same invariants the service does;
            # disagreeing is a bug worth a 400 with the message, not a 500.
            return error_response(
                code="INVALID_REQUEST",
                message=str(exc),
                http_status=status.HTTP_400_BAD_REQUEST,
            )
        except ProviderError as exc:
            return exception_to_response(exc)
        except Exception as exc:  # noqa: BLE001 - deliberate catch-all
            return exception_to_response(exc)

        payload = serialise_corridor(
            result,
            route_id=data.get("route_id") or None,
            zone_name=data.get("timezone"),
        )
        payload["meta"] = {
            "elapsed_ms": round((time.perf_counter() - started) * 1000.0, 1),
            "checkpoints": len(result.checkpoints),
            "frames": len(result.frames),
        }
        return Response(payload, status=status.HTTP_200_OK)


class PlacesView(APIView):
    """`GET /api/v1/places?q=` -- type-ahead suggestions for the trip form.

    The same geocoding provider the analysis uses, so a suggestion the user
    picks is a place the analysis will resolve. Too-short queries get an
    empty list rather than an error: the form calls this on every keystroke.
    """

    throttle_classes = [ScopedThrottle]
    throttle_scope = "places"

    def get(self, request: Request) -> Response:
        query = str(request.query_params.get("q", "")).strip()
        if len(query) > MAX_QUERY_LENGTH:
            return error_response(
                code="INVALID_REQUEST",
                message=f"Queries are limited to {MAX_QUERY_LENGTH} characters.",
                http_status=status.HTTP_400_BAD_REQUEST,
            )
        try:
            suggestions = suggest_places(query)
        except ProviderError as exc:
            return exception_to_response(exc)

        return Response(
            {
                "query": query,
                "suggestions": [
                    {
                        "label": item.label,
                        "latitude": round(item.coordinate.latitude, 6),
                        "longitude": round(item.coordinate.longitude, 6),
                    }
                    for item in suggestions
                ],
            },
            status=status.HTTP_200_OK,
        )
