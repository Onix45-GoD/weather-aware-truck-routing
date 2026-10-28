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

from apps.routing.providers.factory import provider_status
from apps.routing.services.analysis import analyse_trip
from apps.routing.services.errors import AnalysisError
from apps.routing.providers.errors import ProviderError

from .errors import error_response, exception_to_response
from .serializers import RouteAnalysisRequestSerializer, serialise_analysis

__all__ = ["HealthView", "RouteAnalysisView"]

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
