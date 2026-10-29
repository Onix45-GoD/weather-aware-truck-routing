"""Route-analysis orchestration.

Carries values between the provider layer and the domain layer, in this order:

    geocode -> route -> checkpoints -> weather -> risk -> rank

Every decision along the way belongs to the domain. This module decides
*nothing* about risk: it does not know a threshold, a mileage rule or a
ranking criterion. If a number in the response looks wrong, the bug is in
``apps.routing.domain`` or in the provider that supplied the input -- not
here. ``test_architecture.py`` fails the build if that stops being true.
"""

from __future__ import annotations

import logging
from collections.abc import Sequence
from math import ceil
from dataclasses import dataclass, field
from datetime import datetime, timedelta
from typing import Final

from django.conf import settings

from apps.routing.domain.aggregation import assess_route, summarise_route
from apps.routing.domain.checkpoints import generate_checkpoints
from apps.routing.domain.models import (
    AssessedCheckpoint,
    CheckpointInterval,
    Coordinate,
    RouteCandidate,
    RouteMetrics,
    WeatherSample,
)
from apps.routing.domain.ranking import MIN_COVERAGE_PCT, RankingResult, rank_routes
from apps.routing.domain.units import pounds_to_kilograms
from apps.routing.providers.base import (
    GeocodeResult,
    GeocodingProvider,
    HourlyForecast,
    RoutingProvider,
    WeatherProvider,
)
from apps.routing.providers.errors import ProviderError, WeatherUnavailableError
from apps.routing.providers.factory import (
    get_geocoding_provider,
    get_routing_provider,
    get_weather_provider,
)
from apps.routing.providers.http import run_bounded

from .errors import AmbiguousLocationError

__all__ = [
    "AnalysedRoute",
    "AnalysisRequest",
    "AnalysisResult",
    "AnalysisWarning",
    "MAX_CHECKPOINTS_PER_ROUTE",
    "MAX_FORECAST_OFFSET_HOURS",
    "analyse_trip",
]

logger = logging.getLogger(__name__)

#: Upper bound on `forecast_offset_hours`. Matches the forecast horizon the
#: corridor view is specified against; see D28 for why this is a departure
#: shift and not the heatmap slider.
MAX_FORECAST_OFFSET_HOURS: Final = 48

#: Ceiling on checkpoints per route, closing the open item recorded at the end
#: of docs/decisions.md. A 2,000-mile route at 10-mile spacing is 200
#: checkpoints; three alternatives make 600 forecast lookups. Rather than time
#: out, the interval is coarsened and a warning says so.
MAX_CHECKPOINTS_PER_ROUTE: Final = 300

#: Geometry simplification tolerance for the response, in miles (~8 m).
#: Analysis always uses full-resolution geometry; only the payload is reduced.
GEOMETRY_TOLERANCE_MILES: Final = 0.005

#: Below this, a geocoding match is treated as too ambiguous to route from.
DEFAULT_MIN_GEOCODE_CONFIDENCE: Final = 0.5


@dataclass(frozen=True, slots=True)
class AnalysisWarning:
    """Something the caller should know that is not a failure."""

    code: str
    message: str
    route_id: str | None = None


@dataclass(frozen=True, slots=True)
class AnalysisRequest:
    """Validated, normalised trip inputs.

    ``departure_at`` is timezone-aware. ``forecast_offset_hours`` shifts the
    whole analysis later (D28): routing, checkpoint ETAs, weather lookups and
    therefore the recommendation all use :attr:`effective_departure_at`.
    """

    origin: str
    destination: str
    departure_at: datetime
    load_weight_lb: float
    checkpoint_interval_miles: int
    forecast_offset_hours: int = 0
    #: IANA name the departure was expressed in, carried for display only.
    #: The analysis itself runs entirely in UTC -- a timezone cannot change
    #: an instant, so it cannot change a result.
    departure_timezone: str | None = None

    def __post_init__(self) -> None:
        if self.departure_at.tzinfo is None:
            raise ValueError("departure_at must be timezone-aware")
        if self.load_weight_lb <= 0:
            raise ValueError("load_weight_lb must be positive")
        if not 0 <= self.forecast_offset_hours <= MAX_FORECAST_OFFSET_HOURS:
            raise ValueError(
                f"forecast_offset_hours must be 0..{MAX_FORECAST_OFFSET_HOURS}"
            )
        if self.checkpoint_interval_miles not in {
            int(value) for value in CheckpointInterval
        }:
            raise ValueError("checkpoint_interval_miles must be 10, 25 or 50")

    #: Empty tractor + trailer weight, in pounds, added to the cargo to form
    #: the gross weight the routing provider is given (D16).
    tare_weight_lb: float = 35_000.0

    @property
    def gross_weight_lb(self) -> float:
        return self.load_weight_lb + self.tare_weight_lb

    @property
    def vehicle_weight_kg(self) -> float:
        """What the routing provider is asked to route for."""
        return pounds_to_kilograms(self.gross_weight_lb)

    @property
    def effective_departure_at(self) -> datetime:
        """When the truck actually leaves, once the offset is applied."""
        return self.departure_at + timedelta(hours=self.forecast_offset_hours)


@dataclass(frozen=True, slots=True)
class AnalysedRoute:
    """One route with its checkpoints, risk and metrics."""

    route: RouteCandidate
    checkpoints: tuple[AssessedCheckpoint, ...]
    metrics: RouteMetrics
    #: "provider_segments" when the provider supplied per-segment timings,
    #: "distance_proportional" when the documented fallback was used (D13).
    eta_source: str
    #: Vertices before display simplification, so the reduction is visible.
    geometry_points: int

    @property
    def arrival_at(self) -> datetime:
        return self.checkpoints[-1].checkpoint.eta


@dataclass(frozen=True, slots=True)
class AnalysisResult:
    """Everything the API layer needs to render a response."""

    request: AnalysisRequest
    origin: GeocodeResult
    destination: GeocodeResult
    routes: tuple[AnalysedRoute, ...]
    ranking: RankingResult
    warnings: tuple[AnalysisWarning, ...] = field(default_factory=tuple)
    providers: dict[str, str] = field(default_factory=dict)
    routes_returned_by_provider: int = 0

    @property
    def recommended_route_id(self) -> str | None:
        return self.ranking.recommended_route_id


def analyse_trip(
    request: AnalysisRequest,
    *,
    geocoder: GeocodingProvider | None = None,
    router: RoutingProvider | None = None,
    weather: WeatherProvider | None = None,
) -> AnalysisResult:
    """Run the full analysis.

    Providers are injectable so tests can substitute fixtures or mocks; by
    default they come from the configured factory.

    Raises :class:`~apps.routing.providers.errors.ProviderError` subclasses
    and :class:`~apps.routing.services.errors.AnalysisError` subclasses. It
    does not catch provider failures to turn them into empty successes -- an
    infrastructure failure and a trip with no safe route are different
    answers and must stay distinguishable.
    """
    geocoder = geocoder or get_geocoding_provider()
    router = router or get_routing_provider()
    weather = weather or get_weather_provider()

    warnings: list[AnalysisWarning] = []
    departure = request.effective_departure_at

    origin, destination = _geocode_endpoints(request, geocoder, warnings)

    route_set = router.routes(
        origin.coordinate,
        destination.coordinate,
        departure,
        max_alternatives=2,
        vehicle_weight_kg=request.vehicle_weight_kg,
    )
    for notice in route_set.notices:
        warnings.append(AnalysisWarning(code="ROUTING_NOTICE", message=notice))
    if len(route_set.routes) < 3:
        warnings.append(
            AnalysisWarning(
                code="FEWER_ALTERNATIVES",
                message=(
                    f"{len(route_set.routes)} distinct route"
                    f"{'s' if len(route_set.routes) != 1 else ''} available, not 3. "
                    "No additional route was invented."
                ),
            )
        )

    plans = [
        _plan_route(route, request, departure, warnings) for route in route_set.routes
    ]

    samples_by_route = _fetch_weather(plans, departure, weather, warnings)

    analysed: list[AnalysedRoute] = []
    for plan, samples in zip(plans, samples_by_route):
        assessed = assess_route(plan.checkpoints, samples, request.load_weight_lb)
        metrics = summarise_route(plan.route, assessed)
        analysed.append(
            AnalysedRoute(
                route=plan.route,
                checkpoints=assessed,
                metrics=metrics,
                eta_source=plan.eta_source,
                geometry_points=len(plan.route.geometry),
            )
        )
        _warn_about_coverage(metrics, warnings)

    ranking = rank_routes(
        [(item.route, item.metrics) for item in analysed],
        min_coverage_pct=_min_coverage_pct(),
    )

    if ranking.recommended_route_id is None:
        warnings.append(
            AnalysisWarning(
                code="NO_ELIGIBLE_ROUTE", message=ranking.recommendation_reason
            )
        )

    return AnalysisResult(
        request=request,
        origin=origin,
        destination=destination,
        routes=tuple(analysed),
        ranking=ranking,
        warnings=tuple(warnings),
        providers={
            "geocoding": geocoder.name,
            "routing": router.name,
            "weather": weather.name,
        },
        routes_returned_by_provider=route_set.returned_count,
    )


# --- geocoding --------------------------------------------------------------


def _geocode_endpoints(
    request: AnalysisRequest,
    geocoder: GeocodingProvider,
    warnings: list[AnalysisWarning],
) -> tuple[GeocodeResult, GeocodeResult]:
    """Resolve both endpoints, in parallel, then apply the confidence policy."""
    origin, destination = run_bounded(
        [
            lambda: geocoder.geocode(request.origin),
            lambda: geocoder.geocode(request.destination),
        ],
        max_workers=2,
    )
    _check_confidence(origin, "origin", request.origin, warnings)
    _check_confidence(destination, "destination", request.destination, warnings)
    return origin, destination


def _check_confidence(
    result: GeocodeResult,
    field_name: str,
    query: str,
    warnings: list[AnalysisWarning],
) -> None:
    """Refuse to route from a location we are not confident about.

    Two distinct cases, deliberately handled differently (D29):

    * **Low confidence** -- the provider told us it is unsure. Routing from
      the wrong "Springfield" would produce a complete, plausible, entirely
      wrong analysis, so this raises.
    * **No confidence reported** -- we have no evidence either way. Treating
      that as a strong match would be exactly the mistake D27 fixed, so it
      proceeds but emits a warning. Rejecting outright would make the app
      unusable with any provider that does not report confidence.
    """
    floor = _min_geocode_confidence()

    if result.confidence is None:
        warnings.append(
            AnalysisWarning(
                code="GEOCODE_CONFIDENCE_UNKNOWN",
                message=(
                    f"{field_name.title()} resolved to {result.label!r}, but the "
                    "provider reported no match confidence. Verify it is the "
                    "intended location."
                ),
            )
        )
        return

    if result.confidence < floor:
        raise AmbiguousLocationError(
            f"{query!r} did not resolve confidently (best match "
            f"{result.label!r}, confidence {result.confidence:.2f} below the "
            f"required {floor:.2f}). Add a state or postcode and try again.",
            field=field_name,
            query=query,
            confidence=result.confidence,
        )


# --- checkpoints ------------------------------------------------------------


@dataclass(frozen=True, slots=True)
class _RoutePlan:
    route: RouteCandidate
    checkpoints: tuple
    eta_source: str


def _plan_route(
    route: RouteCandidate,
    request: AnalysisRequest,
    departure: datetime,
    warnings: list[AnalysisWarning],
) -> _RoutePlan:
    """Place checkpoints on one route, coarsening the interval if needed."""
    interval = float(request.checkpoint_interval_miles)
    effective = _effective_interval(route, interval)

    if effective != interval:
        warnings.append(
            AnalysisWarning(
                code="CHECKPOINT_INTERVAL_COARSENED",
                message=(
                    f"{route.distance_miles:,.0f} mi at {interval:.0f} mi spacing "
                    f"would need more than {MAX_CHECKPOINTS_PER_ROUTE} checkpoints; "
                    f"using {effective:.0f} mi spacing for this route."
                ),
                route_id=route.id,
            )
        )

    checkpoints = generate_checkpoints(route, effective, departure)

    eta_source = (
        "provider_segments"
        if route.segment_durations is not None
        else "distance_proportional"
    )
    if eta_source == "distance_proportional":
        warnings.append(
            AnalysisWarning(
                code="ETA_ESTIMATED",
                message=(
                    "The provider supplied no per-segment timings for this route, "
                    "so checkpoint ETAs assume a constant average speed."
                ),
                route_id=route.id,
            )
        )

    return _RoutePlan(route=route, checkpoints=checkpoints, eta_source=eta_source)


def _effective_interval(route: RouteCandidate, requested: float) -> float:
    """Coarsen the interval if the requested one would blow the ceiling."""
    needed = route.distance_miles / requested
    if needed <= MAX_CHECKPOINTS_PER_ROUTE:
        return requested
    # Round up to a whole mile so the spacing stays legible in the UI.
    return float(ceil(route.distance_miles / MAX_CHECKPOINTS_PER_ROUTE))


# --- weather ----------------------------------------------------------------


def _fetch_weather(
    plans: Sequence[_RoutePlan],
    departure: datetime,
    weather: WeatherProvider,
    warnings: list[AnalysisWarning],
) -> list[list[WeatherSample | None]]:
    """One batched forecast request covering every checkpoint on every route.

    Checkpoints from all alternatives go into a single call. The adapter
    collapses near-identical coordinates and chunks to its documented limit,
    so overlapping routes cost one lookup rather than three.

    A total weather failure does not abort the analysis: routes, distances and
    ETAs are still useful, every checkpoint becomes UNKNOWN, and the coverage
    gate then prevents any route being recommended on absent data.
    """
    coordinates: list[Coordinate] = []
    for plan in plans:
        coordinates.extend(point.coordinate for point in plan.checkpoints)

    if not coordinates:
        return [[] for _ in plans]

    latest_eta = max(plan.checkpoints[-1].eta for plan in plans)

    try:
        forecasts = weather.hourly(coordinates, departure, latest_eta)
    except ProviderError as exc:
        # Degrade rather than fail: an analysis with no weather is still worth
        # returning, and the coverage gate stops it being recommended.
        logger.warning("weather lookup failed, continuing with UNKNOWN: %s", exc)
        warnings.append(
            AnalysisWarning(
                code="WEATHER_UNAVAILABLE",
                message=(
                    "Weather data could not be retrieved, so no route can be "
                    "assessed for risk. Routes and travel times are still shown."
                ),
            )
        )
        return [[None] * len(plan.checkpoints) for plan in plans]

    if len(forecasts) != len(coordinates):  # pragma: no cover - adapter guards this
        raise WeatherUnavailableError(
            "weather provider returned a mismatched number of forecasts"
        )

    samples: list[list[WeatherSample | None]] = []
    cursor = 0
    for plan in plans:
        route_samples: list[WeatherSample | None] = []
        for point in plan.checkpoints:
            forecast: HourlyForecast = forecasts[cursor]
            cursor += 1
            # Nearest-hour selection, ties round up, out-of-horizon -> None
            # (D19). `None` classifies as UNKNOWN, never as calm.
            route_samples.append(forecast.sample_at(point.eta))
        samples.append(route_samples)
    return samples


def _warn_about_coverage(
    metrics: RouteMetrics, warnings: list[AnalysisWarning]
) -> None:
    if metrics.coverage_pct >= 100.0:
        return
    warnings.append(
        AnalysisWarning(
            code="INCOMPLETE_FORECAST",
            message=(
                f"Forecast covers {metrics.coverage_pct:.1f}% of this route; "
                f"{metrics.unknown_miles:,.1f} mi have no weather data and are "
                "excluded from the risk average."
            ),
            route_id=metrics.route_id,
        )
    )


# --- settings ---------------------------------------------------------------


def _min_coverage_pct() -> float:
    return float(getattr(settings, "MIN_COVERAGE_PCT", MIN_COVERAGE_PCT))


def _min_geocode_confidence() -> float:
    return float(
        getattr(settings, "MIN_GEOCODE_CONFIDENCE", DEFAULT_MIN_GEOCODE_CONFIDENCE)
    )
