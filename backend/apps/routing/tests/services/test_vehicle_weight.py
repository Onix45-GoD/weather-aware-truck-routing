"""The routing provider is asked for the gross vehicle weight, in kilograms."""

from __future__ import annotations

from datetime import UTC, datetime

import pytest

from apps.routing.providers.fixtures import (
    FixtureGeocodingProvider,
    FixtureRoutingProvider,
    FixtureWeatherProvider,
)
from apps.routing.services.analysis import AnalysisRequest, analyse_trip


class RecordingRouter:
    name = "recording"

    def __init__(self) -> None:
        self.calls: list[dict] = []
        self._inner = FixtureRoutingProvider()

    def routes(self, origin, destination, departure_time, *, max_alternatives=2, vehicle_weight_kg=None):
        self.calls.append({"vehicle_weight_kg": vehicle_weight_kg, "max_alternatives": max_alternatives})
        return self._inner.routes(origin, destination, departure_time, max_alternatives=max_alternatives)


def request(load_weight_lb: float, tare_weight_lb: float = 35_000.0) -> AnalysisRequest:
    return AnalysisRequest(
        origin="Denver",
        destination="Chicago",
        departure_at=datetime(2026, 11, 2, 12, tzinfo=UTC),
        load_weight_lb=load_weight_lb,
        checkpoint_interval_miles=50,
        tare_weight_lb=tare_weight_lb,
    )


class TestGrossWeight:
    def test_cargo_plus_tare_in_kilograms_reaches_the_router(self) -> None:
        router = RecordingRouter()
        analyse_trip(
            request(40_000),
            geocoder=FixtureGeocodingProvider(),
            router=router,
            weather=FixtureWeatherProvider(),
        )
        assert router.calls[0]["vehicle_weight_kg"] == pytest.approx(75_000 * 0.45359237)
        assert router.calls[0]["max_alternatives"] == 2

    def test_the_bare_cargo_figure_is_never_what_the_router_sees(self) -> None:
        router = RecordingRouter()
        analyse_trip(
            request(40_000),
            geocoder=FixtureGeocodingProvider(),
            router=router,
            weather=FixtureWeatherProvider(),
        )
        assert router.calls[0]["vehicle_weight_kg"] > 40_000 * 0.45359237

    def test_tare_is_configurable(self) -> None:
        assert request(10_000, tare_weight_lb=30_000).gross_weight_lb == 40_000
        assert request(10_000, tare_weight_lb=30_000).vehicle_weight_kg == pytest.approx(18_143.6948)

    def test_risk_engine_still_uses_cargo_weight_only(self) -> None:
        """Gross weight is for routing; the cargo-weight risk rules are untouched."""
        result = analyse_trip(
            request(40_000),
            geocoder=FixtureGeocodingProvider(),
            router=FixtureRoutingProvider(),
            weather=FixtureWeatherProvider(),
        )
        assert result.request.load_weight_lb == 40_000
