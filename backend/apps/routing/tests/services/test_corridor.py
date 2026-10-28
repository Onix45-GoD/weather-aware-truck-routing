"""Corridor forecast service: 49 frames, classified by the domain, nothing invented.

Everything here is offline and deterministic. The weather comes from either
the synthetic fixture provider or a small scripted provider built in-test,
so every assertion about "which hour" and "which checkpoint" is exact.
"""

from __future__ import annotations

from collections.abc import Sequence
from datetime import UTC, datetime, timedelta

import pytest

from apps.routing.domain.models import Coordinate, RiskLevel, WeatherSample
from apps.routing.domain.risk import assess_checkpoint
from apps.routing.providers.base import HourlyForecast
from apps.routing.providers.errors import (
    InvalidProviderResponseError,
    ProviderRateLimitError,
    ProviderTimeoutError,
)
from apps.routing.providers.fixtures import FixtureWeatherProvider
from apps.routing.services.corridor import (
    CORRIDOR_HORIZON_HOURS,
    CorridorCheckpoint,
    forecast_corridor,
)

REFERENCE = datetime(2026, 11, 2, 13, 0, tzinfo=UTC)
HOURS = CORRIDOR_HORIZON_HOURS + 1


def corridor(count: int = 5, spacing: float = 25.0) -> tuple[CorridorCheckpoint, ...]:
    return tuple(
        CorridorCheckpoint(
            index=i,
            coordinate=Coordinate(latitude=40.0 + 0.1 * i, longitude=-100.0 + 0.3 * i),
            distance_from_origin_miles=spacing * i,
        )
        for i in range(count)
    )


class ScriptedWeather:
    """A provider whose every hour and checkpoint is chosen by the test."""

    name = "scripted"

    def __init__(
        self,
        series_for: callable,
        *,
        start: datetime = REFERENCE,
        hours: int = HOURS,
    ) -> None:
        self.series_for = series_for
        self.start = start
        self.hours = hours
        self.calls: list[tuple[int, datetime, datetime]] = []

    def hourly(
        self, coordinates: Sequence[Coordinate], start: datetime, end: datetime
    ) -> tuple[HourlyForecast, ...]:
        self.calls.append((len(coordinates), start, end))
        times = tuple(self.start + timedelta(hours=h) for h in range(self.hours))
        out = []
        for position, coordinate in enumerate(coordinates):
            samples = tuple(self.series_for(position, h, moment) for h, moment in enumerate(times))
            out.append(
                HourlyForecast(
                    coordinate=coordinate,
                    resolved_coordinate=coordinate,
                    times=times,
                    samples=samples,
                    provider=self.name,
                )
            )
        return tuple(out)


def calm(_position: int, _hour: int, moment: datetime) -> WeatherSample:
    return WeatherSample(wind_mph=5.0, rain_in_hr=0.0, snow_in_hr=0.0, forecast_time=moment)


class TestFrameShape:
    def test_one_frame_per_hour_from_zero_to_forty_eight(self) -> None:
        result = forecast_corridor(REFERENCE, 40_000, corridor(), weather=ScriptedWeather(calm))
        assert [frame.hour for frame in result.frames] == list(range(HOURS))
        assert result.frames[0].at == REFERENCE
        assert result.frames[-1].at == REFERENCE + timedelta(hours=48)
        assert result.step_hours == 1 and result.horizon_hours == 48

    def test_every_frame_covers_every_checkpoint_in_order(self) -> None:
        result = forecast_corridor(REFERENCE, 40_000, corridor(7), weather=ScriptedWeather(calm))
        for frame in result.frames:
            assert [a.checkpoint.index for a in frame.assessed] == list(range(7))

    def test_segment_miles_come_from_the_domain_and_sum_to_the_route(self) -> None:
        result = forecast_corridor(REFERENCE, 40_000, corridor(5, 25.0), weather=ScriptedWeather(calm))
        assert result.segment_miles == (25.0, 25.0, 25.0, 25.0, 0.0)
        assert sum(result.segment_miles) == 100.0

    def test_one_provider_call_for_the_whole_window(self) -> None:
        weather = ScriptedWeather(calm)
        forecast_corridor(REFERENCE, 40_000, corridor(9), weather=weather)
        assert weather.calls == [(9, REFERENCE, REFERENCE + timedelta(hours=48))]

    def test_provider_name_is_reported(self) -> None:
        result = forecast_corridor(REFERENCE, 40_000, corridor(), weather=FixtureWeatherProvider())
        assert result.provider == "fixtures"


class TestTimestampSelection:
    def test_frame_samples_are_the_measurements_for_that_exact_hour(self) -> None:
        """Checkpoint 2 gets a storm at +17 h only; nowhere else, no other hour."""

        def storm_at_17(position: int, hour: int, moment: datetime) -> WeatherSample:
            if position == 2 and hour == 17:
                return WeatherSample(wind_mph=60.0, rain_in_hr=0.0, snow_in_hr=0.0, forecast_time=moment)
            return calm(position, hour, moment)

        result = forecast_corridor(REFERENCE, 40_000, corridor(), weather=ScriptedWeather(storm_at_17))
        levels = {
            (frame.hour, a.checkpoint.index): a.risk.level
            for frame in result.frames
            for a in frame.assessed
        }
        assert levels[(17, 2)] is RiskLevel.NO_TRAVEL
        assert levels[(16, 2)] is RiskLevel.LOW
        assert levels[(18, 2)] is RiskLevel.LOW
        assert levels[(17, 1)] is RiskLevel.LOW
        assert levels[(17, 3)] is RiskLevel.LOW
        assert result.frames[17].assessed[2].weather.forecast_time == REFERENCE + timedelta(hours=17)

    def test_beginning_middle_and_end_of_the_window(self) -> None:
        def ramp(position: int, hour: int, moment: datetime) -> WeatherSample:
            return WeatherSample(wind_mph=float(hour), rain_in_hr=0.0, snow_in_hr=0.0, forecast_time=moment)

        result = forecast_corridor(REFERENCE, 40_000, corridor(), weather=ScriptedWeather(ramp))
        assert result.frames[0].assessed[0].weather.wind_mph == 0.0
        assert result.frames[24].assessed[0].weather.wind_mph == 24.0
        assert result.frames[48].assessed[0].weather.wind_mph == 48.0

    def test_classification_matches_the_domain_function_exactly(self) -> None:
        def ramp(position: int, hour: int, moment: datetime) -> WeatherSample:
            return WeatherSample(wind_mph=float(hour), rain_in_hr=0.0, snow_in_hr=0.0, forecast_time=moment)

        result = forecast_corridor(REFERENCE, 40_000, corridor(), weather=ScriptedWeather(ramp))
        for frame in result.frames:
            for assessed in frame.assessed:
                expected = assess_checkpoint(assessed.weather, 40_000)
                assert assessed.risk == expected


class TestCargoWeight:
    def test_load_override_is_applied_per_frame(self) -> None:
        """A wind that is Moderate alone becomes High for a heavy load.

        The exact rule lives in the domain; here it is only asserted that the
        corridor hands the weight through and the override flag surfaces.
        """

        def breezy(position: int, hour: int, moment: datetime) -> WeatherSample:
            return WeatherSample(wind_mph=30.0, rain_in_hr=0.0, snow_in_hr=0.0, forecast_time=moment)

        light = forecast_corridor(REFERENCE, 10_000, corridor(), weather=ScriptedWeather(breezy))
        heavy = forecast_corridor(REFERENCE, 45_000, corridor(), weather=ScriptedWeather(breezy))

        light_risk = light.frames[10].assessed[1].risk
        heavy_risk = heavy.frames[10].assessed[1].risk
        assert light_risk == assess_checkpoint(light.frames[10].assessed[1].weather, 10_000)
        assert heavy_risk == assess_checkpoint(heavy.frames[10].assessed[1].weather, 45_000)

    def test_an_override_the_domain_applies_surfaces_in_the_frame(self) -> None:
        """Find a wind/load pair the domain escalates, then prove the corridor
        reports it. The domain is the oracle; no threshold is restated here."""
        found = None
        for wind in range(0, 80):
            for load in (10_000, 45_000, 80_000):
                sample = WeatherSample(wind_mph=float(wind), rain_in_hr=0.0, snow_in_hr=0.0)
                if assess_checkpoint(sample, load).load_override_applied:
                    found = (float(wind), load)
                    break
            if found:
                break
        assert found is not None, "domain never applies an override; test needs revisiting"
        wind_mph, load = found

        def windy(position: int, hour: int, moment: datetime) -> WeatherSample:
            return WeatherSample(wind_mph=wind_mph, rain_in_hr=0.0, snow_in_hr=0.0, forecast_time=moment)

        result = forecast_corridor(REFERENCE, load, corridor(), weather=ScriptedWeather(windy))
        for frame in result.frames:
            for assessed in frame.assessed:
                assert assessed.risk.load_override_applied is True


class TestMissingData:
    def test_missing_hours_are_unknown_never_low(self) -> None:
        result = forecast_corridor(
            REFERENCE, 40_000, corridor(), weather=FixtureWeatherProvider(missing_every=4)
        )
        for frame in result.frames:
            for assessed in frame.assessed:
                sample = assessed.weather
                if sample is not None and sample.wind_mph is None:
                    assert assessed.risk.level is RiskLevel.UNKNOWN
        assert any(
            a.risk.level is RiskLevel.UNKNOWN for frame in result.frames for a in frame.assessed
        )

    def test_partial_route_coverage_is_counted_in_unknown_miles(self) -> None:
        def gap_at_checkpoint_1(position: int, hour: int, moment: datetime) -> WeatherSample | None:
            if position == 1:
                return WeatherSample(wind_mph=None, rain_in_hr=None, snow_in_hr=None, forecast_time=moment)
            return calm(position, hour, moment)

        result = forecast_corridor(
            REFERENCE, 40_000, corridor(5, 25.0), weather=ScriptedWeather(gap_at_checkpoint_1)
        )
        frame = result.frames[5]
        assert frame.available is True
        assert frame.metrics.unknown_miles == 25.0
        assert frame.metrics.low_miles == 75.0
        assert frame.metrics.coverage_pct == 75.0
        assert any(w.code == "INCOMPLETE_FORECAST" for w in result.warnings)

    def test_a_partially_missing_sample_is_flagged_not_hidden(self) -> None:
        def no_snow(position: int, hour: int, moment: datetime) -> WeatherSample:
            return WeatherSample(wind_mph=5.0, rain_in_hr=0.0, snow_in_hr=None, forecast_time=moment)

        result = forecast_corridor(REFERENCE, 40_000, corridor(), weather=ScriptedWeather(no_snow))
        risk = result.frames[3].assessed[0].risk
        assert risk.partial_data is True
        assert risk.level is RiskLevel.LOW
        assert risk.snow_level is RiskLevel.UNKNOWN


class TestHorizon:
    def test_hours_the_provider_does_not_cover_are_unavailable(self) -> None:
        """Provider series stops at +30 h: frames 31..48 are unavailable, not calm."""
        weather = ScriptedWeather(calm, hours=31)
        result = forecast_corridor(REFERENCE, 40_000, corridor(), weather=weather)

        assert all(frame.available for frame in result.frames[:31])
        assert not any(frame.available for frame in result.frames[31:])
        assert result.frames[40].unavailable_reason == "outside_provider_horizon"
        assert all(
            a.risk.level is RiskLevel.UNKNOWN for a in result.frames[40].assessed
        )
        assert result.available_hours == 31
        assert result.forecast_window_end == REFERENCE + timedelta(hours=30)
        assert any(w.code == "FORECAST_HORIZON" for w in result.warnings)

    def test_hours_before_the_series_starts_are_unavailable(self) -> None:
        """Series starts at +2 h: frames 0 and 1 precede it; 2 onward match."""
        weather = ScriptedWeather(calm, start=REFERENCE + timedelta(hours=2))
        result = forecast_corridor(REFERENCE, 40_000, corridor(), weather=weather)
        assert [frame.available for frame in result.frames[:3]] == [False, False, True]
        assert result.frames[0].unavailable_reason == "outside_provider_horizon"
        assert result.frames[1].unavailable_reason == "outside_provider_horizon"
        assert result.forecast_window_start == REFERENCE + timedelta(hours=2)

    def test_nearest_hour_policy_is_the_adapters_not_a_second_copy(self) -> None:
        """A series 29 minutes off still matches (within tolerance); 31 does not
        match the *same* hour but does match the next one -- exactly what
        `HourlyForecast.sample_at` decides. The corridor only forwards it."""
        shifted = ScriptedWeather(calm, start=REFERENCE + timedelta(minutes=29))
        result = forecast_corridor(REFERENCE, 40_000, corridor(), weather=shifted)
        assert result.frames[0].available is True
        expected = shifted.hourly([corridor()[0].coordinate], REFERENCE, REFERENCE)[0]
        assert result.frames[0].assessed[0].weather == expected.sample_at(REFERENCE)

    def test_an_hour_inside_the_window_with_no_values_says_so(self) -> None:
        def blank_at_9(position: int, hour: int, moment: datetime) -> WeatherSample:
            if hour == 9:
                return WeatherSample(wind_mph=None, rain_in_hr=None, snow_in_hr=None, forecast_time=moment)
            return calm(position, hour, moment)

        result = forecast_corridor(REFERENCE, 40_000, corridor(), weather=ScriptedWeather(blank_at_9))
        frame = result.frames[9]
        # A sample object with no values still "exists"; the frame is
        # available but every checkpoint is UNKNOWN and coverage is zero.
        assert frame.available is True
        assert frame.metrics.coverage_pct == 0.0
        assert all(a.risk.level is RiskLevel.UNKNOWN for a in frame.assessed)

    def test_provider_with_nothing_at_all(self) -> None:
        weather = ScriptedWeather(calm, hours=0)
        result = forecast_corridor(REFERENCE, 40_000, corridor(), weather=weather)
        assert result.available_hours == 0
        assert result.forecast_window_start is None
        assert [w.code for w in result.warnings] == ["FORECAST_HORIZON"]


class TestProviderFailures:
    @pytest.mark.parametrize(
        "error",
        [
            ProviderTimeoutError("slow", provider="open-meteo"),
            ProviderRateLimitError("429", provider="open-meteo", retry_after_seconds=3),
            InvalidProviderResponseError("bad body", provider="open-meteo"),
        ],
    )
    def test_failures_propagate_unchanged(self, error: Exception) -> None:
        class Failing:
            name = "failing"

            def hourly(self, *_args, **_kwargs):
                raise error

        with pytest.raises(type(error)):
            forecast_corridor(REFERENCE, 40_000, corridor(), weather=Failing())


class TestValidation:
    def test_naive_reference_is_rejected(self) -> None:
        with pytest.raises(ValueError, match="timezone-aware"):
            forecast_corridor(REFERENCE.replace(tzinfo=None), 40_000, corridor(), weather=ScriptedWeather(calm))

    def test_descending_distances_are_rejected(self) -> None:
        bad = (corridor()[0], corridor()[2], corridor()[1])
        with pytest.raises(ValueError, match="non-decreasing"):
            forecast_corridor(REFERENCE, 40_000, bad, weather=ScriptedWeather(calm))

    def test_too_few_checkpoints(self) -> None:
        with pytest.raises(ValueError, match="origin and a destination"):
            forecast_corridor(REFERENCE, 40_000, corridor(1), weather=ScriptedWeather(calm))

    def test_non_positive_load(self) -> None:
        with pytest.raises(ValueError, match="positive"):
            forecast_corridor(REFERENCE, 0, corridor(), weather=ScriptedWeather(calm))

    def test_too_many_checkpoints(self) -> None:
        with pytest.raises(ValueError, match="at most"):
            forecast_corridor(REFERENCE, 40_000, corridor(301, 1.0), weather=ScriptedWeather(calm))

    def test_zero_length_route(self) -> None:
        flat = tuple(
            CorridorCheckpoint(index=i, coordinate=corridor()[i].coordinate, distance_from_origin_miles=0.0)
            for i in range(2)
        )
        with pytest.raises(ValueError, match="positive length"):
            forecast_corridor(REFERENCE, 40_000, flat, weather=ScriptedWeather(calm))

    def test_indexes_must_be_unique_and_ascending(self) -> None:
        points = corridor()
        shuffled = (points[0], CorridorCheckpoint(index=0, coordinate=points[1].coordinate, distance_from_origin_miles=25.0), points[2], points[3], points[4])
        with pytest.raises(ValueError, match="unique and ascending"):
            forecast_corridor(REFERENCE, 40_000, shuffled, weather=ScriptedWeather(calm))
