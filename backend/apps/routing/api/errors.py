"""Mapping typed errors to HTTP responses.

Three rules hold everywhere here:

1. **Status codes carry meaning.** A trip with no safe route is a *successful*
   analysis (200) with `recommended_route_id: null`. An upstream outage is
   502. Returning 200 for everything would make both indistinguishable to a
   client, and the difference is the whole point of the recommendation.
2. **Messages are safe to show a user.** No stack traces, no upstream bodies,
   no URLs, and never a credential -- provider errors are already written to
   be log-safe, and the catch-all never echoes the underlying exception.
3. **Every response has the same shape**, so a typed client needs one error
   model rather than one per endpoint.
"""

from __future__ import annotations

import logging
from typing import Any

from rest_framework import status
from rest_framework.response import Response

from apps.routing.providers.errors import (
    GeocodingNoResultsError,
    InvalidProviderResponseError,
    ProviderAuthError,
    ProviderConfigurationError,
    ProviderError,
    ProviderRateLimitError,
    ProviderTimeoutError,
    ProviderUnavailableError,
    RoutingNoRoutesError,
    WeatherUnavailableError,
)
from apps.routing.services.errors import AmbiguousLocationError, AnalysisError

__all__ = ["error_response", "exception_to_response"]

logger = logging.getLogger(__name__)

#: Exception type -> HTTP status. Order matters only in that subclasses are
#: resolved before their bases by `exception_to_response`.
_STATUS_BY_TYPE: tuple[tuple[type[Exception], int], ...] = (
    # User-input problems: the request itself is at fault.
    (GeocodingNoResultsError, status.HTTP_400_BAD_REQUEST),
    (AmbiguousLocationError, status.HTTP_400_BAD_REQUEST),
    # A valid request that this pair of locations cannot satisfy.
    (RoutingNoRoutesError, status.HTTP_422_UNPROCESSABLE_ENTITY),
    # Our configuration is wrong -- not the caller's fault, and not
    # something a retry fixes.
    (ProviderConfigurationError, status.HTTP_500_INTERNAL_SERVER_ERROR),
    (ProviderAuthError, status.HTTP_502_BAD_GATEWAY),
    # Upstream trouble. 429 and 504 are forwarded as themselves so a client
    # can back off intelligently rather than guessing.
    (ProviderRateLimitError, status.HTTP_429_TOO_MANY_REQUESTS),
    (ProviderTimeoutError, status.HTTP_504_GATEWAY_TIMEOUT),
    (InvalidProviderResponseError, status.HTTP_502_BAD_GATEWAY),
    (WeatherUnavailableError, status.HTTP_502_BAD_GATEWAY),
    (ProviderUnavailableError, status.HTTP_502_BAD_GATEWAY),
    (ProviderError, status.HTTP_502_BAD_GATEWAY),
    (AnalysisError, status.HTTP_400_BAD_REQUEST),
)


def error_response(
    code: str,
    message: str,
    http_status: int,
    *,
    field: str | None = None,
    details: Any = None,
    retry_after_seconds: float | None = None,
) -> Response:
    """Build the one error envelope every failure uses."""
    payload: dict[str, Any] = {
        "error": {
            "code": code,
            "message": message,
            "field": field,
            "details": details,
        }
    }
    response = Response(payload, status=http_status)
    if retry_after_seconds is not None:
        # Standard header, so a client can honour the provider's own backoff.
        response["Retry-After"] = str(int(max(0, retry_after_seconds)))
    return response


def exception_to_response(exc: Exception) -> Response:
    """Translate a known exception into its HTTP response.

    Anything unrecognised becomes a generic 500 whose message says nothing
    about the internals. The real exception is logged with a traceback for
    operators; the client gets a stable code and nothing else.
    """
    for exception_type, http_status in _STATUS_BY_TYPE:
        if isinstance(exc, exception_type):
            return _known_error_response(exc, http_status)

    logger.exception("unhandled error during route analysis")
    return error_response(
        code="INTERNAL_ERROR",
        message="Something went wrong while analysing this trip. Please try again.",
        http_status=status.HTTP_500_INTERNAL_SERVER_ERROR,
    )


def _known_error_response(exc: Exception, http_status: int) -> Response:
    code = getattr(exc, "code", "PROVIDER_ERROR")
    # `str(ProviderError)` prefixes the provider name, which is useful context
    # and contains no secret -- adapters build these messages deliberately.
    message = str(exc)
    field = getattr(exc, "field", None)

    if isinstance(exc, GeocodingNoResultsError):
        # The adapter does not know which input it was resolving; the service
        # does, but a no-results error can also arrive from a bare geocode.
        field = field or None

    retry_after = getattr(exc, "retry_after_seconds", None)

    if http_status >= 500:
        logger.warning("upstream failure (%s): %s", code, message)

    return error_response(
        code=code,
        message=message,
        http_status=http_status,
        field=field,
        retry_after_seconds=retry_after,
    )
