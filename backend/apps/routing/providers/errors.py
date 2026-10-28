"""Typed provider errors.

Every error carries a ``code`` that the API layer can map to a stable
machine-readable value, and a ``message`` written to be safe for logs and for
eventual display to a user. Provider credentials never appear in either --
see :func:`apps.routing.providers.http.redact`.
"""

from __future__ import annotations

__all__ = [
    "GeocodingNoResultsError",
    "InvalidProviderResponseError",
    "ProviderAuthError",
    "ProviderConfigurationError",
    "ProviderError",
    "ProviderRateLimitError",
    "ProviderTimeoutError",
    "ProviderUnavailableError",
    "RoutingNoRoutesError",
    "WeatherUnavailableError",
]


class ProviderError(Exception):
    """Base class for every failure originating outside the domain.

    Catching this one type lets the orchestration layer degrade gracefully
    without enumerating provider internals.
    """

    code = "PROVIDER_ERROR"

    def __init__(self, message: str, *, provider: str | None = None) -> None:
        self.provider = provider
        self.message = message
        super().__init__(message)

    def __str__(self) -> str:
        if self.provider:
            return f"[{self.provider}] {self.message}"
        return self.message


class ProviderConfigurationError(ProviderError):
    """A provider is selected but not usable -- typically a missing API key.

    Raised at construction time rather than on first request, so a
    misconfiguration surfaces at startup instead of mid-analysis.
    """

    code = "PROVIDER_MISCONFIGURED"


class ProviderAuthError(ProviderError):
    """The provider rejected our credentials (HTTP 401/403). Never retried."""

    code = "PROVIDER_AUTH_FAILED"


class ProviderRateLimitError(ProviderError):
    """The provider rate-limited us (HTTP 429).

    ``retry_after_seconds`` carries the provider's ``Retry-After`` header when
    it sent one, so the caller can report a meaningful wait rather than a bare
    failure.
    """

    code = "PROVIDER_RATE_LIMITED"

    def __init__(
        self,
        message: str,
        *,
        provider: str | None = None,
        retry_after_seconds: float | None = None,
    ) -> None:
        self.retry_after_seconds = retry_after_seconds
        super().__init__(message, provider=provider)


class ProviderTimeoutError(ProviderError):
    """The provider did not respond within the configured timeout."""

    code = "PROVIDER_TIMEOUT"


class ProviderUnavailableError(ProviderError):
    """The provider is reachable but failing (HTTP 5xx), or unreachable."""

    code = "PROVIDER_UNAVAILABLE"


class InvalidProviderResponseError(ProviderError):
    """The provider answered, but not in a shape we can trust.

    Deliberately distinct from :class:`ProviderUnavailableError`: a malformed
    payload is a contract violation, not a transient outage, so retrying it
    would only waste quota. This is also what guards the unit contract -- if
    the weather provider ever changes the units it returns, parsing fails
    loudly here rather than silently misclassifying every checkpoint.
    """

    code = "PROVIDER_INVALID_RESPONSE"


class GeocodingNoResultsError(ProviderError):
    """The address was understood but matched nothing.

    A user-input problem, not a provider fault, so it maps to HTTP 400 rather
    than 502 at the API boundary.
    """

    code = "GEOCODING_NO_RESULTS"

    def __init__(self, message: str, *, provider: str | None = None, query: str = "") -> None:
        self.query = query
        super().__init__(message, provider=provider)


class RoutingNoRoutesError(ProviderError):
    """The provider could not route between the two points at all."""

    code = "ROUTING_NO_ROUTES"


class WeatherUnavailableError(ProviderError):
    """No usable forecast could be obtained for the requested points.

    Note this means a *total* failure. Individual missing values inside an
    otherwise valid response are represented as ``None`` on
    :class:`~apps.routing.domain.models.WeatherSample` and classify as
    ``UNKNOWN``; they never raise and are never silently replaced with zero.
    """

    code = "WEATHER_UNAVAILABLE"
