"""Opt-in live smoke tests. Disabled by default.

These are the only tests in the project that touch the network. They are
excluded by the `-m "not live"` default in `pyproject.toml`, so an ordinary
`pytest` run can never fire them accidentally -- not on a laptop, not in CI,
not on a machine with no internet.

Run them deliberately:

    pytest -m live                      # Open-Meteo only; needs no key
    TOMTOM_API_KEY=... pytest -m live   # adds the TomTom checks

Their purpose is to catch provider drift -- a renamed field, a changed unit --
that mocked tests cannot see by construction. They assert contract shape, not
specific weather values, because real forecasts change by the hour.
"""

from __future__ import annotations

import os
from datetime import UTC, datetime, timedelta

import pytest

from apps.routing.providers.openmeteo import OpenMeteoWeatherProvider
from apps.routing.providers.tomtom import (
    TomTomGeocodingProvider,
    TomTomRoutingProvider,
)
from apps.routing.tests.providers.conftest import CHICAGO, DENVER

pytestmark = pytest.mark.live

needs_tomtom_key = pytest.mark.skipif(
    not os.environ.get("TOMTOM_API_KEY", "").strip(),
    reason="TOMTOM_API_KEY is not set; live TomTom checks skipped.",
)


def _window() -> tuple[datetime, datetime]:
    start = datetime.now(UTC).replace(minute=0, second=0, microsecond=0)
    return start, start + timedelta(hours=12)


class TestOpenMeteoLive:
    """Open-Meteo needs no key, so these run on `pytest -m live` alone."""

    def test_returns_a_usable_hourly_series(self) -> None:
        start, end = _window()
        forecast = OpenMeteoWeatherProvider().hourly([DENVER], start, end)[0]

        assert forecast.times
        assert len(forecast.times) == len(forecast.samples)
        assert all(time.tzinfo is not None for time in forecast.times)

    def test_units_still_match_what_the_adapter_assumes(self) -> None:
        """The drift check that matters most.

        If Open-Meteo ever changes the units it returns for these variables,
        the adapter raises rather than silently misclassifying -- so reaching
        a parsed result at all is the assertion.
        """
        start, end = _window()
        forecast = OpenMeteoWeatherProvider().hourly([DENVER], start, end)[0]

        known = [s for s in forecast.samples if s.wind_mph is not None]
        assert known, "expected at least one hour with a wind reading"
        # Sanity bounds in mph. If the provider silently reverted to km/h,
        # ordinary weather would routinely exceed this.
        assert all(0.0 <= s.wind_mph <= 200.0 for s in known)

    def test_multi_location_association_still_holds(self) -> None:
        start, end = _window()
        results = OpenMeteoWeatherProvider().hourly([DENVER, CHICAGO], start, end)

        assert len(results) == 2
        assert results[0].coordinate != results[1].coordinate
        # Grid snapping means resolved != requested, which is exactly why
        # association is positional.
        assert results[0].resolved_coordinate is not None

    def test_forecast_lookup_works_against_live_data(self) -> None:
        start, end = _window()
        forecast = OpenMeteoWeatherProvider().hourly([DENVER], start, end)[0]
        assert forecast.sample_at(start + timedelta(hours=2)) is not None


@needs_tomtom_key
class TestTomTomLive:
    """Skipped unless a key is present. Never required to complete the suite."""

    def _geocoder(self) -> TomTomGeocodingProvider:
        return TomTomGeocodingProvider(os.environ["TOMTOM_API_KEY"])

    def test_geocoding_resolves_a_known_city(self) -> None:
        result = self._geocoder().geocode("Denver, CO")
        assert 38.0 < result.coordinate.latitude < 41.0
        assert -106.0 < result.coordinate.longitude < -103.0
        assert result.label

    def test_truck_routing_returns_alternatives(self) -> None:
        provider = TomTomRoutingProvider(os.environ["TOMTOM_API_KEY"])
        departure = datetime.now(UTC) + timedelta(hours=1)
        result = provider.routes(DENVER, CHICAGO, departure)

        assert result.routes, "expected at least one route"
        assert len(result.routes) <= 3
        for route in result.routes:
            assert route.distance_miles > 500
            assert route.duration_seconds > 0
            assert len(route.geometry) > 100

    def test_route_geometry_spans_origin_to_destination(self) -> None:
        provider = TomTomRoutingProvider(os.environ["TOMTOM_API_KEY"])
        departure = datetime.now(UTC) + timedelta(hours=1)
        route = provider.routes(DENVER, CHICAGO, departure).routes[0]

        assert abs(route.geometry[0].latitude - DENVER.latitude) < 0.5
        assert abs(route.geometry[-1].latitude - CHICAGO.latitude) < 0.5
