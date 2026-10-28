"""Tests for the provider result types, chiefly forecast-time selection."""

from __future__ import annotations

from datetime import UTC, datetime, timedelta

import pytest

from apps.routing.domain.models import Coordinate, WeatherSample
from apps.routing.providers.base import (
    FORECAST_MATCH_TOLERANCE,
    HourlyForecast,
    RouteSet,
)
from apps.routing.tests.providers.conftest import DENVER

BASE = datetime(2026, 11, 2, 12, 0, tzinfo=UTC)


def forecast(hours: int = 6, *, start: datetime = BASE) -> HourlyForecast:
    times = tuple(start + timedelta(hours=offset) for offset in range(hours))
    return HourlyForecast(
        coordinate=DENVER,
        resolved_coordinate=DENVER,
        times=times,
        samples=tuple(
            WeatherSample(
                wind_mph=float(offset),
                rain_in_hr=0.0,
                snow_in_hr=0.0,
                forecast_time=time,
            )
            for offset, time in enumerate(times)
        ),
        provider="test",
    )


class TestConstruction:
    def test_rejects_mismatched_lengths(self) -> None:
        with pytest.raises(ValueError, match="same length"):
            HourlyForecast(
                coordinate=DENVER,
                resolved_coordinate=DENVER,
                times=(BASE,),
                samples=(),
                provider="test",
            )

    def test_rejects_naive_timestamps(self) -> None:
        with pytest.raises(ValueError, match="timezone-aware"):
            HourlyForecast(
                coordinate=DENVER,
                resolved_coordinate=DENVER,
                times=(datetime(2026, 11, 2, 12, 0),),
                samples=(WeatherSample(None, None, None),),
                provider="test",
            )


class TestForecastSelection:
    """Nearest hour wins; an exact half-hour tie rounds up."""

    def test_exact_hour_matches_itself(self) -> None:
        sample = forecast().sample_at(BASE + timedelta(hours=2))
        assert sample is not None and sample.wind_mph == 2.0

    @pytest.mark.parametrize(
        ("minutes", "expected_hour"),
        [
            (1, 2),    # 12:01 -> 12:00
            (29, 2),   # 12:29 -> 12:00
            (31, 3),   # 12:31 -> 13:00
            (59, 3),   # 12:59 -> 13:00
        ],
    )
    def test_rounds_to_the_nearest_hour(self, minutes: int, expected_hour: int) -> None:
        when = BASE + timedelta(hours=2, minutes=minutes)
        sample = forecast().sample_at(when)
        assert sample is not None and sample.wind_mph == float(expected_hour)

    def test_an_exact_half_hour_tie_rounds_up(self) -> None:
        """Matches the round-half-up convention in docs/decisions.md."""
        sample = forecast().sample_at(BASE + timedelta(hours=2, minutes=30))
        assert sample is not None and sample.wind_mph == 3.0

    def test_flooring_is_not_used(self) -> None:
        """Flooring would bias every forecast up to 59 minutes early."""
        sample = forecast().sample_at(BASE + timedelta(hours=2, minutes=58))
        assert sample is not None and sample.wind_mph == 3.0

    def test_selection_is_deterministic(self) -> None:
        series = forecast()
        when = BASE + timedelta(hours=1, minutes=30)
        first = series.sample_at(when)
        assert all(series.sample_at(when) == first for _ in range(20))


class TestHorizonGaps:
    def test_just_before_the_series_still_matches(self) -> None:
        assert forecast().sample_at(BASE - timedelta(minutes=20)) is not None

    def test_well_before_the_series_is_unavailable(self) -> None:
        assert forecast().sample_at(BASE - timedelta(hours=5)) is None

    def test_well_after_the_series_is_unavailable(self) -> None:
        """Beyond the horizon must be UNKNOWN, never the last known hour."""
        assert forecast().sample_at(BASE + timedelta(hours=40)) is None

    def test_exactly_at_the_tolerance_is_accepted(self) -> None:
        assert forecast().sample_at(BASE - FORECAST_MATCH_TOLERANCE) is not None

    def test_just_past_the_tolerance_is_rejected(self) -> None:
        when = BASE - FORECAST_MATCH_TOLERANCE - timedelta(seconds=1)
        assert forecast().sample_at(when) is None

    def test_an_empty_series_yields_nothing(self) -> None:
        empty = HourlyForecast(
            coordinate=DENVER,
            resolved_coordinate=DENVER,
            times=(),
            samples=(),
            provider="test",
        )
        assert empty.sample_at(BASE) is None

    def test_naive_lookup_is_rejected(self) -> None:
        with pytest.raises(ValueError, match="timezone-aware"):
            forecast().sample_at(datetime(2026, 11, 2, 12, 0))

    def test_tolerance_is_configurable(self) -> None:
        series = forecast()
        far = BASE + timedelta(hours=40)
        assert series.sample_at(far) is None
        assert series.sample_at(far, tolerance=timedelta(days=2)) is not None


class TestRouteSet:
    def test_reports_provider_timings_only_when_every_route_has_them(self) -> None:
        from apps.routing.tests.conftest import make_route

        with_timings = make_route(
            route_id="a",
            geometry=(Coordinate(40.0, -100.0), Coordinate(41.0, -100.0)),
            segment_durations=(600.0,),
        )
        without = make_route(
            route_id="b",
            geometry=(Coordinate(40.0, -100.0), Coordinate(41.0, -100.0)),
        )

        assert RouteSet(
            routes=(with_timings,), provider="t", requested_alternatives=2,
            returned_count=1,
        ).has_provider_timings is True

        assert RouteSet(
            routes=(with_timings, without), provider="t",
            requested_alternatives=2, returned_count=2,
        ).has_provider_timings is False

    def test_an_empty_route_set_has_no_timings(self) -> None:
        assert RouteSet(
            routes=(), provider="t", requested_alternatives=2, returned_count=0
        ).has_provider_timings is False
