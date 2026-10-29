"""Shared synthetic builders for the domain test suite.

Everything here is fabricated in-process. No test in this project touches the
network, reads an API key, or depends on the wall clock.
"""

from __future__ import annotations

from collections.abc import Sequence
from datetime import UTC, datetime

from apps.routing.domain.models import (
    Coordinate,
    RouteCandidate,
    WeatherSample,
)

#: Fixed reference instant. The domain never reads the clock, so every test
#: that needs a departure time uses this.
DEPARTURE = datetime(2026, 11, 2, 12, 0, 0, tzinfo=UTC)

CALM = WeatherSample(wind_mph=5.0, rain_in_hr=0.0, snow_in_hr=0.0)
NO_DATA: WeatherSample | None = None


def meridian_geometry(
    vertices: int = 11,
    start_lat: float = 40.0,
    span_lat: float = 1.0,
    longitude: float = -100.0,
) -> tuple[Coordinate, ...]:
    """A due-north line with evenly spaced vertices.

    Even latitude spacing along a meridian gives even *distance* spacing, so a
    checkpoint placed at 25% of the route distance must land at 25% of the
    latitude span. That makes interpolation assertions exact.
    """
    if vertices < 2:
        raise ValueError("need at least two vertices")
    step = span_lat / (vertices - 1)
    return tuple(
        Coordinate(latitude=start_lat + step * index, longitude=longitude)
        for index in range(vertices)
    )


def uneven_geometry() -> tuple[Coordinate, ...]:
    """A due-north line whose vertices are deliberately clustered.

    Dense near the start, sparse across the middle -- the shape real provider
    polylines take around interchanges. Used to prove checkpoints are placed by
    cumulative distance rather than by index into the geometry array.
    """
    offsets = (0.0, 0.01, 0.02, 0.03, 0.04, 0.05, 0.5, 0.95, 1.0)
    return tuple(
        Coordinate(latitude=40.0 + offset, longitude=-100.0) for offset in offsets
    )


def make_route(
    route_id: str = "r1",
    label: str = "Test route",
    distance_miles: float = 100.0,
    duration_seconds: float = 7200.0,
    geometry: Sequence[Coordinate] | None = None,
    provider_index: int = 0,
    segment_durations: Sequence[float] | None = None,
) -> RouteCandidate:
    """Build a synthetic route candidate with sane defaults."""
    points = tuple(geometry) if geometry is not None else meridian_geometry()
    return RouteCandidate(
        id=route_id,
        label=label,
        geometry=points,
        distance_miles=distance_miles,
        duration_seconds=duration_seconds,
        provider_index=provider_index,
        segment_durations=(
            tuple(segment_durations) if segment_durations is not None else None
        ),
    )


def wind(speed_mph: float) -> WeatherSample:
    """A sample where wind is the only non-trivial condition."""
    return WeatherSample(wind_mph=speed_mph, rain_in_hr=0.0, snow_in_hr=0.0)


def rain(rate_in_hr: float) -> WeatherSample:
    """A sample where rain is the only non-trivial condition."""
    return WeatherSample(wind_mph=0.0, rain_in_hr=rate_in_hr, snow_in_hr=0.0)


def snow(rate_in_hr: float) -> WeatherSample:
    """A sample where snow is the only non-trivial condition."""
    return WeatherSample(wind_mph=0.0, rain_in_hr=0.0, snow_in_hr=rate_in_hr)
