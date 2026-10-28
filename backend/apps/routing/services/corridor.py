"""Corridor forecast: the selected route's checkpoints, every hour for 48 hours.

The route analysis answers one question per checkpoint -- what will the
weather be *when the truck gets there*. The corridor view answers a
different one: what does the whole route look like at hour +N after the
analysis reference time, for every N from 0 to 48. That is a display
feature (D28): it never changes the departure, the ETAs or the
recommendation, and this module is correspondingly read-only.

What it reuses, deliberately
----------------------------
* **The same provider and adapter** as the analysis. Open-Meteo's hourly
  series, with the adapter's unit normalisation, coordinate de-duplication,
  chunking, timeouts, retries and response cache. One ``hourly()`` call per
  corridor request; overlapping checkpoints cost one lookup.
* **The same domain functions.** Every frame is classified by
  :func:`~apps.routing.domain.aggregation.assess_route` (which applies the
  cargo-weight override) and summarised by
  :func:`~apps.routing.domain.aggregation.summarise_route`. No threshold,
  severity comparison or coverage rule is restated here.
* **The same forecast-selection policy.** Each frame's samples come from
  ``HourlyForecast.sample_at`` -- nearest hour, out-of-horizon is ``None``
  (D19) -- so an hour the provider does not cover classifies as UNKNOWN and
  the frame says it is unavailable. Nothing is interpolated or invented.

Why a reference time rather than ETAs
-------------------------------------
A frame is one instant across the whole route. Frame ``h`` is
``reference_at + h hours`` at *every* checkpoint, which is exactly what a
"scrub the forecast" slider means. It is **not** the ETA-based view: at hour
+12 the truck is only at one place, but the map shows what every mile of the
corridor would be like at that moment. The UI labels the two views so they
are not mistaken for each other.
"""

from __future__ import annotations

import logging
from collections.abc import Sequence
from dataclasses import dataclass, field
from datetime import datetime, timedelta
from typing import Final

from apps.routing.domain.aggregation import assess_route, summarise_route
from apps.routing.domain.models import (
    AssessedCheckpoint,
    Checkpoint,
    Coordinate,
    RouteCandidate,
    RouteMetrics,
)
from apps.routing.providers.base import HourlyForecast, WeatherProvider
from apps.routing.providers.factory import get_weather_provider

from .analysis import MAX_CHECKPOINTS_PER_ROUTE, AnalysisWarning

__all__ = [
    "CORRIDOR_HORIZON_HOURS",
    "CORRIDOR_STEP_HOURS",
    "CorridorCheckpoint",
    "CorridorForecast",
    "CorridorFrame",
    "forecast_corridor",
]

logger = logging.getLogger(__name__)

#: The assessment's slider range. Frames run from +0 to +48 inclusive.
CORRIDOR_HORIZON_HOURS: Final = 48

#: Open-Meteo's series is hourly, so the step is one hour. A finer step would
#: have to invent measurements; a coarser one would discard real ones.
CORRIDOR_STEP_HOURS: Final = 1


@dataclass(frozen=True, slots=True)
class CorridorCheckpoint:
    """A checkpoint as the client sent it back: where it is on the route."""

    index: int
    coordinate: Coordinate
    distance_from_origin_miles: float


@dataclass(frozen=True, slots=True)
class CorridorFrame:
    """One hour across every checkpoint, classified."""

    hour: int
    at: datetime
    assessed: tuple[AssessedCheckpoint, ...]
    metrics: RouteMetrics
    #: False when no checkpoint had a forecast for this instant. The frame
    #: is still returned -- as all-UNKNOWN -- so the slider can show the gap.
    available: bool
    #: Why ``available`` is False, when it is: ``outside_provider_horizon``
    #: (the instant precedes or follows everything the provider sent) or
    #: ``no_measurements`` (the hour exists but carried no values).
    unavailable_reason: str | None


@dataclass(frozen=True, slots=True)
class CorridorForecast:
    reference_at: datetime
    load_weight_lb: float
    checkpoints: tuple[CorridorCheckpoint, ...]
    #: Forward-attributed miles per checkpoint, from the domain.
    segment_miles: tuple[float, ...]
    frames: tuple[CorridorFrame, ...]
    provider: str
    #: First and last instants the provider actually covered, or ``None``
    #: when it covered nothing. The UI must not promise forecast outside it.
    forecast_window_start: datetime | None
    forecast_window_end: datetime | None
    warnings: tuple[AnalysisWarning, ...] = field(default_factory=tuple)
    step_hours: int = CORRIDOR_STEP_HOURS
    horizon_hours: int = CORRIDOR_HORIZON_HOURS

    @property
    def available_hours(self) -> int:
        return sum(1 for frame in self.frames if frame.available)


def _validate(
    reference_at: datetime,
    load_weight_lb: float,
    checkpoints: Sequence[CorridorCheckpoint],
) -> None:
    if reference_at.tzinfo is None:
        raise ValueError("reference_at must be timezone-aware")
    if load_weight_lb <= 0:
        raise ValueError("load_weight_lb must be positive")
    if len(checkpoints) < 2:
        raise ValueError("a corridor needs at least an origin and a destination")
    if len(checkpoints) > MAX_CHECKPOINTS_PER_ROUTE:
        raise ValueError(f"at most {MAX_CHECKPOINTS_PER_ROUTE} checkpoints")
    distances = [point.distance_from_origin_miles for point in checkpoints]
    if distances[0] < 0.0 or any(
        later < earlier for earlier, later in zip(distances, distances[1:])
    ):
        raise ValueError("checkpoint distances must be non-negative and non-decreasing")
    if distances[-1] <= 0.0:
        raise ValueError("the route must have positive length")
    indexes = [point.index for point in checkpoints]
    if any(later <= earlier for earlier, later in zip(indexes, indexes[1:])):
        raise ValueError("checkpoint indexes must be unique and ascending")


def _route_shell(checkpoints: Sequence[CorridorCheckpoint]) -> RouteCandidate:
    """The route as :func:`summarise_route` needs to see it.

    The client does not resend geometry -- it would be the largest part of
    the request for no benefit, since the corridor is sampled at checkpoints
    only. The checkpoint polyline is geometry enough for the summary, and
    the distance is the last checkpoint's. ``duration_seconds`` is a
    placeholder the summary carries but this module never reports; it is
    not a claim about travel time.
    """
    return RouteCandidate(
        id="corridor",
        label="corridor",
        geometry=tuple(point.coordinate for point in checkpoints),
        distance_miles=checkpoints[-1].distance_from_origin_miles,
        duration_seconds=1.0,
    )


def _domain_checkpoints(
    checkpoints: Sequence[CorridorCheckpoint], at: datetime
) -> tuple[Checkpoint, ...]:
    """Checkpoint objects for one frame. The ETA *is* the frame instant."""
    last = len(checkpoints) - 1
    return tuple(
        Checkpoint(
            index=point.index,
            coordinate=point.coordinate,
            distance_from_origin_miles=point.distance_from_origin_miles,
            eta=at,
            is_origin=position == 0,
            is_destination=position == last,
        )
        for position, point in enumerate(checkpoints)
    )


def _series_window(
    forecasts: Sequence[HourlyForecast],
) -> tuple[datetime | None, datetime | None]:
    starts = [series.times[0] for series in forecasts if series.times]
    ends = [series.times[-1] for series in forecasts if series.times]
    if not starts:
        return None, None
    return min(starts), max(ends)


def forecast_corridor(
    reference_at: datetime,
    load_weight_lb: float,
    checkpoints: Sequence[CorridorCheckpoint],
    *,
    weather: WeatherProvider | None = None,
) -> CorridorForecast:
    """Classify every checkpoint at every hour from +0 to +48.

    Raises ``ValueError`` for an inconsistent request (the API validates
    first, so reaching one is a bug) and lets provider failures propagate:
    a corridor with no weather has nothing to show, unlike an analysis,
    where routes and ETAs are still worth returning.
    """
    _validate(reference_at, load_weight_lb, checkpoints)
    weather = weather or get_weather_provider()

    horizon_end = reference_at + timedelta(hours=CORRIDOR_HORIZON_HOURS)
    coordinates = [point.coordinate for point in checkpoints]

    # One call. The adapter collapses near-identical coordinates, chunks to
    # its limit, applies timeouts and retries, and caches the response.
    forecasts = weather.hourly(coordinates, reference_at, horizon_end)
    if len(forecasts) != len(coordinates):  # pragma: no cover - adapter guards this
        raise ValueError("weather provider returned a mismatched number of series")

    window_start, window_end = _series_window(forecasts)
    route = _route_shell(checkpoints)
    warnings: list[AnalysisWarning] = []

    frames: list[CorridorFrame] = []
    for hour in range(0, CORRIDOR_HORIZON_HOURS + 1, CORRIDOR_STEP_HOURS):
        at = reference_at + timedelta(hours=hour)
        # Nearest hour, ties round up, outside the series -> None (D19).
        samples = [series.sample_at(at) for series in forecasts]
        domain_points = _domain_checkpoints(checkpoints, at)
        assessed = assess_route(domain_points, samples, load_weight_lb)
        metrics = summarise_route(route, assessed)

        available = any(sample is not None for sample in samples)
        reason: str | None = None
        if not available:
            inside = (
                window_start is not None
                and window_end is not None
                and window_start <= at <= window_end
            )
            reason = "no_measurements" if inside else "outside_provider_horizon"

        frames.append(
            CorridorFrame(
                hour=hour,
                at=at,
                assessed=assessed,
                metrics=metrics,
                available=available,
                unavailable_reason=reason,
            )
        )

    unavailable = [frame.hour for frame in frames if not frame.available]
    if unavailable:
        if len(unavailable) == len(frames):
            warnings.append(
                AnalysisWarning(
                    code="FORECAST_HORIZON",
                    message=(
                        "The weather provider has no forecast for any hour in "
                        "this window. Every hour is shown as unknown."
                    ),
                )
            )
        else:
            warnings.append(
                AnalysisWarning(
                    code="FORECAST_HORIZON",
                    message=(
                        f"{len(unavailable)} of {len(frames)} hours have no forecast "
                        "from the provider and are shown as unknown."
                    ),
                )
            )

    partial = [
        frame.hour
        for frame in frames
        if frame.available and frame.metrics.coverage_pct < 100.0
    ]
    if partial:
        warnings.append(
            AnalysisWarning(
                code="INCOMPLETE_FORECAST",
                message=(
                    f"{len(partial)} hour{'s' if len(partial) != 1 else ''} have a "
                    "forecast for only part of the route; the missing miles are "
                    "shown as unknown, never as clear."
                ),
            )
        )

    # Segment miles are identical for every frame -- they depend only on
    # distances -- so they are reported once, from the first frame.
    segment_miles = tuple(point.segment_miles for point in frames[0].assessed)

    return CorridorForecast(
        reference_at=reference_at,
        load_weight_lb=load_weight_lb,
        checkpoints=tuple(checkpoints),
        segment_miles=segment_miles,
        frames=tuple(frames),
        provider=weather.name,
        forecast_window_start=window_start,
        forecast_window_end=window_end,
        warnings=tuple(warnings),
    )
