"""Provider protocols and the typed results they return.

These are the seams the orchestration service in Milestone 3 will depend on.
Nothing here performs I/O; the concrete adapters implement these protocols.
"""

from __future__ import annotations

from bisect import bisect_left
from collections.abc import Sequence
from dataclasses import dataclass, field
from datetime import datetime, timedelta
from typing import Protocol, runtime_checkable

from apps.routing.domain.models import Coordinate, RouteCandidate, WeatherSample

__all__ = [
    "FORECAST_MATCH_TOLERANCE",
    "GeocodeResult",
    "GeocodingProvider",
    "HourlyForecast",
    "RouteSet",
    "RoutingProvider",
    "WeatherProvider",
]

#: How far a requested instant may sit from the nearest available hourly
#: forecast before we treat it as unavailable. Hourly data is never more than
#: 30 minutes from any instant *inside* the forecast horizon, so this value
#: accepts everything in range and rejects everything beyond the horizon.
FORECAST_MATCH_TOLERANCE = timedelta(minutes=30)


@dataclass(frozen=True, slots=True)
class GeocodeResult:
    """A resolved place: where it is, and what to call it."""

    coordinate: Coordinate
    label: str
    provider: str
    confidence: float | None = None


@dataclass(frozen=True, slots=True)
class RouteSet:
    """Route alternatives as actually returned by a provider.

    The counts are kept deliberately honest. ``returned_count`` is what the
    provider sent before de-duplication, and ``len(routes)`` is what survived.
    Neither is ever padded: if the provider could only find two distinct
    routes, two is what the caller gets, with a notice saying so. We never
    invent a third.

    A route whose ``segment_durations`` is not ``None`` carries real
    provider-supplied timing; otherwise the domain falls back to
    distance-proportional ETAs.
    """

    routes: tuple[RouteCandidate, ...]
    provider: str
    requested_alternatives: int
    returned_count: int
    duplicates_removed: int = 0
    notices: tuple[str, ...] = field(default_factory=tuple)

    @property
    def has_provider_timings(self) -> bool:
        """True when every route carries provider segment timings."""
        return bool(self.routes) and all(
            route.segment_durations is not None for route in self.routes
        )


@dataclass(frozen=True, slots=True)
class HourlyForecast:
    """An hourly forecast time series for one point.

    ``coordinate`` is what we asked for; ``resolved_coordinate`` is the model
    grid cell the provider actually answered with. They differ by up to a few
    kilometres, which is why forecasts must be associated with checkpoints by
    **request order**, never by matching coordinates back.

    ``times`` is ascending, timezone-aware UTC, and positionally aligned with
    ``samples``.
    """

    coordinate: Coordinate
    resolved_coordinate: Coordinate
    times: tuple[datetime, ...]
    samples: tuple[WeatherSample, ...]
    provider: str
    elevation_m: float | None = None

    def __post_init__(self) -> None:
        if len(self.times) != len(self.samples):
            raise ValueError(
                "times and samples must be the same length: "
                f"{len(self.times)} vs {len(self.samples)}"
            )
        if any(t.tzinfo is None for t in self.times):
            raise ValueError("forecast times must be timezone-aware")

    def sample_at(
        self, when: datetime, *, tolerance: timedelta = FORECAST_MATCH_TOLERANCE
    ) -> WeatherSample | None:
        """The forecast nearest to ``when``, or ``None`` if out of range.

        **Selection policy.** The nearest available hour wins. An exact tie --
        an instant falling precisely on the half hour -- resolves to the
        **later** hour, matching the round-half-up convention recorded in
        ``docs/decisions.md``. An instant further than ``tolerance`` from any
        available hour is outside the forecast horizon and returns ``None``,
        which classifies as ``UNKNOWN`` downstream rather than as good weather.

        This is hourly data. Matching an ETA to the nearest hour does not make
        the forecast minute-accurate, and nothing downstream should present it
        as though it were.
        """
        if when.tzinfo is None:
            raise ValueError("`when` must be timezone-aware")
        if not self.times:
            return None

        index = bisect_left(self.times, when)

        if index == 0:
            best = 0
        elif index >= len(self.times):
            best = len(self.times) - 1
        else:
            before_gap = when - self.times[index - 1]
            after_gap = self.times[index] - when
            # `<=` sends an exact half-hour tie to the later hour.
            best = index if after_gap <= before_gap else index - 1

        if abs(self.times[best] - when) > tolerance:
            return None
        return self.samples[best]


@runtime_checkable
class GeocodingProvider(Protocol):
    """Resolves a free-text place into a coordinate."""

    name: str

    def geocode(self, query: str) -> GeocodeResult:
        """Resolve ``query``.

        Raises :class:`~apps.routing.providers.errors.GeocodingNoResultsError`
        when nothing matches -- never returns a guessed coordinate.
        """
        ...


@runtime_checkable
class RoutingProvider(Protocol):
    """Produces truck-route alternatives between two points."""

    name: str

    def routes(
        self,
        origin: Coordinate,
        destination: Coordinate,
        departure_time: datetime,
        *,
        max_alternatives: int = 2,
    ) -> RouteSet:
        """Route from ``origin`` to ``destination``.

        ``max_alternatives`` is how many routes to request *in addition to*
        the primary one, so the default of 2 asks for up to three candidates.
        """
        ...


@runtime_checkable
class WeatherProvider(Protocol):
    """Fetches hourly forecasts for a batch of points."""

    name: str

    def hourly(
        self,
        coordinates: Sequence[Coordinate],
        start: datetime,
        end: datetime,
    ) -> tuple[HourlyForecast, ...]:
        """Forecasts covering ``start``..``end`` for every coordinate.

        The result is positionally aligned with ``coordinates`` and has the
        same length, so callers associate forecasts with checkpoints by index.
        """
        ...
