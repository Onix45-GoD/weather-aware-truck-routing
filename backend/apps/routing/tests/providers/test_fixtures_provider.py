"""Tests for the offline fixture providers.

Their contract is determinism: the application must be demonstrable and
testable with no key and no network, and the same inputs must always give
byte-identical output so nothing downstream can flake.
"""

from __future__ import annotations

from datetime import UTC, datetime, timedelta

import pytest

from apps.routing.domain.aggregation import assess_route, summarise_route
from apps.routing.domain.checkpoints import generate_checkpoints
from apps.routing.domain.models import Coordinate
from apps.routing.providers.base import (
    GeocodingProvider,
    RoutingProvider,
    WeatherProvider,
)
from apps.routing.providers.errors import GeocodingNoResultsError
from apps.routing.providers.fixtures import (
    FixtureGeocodingProvider,
    FixtureRoutingProvider,
    FixtureWeatherProvider,
    synthetic_sample,
)
from apps.routing.tests.providers.conftest import CHICAGO, DENVER, DEPARTURE

WINDOW_END = DEPARTURE + timedelta(hours=24)


class TestProtocolConformance:
    def test_fixture_providers_satisfy_the_protocols(self) -> None:
        """They must be drop-in replacements for the real adapters."""
        assert isinstance(FixtureGeocodingProvider(), GeocodingProvider)
        assert isinstance(FixtureRoutingProvider(), RoutingProvider)
        assert isinstance(FixtureWeatherProvider(), WeatherProvider)

    def test_real_providers_satisfy_the_same_protocols(self) -> None:
        from apps.routing.providers.openmeteo import OpenMeteoWeatherProvider
        from apps.routing.providers.tomtom import (
            TomTomGeocodingProvider,
            TomTomRoutingProvider,
        )

        assert isinstance(OpenMeteoWeatherProvider(), WeatherProvider)
        assert isinstance(TomTomGeocodingProvider("k"), GeocodingProvider)
        assert isinstance(TomTomRoutingProvider("k"), RoutingProvider)


class TestFixtureGeocoding:
    @pytest.mark.parametrize(
        "query", ["Denver", "denver", "  DENVER  ", "Denver, CO", "Chicago"]
    )
    def test_resolves_known_places(self, query: str) -> None:
        assert FixtureGeocodingProvider().geocode(query).label

    def test_is_deterministic(self) -> None:
        provider = FixtureGeocodingProvider()
        results = {provider.geocode("Denver") for _ in range(10)}
        assert len(results) == 1

    def test_unknown_places_raise_rather_than_being_invented(self) -> None:
        """A fixture that quietly invents places would hide real bugs."""
        with pytest.raises(GeocodingNoResultsError) as exc:
            FixtureGeocodingProvider().geocode("Atlantis")
        assert "Known fixtures" in str(exc.value)

    def test_returns_a_valid_coordinate(self) -> None:
        result = FixtureGeocodingProvider().geocode("Denver")
        assert isinstance(result.coordinate, Coordinate)
        assert result.provider == "fixtures"


class TestFixtureRouting:
    def test_produces_three_distinct_alternatives(self) -> None:
        result = FixtureRoutingProvider().routes(DENVER, CHICAGO, DEPARTURE)

        assert len(result.routes) == 3
        assert len({r.id for r in result.routes}) == 3
        assert len({r.distance_miles for r in result.routes}) == 3
        assert len({r.duration_seconds for r in result.routes}) == 3

    def test_alternatives_have_genuinely_different_geometry(self) -> None:
        routes = FixtureRoutingProvider().routes(DENVER, CHICAGO, DEPARTURE).routes
        shapes = {tuple((p.latitude, p.longitude) for p in r.geometry) for r in routes}
        assert len(shapes) == 3

    def test_says_plainly_that_the_routes_are_synthetic(self) -> None:
        result = FixtureRoutingProvider().routes(DENVER, CHICAGO, DEPARTURE)
        assert any("ynthetic" in notice for notice in result.notices)

    def test_is_deterministic(self) -> None:
        provider = FixtureRoutingProvider()
        first = provider.routes(DENVER, CHICAGO, DEPARTURE)
        for _ in range(5):
            again = provider.routes(DENVER, CHICAGO, DEPARTURE)
            assert again.routes == first.routes

    def test_can_simulate_fewer_available_routes(self) -> None:
        result = FixtureRoutingProvider(available=2).routes(
            DENVER, CHICAGO, DEPARTURE
        )
        assert len(result.routes) == 2
        assert any("2 of the 3" in notice for notice in result.notices)

    def test_honours_a_lower_alternatives_request(self) -> None:
        result = FixtureRoutingProvider().routes(
            DENVER, CHICAGO, DEPARTURE, max_alternatives=0
        )
        assert len(result.routes) == 1

    def test_routes_start_and_end_at_the_requested_points(self) -> None:
        direct = FixtureRoutingProvider().routes(DENVER, CHICAGO, DEPARTURE).routes[0]
        assert direct.geometry[0].latitude == pytest.approx(DENVER.latitude)
        assert direct.geometry[-1].latitude == pytest.approx(CHICAGO.latitude)

    def test_naive_departure_time_is_rejected(self) -> None:
        with pytest.raises(ValueError, match="timezone-aware"):
            FixtureRoutingProvider().routes(
                DENVER, CHICAGO, datetime(2026, 11, 2, 12, 0)
            )

    @pytest.mark.parametrize("kwargs", [{"vertices": 1}, {"available": 0}, {"available": 9}])
    def test_rejects_nonsensical_configuration(self, kwargs) -> None:
        with pytest.raises(ValueError):
            FixtureRoutingProvider(**kwargs)


class TestFixtureWeather:
    def test_returns_one_series_per_coordinate(self) -> None:
        results = FixtureWeatherProvider().hourly(
            [DENVER, CHICAGO], DEPARTURE, WINDOW_END
        )
        assert len(results) == 2
        assert results[0].coordinate == DENVER

    def test_covers_the_requested_window(self) -> None:
        forecast = FixtureWeatherProvider().hourly([DENVER], DEPARTURE, WINDOW_END)[0]
        assert forecast.times[0] <= DEPARTURE
        assert forecast.times[-1] >= WINDOW_END - timedelta(hours=1)

    def test_timestamps_are_utc_and_hourly(self) -> None:
        forecast = FixtureWeatherProvider().hourly([DENVER], DEPARTURE, WINDOW_END)[0]
        assert all(t.tzinfo is UTC for t in forecast.times)
        gaps = {b - a for a, b in zip(forecast.times, forecast.times[1:])}
        assert gaps == {timedelta(hours=1)}

    def test_is_deterministic_across_calls(self) -> None:
        provider = FixtureWeatherProvider()
        first = provider.hourly([DENVER], DEPARTURE, WINDOW_END)
        for _ in range(5):
            assert provider.hourly([DENVER], DEPARTURE, WINDOW_END) == first

    def test_is_deterministic_across_instances(self) -> None:
        a = FixtureWeatherProvider().hourly([DENVER], DEPARTURE, WINDOW_END)
        b = FixtureWeatherProvider().hourly([DENVER], DEPARTURE, WINDOW_END)
        assert a == b

    def test_different_places_get_different_weather(self) -> None:
        denver, chicago = FixtureWeatherProvider().hourly(
            [DENVER, CHICAGO], DEPARTURE, WINDOW_END
        )
        assert denver.samples != chicago.samples

    def test_values_are_physically_plausible(self) -> None:
        forecast = FixtureWeatherProvider().hourly([DENVER], DEPARTURE, WINDOW_END)[0]
        for sample in forecast.samples:
            assert sample.wind_mph is not None and 0 <= sample.wind_mph <= 80
            assert sample.rain_in_hr is not None and 0 <= sample.rain_in_hr <= 2
            assert sample.snow_in_hr is not None and 0 <= sample.snow_in_hr <= 5

    def test_gusts_exceed_sustained_wind(self) -> None:
        forecast = FixtureWeatherProvider().hourly([DENVER], DEPARTURE, WINDOW_END)[0]
        for sample in forecast.samples:
            assert sample.wind_gust_mph is not None
            assert sample.wind_gust_mph >= sample.wind_mph

    def test_can_inject_missing_hours(self) -> None:
        forecast = FixtureWeatherProvider(missing_every=3).hourly(
            [DENVER], DEPARTURE, WINDOW_END
        )[0]
        assert forecast.samples[0].wind_mph is None
        assert forecast.samples[1].wind_mph is not None
        assert forecast.samples[3].wind_mph is None

    def test_rejects_naive_datetimes(self) -> None:
        with pytest.raises(ValueError, match="timezone-aware"):
            FixtureWeatherProvider().hourly([DENVER], datetime(2026, 11, 2), WINDOW_END)

    def test_rejects_a_reversed_window(self) -> None:
        with pytest.raises(ValueError, match="must not precede"):
            FixtureWeatherProvider().hourly([DENVER], WINDOW_END, DEPARTURE)

    def test_synthetic_sample_is_a_pure_function(self) -> None:
        moment = DEPARTURE
        assert synthetic_sample(DENVER, moment) == synthetic_sample(DENVER, moment)


class TestOfflineEndToEnd:
    def test_a_full_analysis_runs_with_no_key_and_no_network(self) -> None:
        """The whole pipeline, offline: geocode -> route -> weather -> score."""
        geocoder = FixtureGeocodingProvider()
        origin = geocoder.geocode("Denver")
        destination = geocoder.geocode("Chicago")

        routes = FixtureRoutingProvider().routes(
            origin.coordinate, destination.coordinate, DEPARTURE
        )
        weather = FixtureWeatherProvider()

        for route in routes.routes:
            checkpoints = generate_checkpoints(route, 50.0, DEPARTURE)
            forecasts = weather.hourly(
                [c.coordinate for c in checkpoints],
                DEPARTURE,
                DEPARTURE + timedelta(hours=48),
            )
            samples = [
                forecast.sample_at(checkpoint.eta)
                for checkpoint, forecast in zip(checkpoints, forecasts)
            ]
            metrics = summarise_route(
                route, assess_route(checkpoints, samples, 42_000.0)
            )

            assert metrics.coverage_pct == pytest.approx(100.0)
            assert sum(metrics.miles_by_level.values()) == pytest.approx(
                route.distance_miles
            )

    def test_the_offline_pipeline_produces_varied_risk(self) -> None:
        """A demo of uniform calm would not exercise the risk engine."""
        route = FixtureRoutingProvider().routes(DENVER, CHICAGO, DEPARTURE).routes[0]
        checkpoints = generate_checkpoints(route, 25.0, DEPARTURE)
        forecasts = FixtureWeatherProvider().hourly(
            [c.coordinate for c in checkpoints],
            DEPARTURE,
            DEPARTURE + timedelta(hours=48),
        )
        samples = [
            forecast.sample_at(checkpoint.eta)
            for checkpoint, forecast in zip(checkpoints, forecasts)
        ]
        assessed = assess_route(checkpoints, samples, 42_000.0)
        levels = {point.risk.level for point in assessed}
        assert len(levels) >= 2
