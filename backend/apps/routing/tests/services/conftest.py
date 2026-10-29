"""Test doubles for orchestration tests.

These implement the real provider protocols but answer from a script, so a
test can set up an exact weather or routing situation -- all routes blocked,
a forecast gap at one checkpoint, a provider that times out -- without
depending on what the real world happens to be doing.

Nothing here touches the network.
"""

from __future__ import annotations

from collections.abc import Callable, Sequence
from datetime import UTC, datetime, timedelta

import pytest

from apps.routing.domain.models import Coordinate, RouteCandidate, WeatherSample
from apps.routing.providers.base import GeocodeResult, HourlyForecast, RouteSet
from apps.routing.providers.errors import GeocodingNoResultsError
from apps.routing.services.analysis import AnalysisRequest

DEPARTURE = datetime(2026, 11, 2, 12, 0, tzinfo=UTC)
DENVER = Coordinate(latitude=39.7392, longitude=-104.9903)
CHICAGO = Coordinate(latitude=41.8781, longitude=-87.6298)

CALM = WeatherSample(wind_mph=5.0, rain_in_hr=0.0, snow_in_hr=0.0)


def make_request(**overrides) -> AnalysisRequest:
    """An `AnalysisRequest` with sane defaults for the happy path."""
    values = {
        "origin": "Denver, CO",
        "destination": "Chicago, IL",
        "departure_at": DEPARTURE,
        "load_weight_lb": 42_000.0,
        "checkpoint_interval_miles": 50,
        "forecast_offset_hours": 0,
    }
    values.update(overrides)
    return AnalysisRequest(**values)


def straight_route(
    route_id: str,
    *,
    distance_miles: float = 100.0,
    duration_seconds: float = 7200.0,
    provider_index: int = 0,
    label: str | None = None,
    vertices: int = 21,
    lat_offset: float = 0.0,
    segment_durations: tuple[float, ...] | None = None,
) -> RouteCandidate:
    """A synthetic north-running route with evenly spaced vertices."""
    step = 1.0 / (vertices - 1)
    geometry = tuple(
        Coordinate(latitude=39.0 + lat_offset + step * index, longitude=-100.0)
        for index in range(vertices)
    )
    return RouteCandidate(
        id=route_id,
        label=label or f"Route {route_id}",
        geometry=geometry,
        distance_miles=distance_miles,
        duration_seconds=duration_seconds,
        provider_index=provider_index,
        segment_durations=segment_durations,
    )


class StubGeocoder:
    """Returns prepared results, or raises, per query."""

    name = "stub"

    def __init__(
        self,
        *,
        confidence: float | None = 1.0,
        results: dict[str, GeocodeResult] | None = None,
        error: Exception | None = None,
    ) -> None:
        self.confidence = confidence
        self.results = results or {}
        self.error = error
        self.calls: list[str] = []

    def geocode(self, query: str) -> GeocodeResult:
        self.calls.append(query)
        if self.error is not None:
            raise self.error
        if query in self.results:
            return self.results[query]
        coordinate = DENVER if "denver" in query.lower() else CHICAGO
        return GeocodeResult(
            coordinate=coordinate,
            label=f"{query} (resolved)",
            provider=self.name,
            confidence=self.confidence,
        )


class StubRouter:
    """Returns a fixed set of routes, or raises."""

    name = "stub"

    def __init__(
        self,
        routes: Sequence[RouteCandidate] | None = None,
        *,
        error: Exception | None = None,
        notices: tuple[str, ...] = (),
        returned_count: int | None = None,
    ) -> None:
        self.route_list = tuple(routes) if routes is not None else (
            straight_route("r0", provider_index=0),
        )
        self.error = error
        self.notices = notices
        self.returned_count = (
            returned_count if returned_count is not None else len(self.route_list)
        )
        self.calls: list[datetime] = []

    def routes(
        self,
        origin: Coordinate,
        destination: Coordinate,
        departure_time: datetime,
        *,
        max_alternatives: int = 2,
        vehicle_weight_kg: float | None = None,
    ) -> RouteSet:
        self.last_vehicle_weight_kg = vehicle_weight_kg
        self.calls.append(departure_time)
        if self.error is not None:
            raise self.error
        return RouteSet(
            routes=self.route_list,
            provider=self.name,
            requested_alternatives=max_alternatives,
            returned_count=self.returned_count,
            notices=self.notices,
        )


class ScriptedWeather:
    """Returns a chosen sample for every hour, or a per-checkpoint script.

    ``sample_for`` receives the requested coordinate and the hour and returns
    a :class:`WeatherSample` or ``None``. Returning ``None`` produces a gap in
    the series, which is how forecast-horizon and partial-coverage cases are
    reproduced without a provider outage.
    """

    name = "scripted"

    def __init__(
        self,
        sample_for: Callable[[Coordinate, datetime], WeatherSample | None] | None = None,
        *,
        error: Exception | None = None,
    ) -> None:
        self.sample_for = sample_for or (lambda _coordinate, _when: CALM)
        self.error = error
        self.requests: list[tuple[int, datetime, datetime]] = []

    def hourly(
        self,
        coordinates: Sequence[Coordinate],
        start: datetime,
        end: datetime,
    ) -> tuple[HourlyForecast, ...]:
        self.requests.append((len(coordinates), start, end))
        if self.error is not None:
            raise self.error

        first = start.astimezone(UTC).replace(minute=0, second=0, microsecond=0)
        hours = int((end.astimezone(UTC) - first).total_seconds() // 3600) + 2
        times = tuple(first + timedelta(hours=offset) for offset in range(hours))

        forecasts = []
        for coordinate in coordinates:
            kept_times = []
            kept_samples = []
            for moment in times:
                sample = self.sample_for(coordinate, moment)
                if sample is None:
                    # Omit the hour entirely: a genuine hole in the series.
                    continue
                kept_times.append(moment)
                kept_samples.append(sample)
            forecasts.append(
                HourlyForecast(
                    coordinate=coordinate,
                    resolved_coordinate=coordinate,
                    times=tuple(kept_times),
                    samples=tuple(kept_samples),
                    provider=self.name,
                )
            )
        return tuple(forecasts)


def wind_at(speed: float) -> WeatherSample:
    return WeatherSample(wind_mph=speed, rain_in_hr=0.0, snow_in_hr=0.0)


def snow_at(rate: float) -> WeatherSample:
    return WeatherSample(wind_mph=0.0, rain_in_hr=0.0, snow_in_hr=rate)


@pytest.fixture
def geocoder() -> StubGeocoder:
    return StubGeocoder()


@pytest.fixture
def router() -> StubRouter:
    return StubRouter(
        [
            straight_route("r0", distance_miles=100.0, duration_seconds=7200.0,
                           provider_index=0, lat_offset=0.0),
            straight_route("r1", distance_miles=110.0, duration_seconds=7800.0,
                           provider_index=1, lat_offset=2.0),
            straight_route("r2", distance_miles=120.0, duration_seconds=8400.0,
                           provider_index=2, lat_offset=4.0),
        ]
    )


@pytest.fixture
def weather() -> ScriptedWeather:
    return ScriptedWeather()


@pytest.fixture
def no_results_geocoder() -> StubGeocoder:
    return StubGeocoder(
        error=GeocodingNoResultsError("No location found.", provider="stub")
    )
