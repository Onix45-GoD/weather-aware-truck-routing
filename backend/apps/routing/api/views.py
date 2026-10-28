"""HTTP views.

The view does three things and nothing else: validate, delegate, shape. Every
routing, weather and risk decision happens below it.
"""

from __future__ import annotations

import logging
import time

from django.http import HttpResponse
from rest_framework import status
from rest_framework.request import Request
from rest_framework.response import Response
from rest_framework.views import APIView

from apps.routing.providers.errors import ProviderConfigurationError, ProviderError
from apps.routing.providers.factory import provider_status
from apps.routing.services.analysis import analyse_trip
from apps.routing.services.checkpoint_weather import fetch_checkpoint_weather
from apps.routing.services.errors import AnalysisError
from apps.routing.services.weather_tiles import (
    WEATHER_TILE_LAYERS,
    fetch_weather_tile,
    tile_coordinates_are_valid,
)

from .checkpoint_weather import (
    CheckpointWeatherQuerySerializer,
    serialise_checkpoint_weather,
)
from .errors import error_response, exception_to_response
from .serializers import RouteAnalysisRequestSerializer, serialise_analysis

__all__ = [
    "CheckpointWeatherView",
    "HealthView",
    "RouteAnalysisView",
    "WeatherTileView",
]

logger = logging.getLogger(__name__)


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


class WeatherTileView(APIView):
    """`GET /api/v1/weather-tiles/<layer>/<z>/<x>/<y>.png` -- a tile proxy.

    The browser's map asks here for OpenWeatherMap raster tiles; the service
    adds the key, fetches, caches and hands back the PNG. The key is the whole
    reason the endpoint exists: it must never be embedded in a tile URL the
    browser can read.

    Success is a raw image response, so DRF's JSON renderer is bypassed on
    that path. Failures use the same error envelope as every other endpoint.
    """

    def get(
        self, _request: Request, layer: str, z: int, x: int, y: int
    ) -> Response | HttpResponse:
        if layer not in WEATHER_TILE_LAYERS:
            return error_response(
                code="UNKNOWN_TILE_LAYER",
                message=(
                    f"Unknown weather layer {layer!r}. Expected one of: "
                    + ", ".join(sorted(WEATHER_TILE_LAYERS))
                    + "."
                ),
                http_status=status.HTTP_404_NOT_FOUND,
            )
        if not tile_coordinates_are_valid(z, x, y):
            return error_response(
                code="INVALID_TILE",
                message=f"Tile {z}/{x}/{y} is outside the supported range.",
                http_status=status.HTTP_400_BAD_REQUEST,
            )

        try:
            tile = fetch_weather_tile(layer, z, x, y)
        except ProviderConfigurationError as exc:
            # Not an outage: the feature is simply switched off on this
            # deployment. 503 with a stable code lets the UI disable the
            # control instead of showing broken tiles.
            return error_response(
                code="WEATHER_TILES_NOT_CONFIGURED",
                message=str(exc),
                http_status=status.HTTP_503_SERVICE_UNAVAILABLE,
            )
        except ProviderError as exc:
            return exception_to_response(exc)

        response = HttpResponse(tile.png, content_type="image/png")
        # Let the browser reuse the tile for as long as the server would.
        response["Cache-Control"] = f"public, max-age={tile.max_age_seconds}"
        return response


class CheckpointWeatherView(APIView):
    """`GET /api/v1/checkpoint-weather?lat=&lon=&at=` -- weather at one point.

    Descriptive context for a checkpoint the driver clicked: observed
    conditions now, the 3-hourly forecast, and the slot nearest the ETA.
    It is read-only decoration over the analysis; the risk levels were
    computed from Open-Meteo before this is ever called and are not touched.
    """

    def get(self, request: Request) -> Response:
        query = CheckpointWeatherQuerySerializer(data=request.query_params)
        if not query.is_valid():
            return error_response(
                code="INVALID_REQUEST",
                message="The checkpoint location could not be validated.",
                http_status=status.HTTP_400_BAD_REQUEST,
                details=query.errors,
            )

        try:
            result = fetch_checkpoint_weather(query.coordinate(), query.eta())
        except ProviderConfigurationError as exc:
            return error_response(
                code="CHECKPOINT_WEATHER_NOT_CONFIGURED",
                message=str(exc),
                http_status=status.HTTP_503_SERVICE_UNAVAILABLE,
            )
        except ProviderError as exc:
            return exception_to_response(exc)

        return Response(serialise_checkpoint_weather(result), status=status.HTTP_200_OK)
