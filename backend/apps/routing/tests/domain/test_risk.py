"""Exhaustive tests for weather classification and cargo-weight overrides.

Every threshold in the assessment table is tested at the boundary itself and
immediately either side of it, including the shared interior boundaries the
table leaves ambiguous and the gap values (34.5 mph, 0.3 in/hr) a literal
reading of the table does not cover at all.
"""

from __future__ import annotations

import pytest

from apps.routing.domain.models import RiskLevel, WeatherSample
from apps.routing.domain.risk import (
    apply_load_override,
    assess_checkpoint,
    classify_rain,
    classify_snow,
    classify_wind,
    combine_levels,
)

LOW = RiskLevel.LOW
MODERATE = RiskLevel.MODERATE
HIGH = RiskLevel.HIGH
SEVERE = RiskLevel.SEVERE
NO_TRAVEL = RiskLevel.NO_TRAVEL
UNKNOWN = RiskLevel.UNKNOWN

# A light-enough load that no cargo override can ever fire.
LIGHT_LOAD = 10_000.0


class TestWindThresholds:
    """Wind: <25 Low, 25-34 Moderate, 35-44 High, 45-54 Severe, >=55 No Travel."""

    @pytest.mark.parametrize(
        ("speed", "expected"),
        [
            (0.0, LOW),
            (12.5, LOW),
            (24.9, LOW),
            (24.999999, LOW),
            # Shared boundary -> resolves upward, to the more severe band.
            (25.0, MODERATE),
            (25.000001, MODERATE),
            (30.0, MODERATE),
            (34.0, MODERATE),
            # Gap value: the table lists "25-34" then "35-44" and says nothing
            # about 34.5. The lower-bound-inclusive convention assigns it.
            (34.5, MODERATE),
            (34.999999, MODERATE),
            (35.0, HIGH),
            (40.0, HIGH),
            (44.5, HIGH),
            (44.999999, HIGH),
            (45.0, SEVERE),
            (50.0, SEVERE),
            (54.5, SEVERE),
            (54.999999, SEVERE),
            # Table says ">=55 mph", so 55.0 itself is No Travel.
            (55.0, NO_TRAVEL),
            (55.000001, NO_TRAVEL),
            (120.0, NO_TRAVEL),
        ],
    )
    def test_classification(self, speed: float, expected: RiskLevel) -> None:
        assert classify_wind(speed) is expected

    def test_missing_wind_is_unknown_not_low(self) -> None:
        assert classify_wind(None) is UNKNOWN

    def test_nan_is_unknown(self) -> None:
        assert classify_wind(float("nan")) is UNKNOWN

    def test_negative_wind_is_rejected(self) -> None:
        with pytest.raises(ValueError, match="wind speed cannot be negative"):
            classify_wind(-1.0)


class TestRainThresholds:
    """Rain: <0.10 Low, 0.10-0.25 Mod, 0.25-0.50 High, 0.50-1.00 Sev, >1.00 NT."""

    @pytest.mark.parametrize(
        ("rate", "expected"),
        [
            (0.0, LOW),
            (0.05, LOW),
            (0.099999, LOW),
            (0.10, MODERATE),
            (0.100001, MODERATE),
            (0.20, MODERATE),
            (0.249999, MODERATE),
            # 0.25 appears in BOTH the Moderate and High columns of the table.
            # Resolved upward.
            (0.25, HIGH),
            (0.30, HIGH),
            (0.499999, HIGH),
            # 0.50 appears in both High and Severe. Resolved upward.
            (0.50, SEVERE),
            (0.75, SEVERE),
            (0.999999, SEVERE),
            # Table reads ">1.00" for No Travel, so exactly 1.00 stays Severe.
            (1.00, SEVERE),
            (1.000001, NO_TRAVEL),
            (3.0, NO_TRAVEL),
        ],
    )
    def test_classification(self, rate: float, expected: RiskLevel) -> None:
        assert classify_rain(rate) is expected

    def test_missing_rain_is_unknown_not_low(self) -> None:
        assert classify_rain(None) is UNKNOWN

    def test_negative_rain_is_rejected(self) -> None:
        with pytest.raises(ValueError, match="rain rate cannot be negative"):
            classify_rain(-0.01)


class TestSnowThresholds:
    """Snow: <0.5 Low, 0.5-1.0 Mod, 1.0-2.0 High, 2.0-3.0 Sev, >3.0 No Travel."""

    @pytest.mark.parametrize(
        ("rate", "expected"),
        [
            (0.0, LOW),
            (0.25, LOW),
            (0.499999, LOW),
            (0.5, MODERATE),
            (0.75, MODERATE),
            (0.999999, MODERATE),
            (1.0, HIGH),
            (1.5, HIGH),
            (1.999999, HIGH),
            (2.0, SEVERE),
            (2.5, SEVERE),
            (2.999999, SEVERE),
            # Table reads ">3.0" for No Travel, so exactly 3.0 stays Severe.
            (3.0, SEVERE),
            (3.000001, NO_TRAVEL),
            (12.0, NO_TRAVEL),
        ],
    )
    def test_classification(self, rate: float, expected: RiskLevel) -> None:
        assert classify_snow(rate) is expected

    def test_missing_snow_is_unknown_not_low(self) -> None:
        assert classify_snow(None) is UNKNOWN

    def test_negative_snow_is_rejected(self) -> None:
        with pytest.raises(ValueError, match="snow rate cannot be negative"):
            classify_snow(-0.5)


class TestCargoWeightOverrides:
    """The three load rules, with their strict `>` comparisons."""

    @pytest.mark.parametrize("load", [0.0, 30_000.0, 80_000.0, 200_000.0])
    def test_wind_at_or_above_55_is_no_travel_for_any_load(self, load: float) -> None:
        level, _escalated, _reason = apply_load_override(55.0, NO_TRAVEL, load)
        assert level is NO_TRAVEL

    @pytest.mark.parametrize(
        ("load", "expected", "escalated"),
        [
            (29_999.99, SEVERE, False),
            # Exactly 30,000 lb is NOT "> 30,000", so the override must not fire.
            (30_000.0, SEVERE, False),
            (30_000.01, NO_TRAVEL, True),
            (45_000.0, NO_TRAVEL, True),
        ],
    )
    def test_severe_band_override_at_30000_boundary(
        self, load: float, expected: RiskLevel, escalated: bool
    ) -> None:
        level, did_escalate, _reason = apply_load_override(48.0, SEVERE, load)
        assert level is expected
        assert did_escalate is escalated

    @pytest.mark.parametrize(
        ("load", "expected", "escalated"),
        [
            (39_999.99, HIGH, False),
            # Exactly 40,000 lb is NOT "> 40,000", so the override must not fire.
            (40_000.0, HIGH, False),
            (40_000.01, SEVERE, True),
            (80_000.0, SEVERE, True),
        ],
    )
    def test_high_band_override_at_40000_boundary(
        self, load: float, expected: RiskLevel, escalated: bool
    ) -> None:
        level, did_escalate, _reason = apply_load_override(38.0, HIGH, load)
        assert level is expected
        assert did_escalate is escalated

    @pytest.mark.parametrize("speed", [0.0, 24.0, 30.0, 34.999])
    def test_no_override_below_the_high_band(self, speed: float) -> None:
        base = classify_wind(speed)
        level, escalated, reason = apply_load_override(speed, base, 80_000.0)
        assert level is base
        assert escalated is False
        assert reason is None

    def test_override_reason_is_reported_when_it_escalates(self) -> None:
        _level, escalated, reason = apply_load_override(48.0, SEVERE, 42_000.0)
        assert escalated is True
        assert reason is not None
        assert "45-54 mph" in reason
        assert "42,000 lb" in reason

    def test_override_never_de_escalates(self) -> None:
        # Rain-driven NO_TRAVEL must survive a wind band that would "set" SEVERE.
        level, escalated, _reason = apply_load_override(38.0, NO_TRAVEL, 80_000.0)
        assert level is NO_TRAVEL
        assert escalated is False

    def test_unknown_wind_cannot_trigger_an_override(self) -> None:
        level, escalated, reason = apply_load_override(None, UNKNOWN, 80_000.0)
        assert level is UNKNOWN
        assert escalated is False
        assert reason is None

    def test_negative_load_is_rejected(self) -> None:
        with pytest.raises(ValueError, match="load weight cannot be negative"):
            apply_load_override(30.0, MODERATE, -1.0)


class TestCombineLevels:
    def test_takes_the_most_severe(self) -> None:
        assert combine_levels([LOW, HIGH, MODERATE]) is HIGH

    def test_ignores_unknown_when_something_is_known(self) -> None:
        assert combine_levels([UNKNOWN, MODERATE, UNKNOWN]) is MODERATE

    def test_all_unknown_stays_unknown(self) -> None:
        assert combine_levels([UNKNOWN, UNKNOWN]) is UNKNOWN

    def test_empty_is_unknown(self) -> None:
        assert combine_levels([]) is UNKNOWN

    def test_unknown_never_reads_as_low(self) -> None:
        assert combine_levels([UNKNOWN]) is not LOW


class TestAssessCheckpoint:
    """Combination of wind, rain and snow at a single checkpoint."""

    def test_maximum_severity_wins(self) -> None:
        sample = WeatherSample(wind_mph=30.0, rain_in_hr=0.60, snow_in_hr=0.0)
        assessment = assess_checkpoint(sample, LIGHT_LOAD)
        assert assessment.level is SEVERE
        assert assessment.driver == "rain"

    def test_conditions_are_not_compounded(self) -> None:
        # Three simultaneous Moderates stay Moderate; they do not add up.
        sample = WeatherSample(wind_mph=26.0, rain_in_hr=0.12, snow_in_hr=0.6)
        assert assess_checkpoint(sample, LIGHT_LOAD).level is MODERATE

    def test_driver_tie_resolves_to_wind_then_rain_then_snow(self) -> None:
        sample = WeatherSample(wind_mph=36.0, rain_in_hr=0.30, snow_in_hr=1.5)
        assessment = assess_checkpoint(sample, LIGHT_LOAD)
        assert assessment.level is HIGH
        assert assessment.driver == "wind"

        sample = WeatherSample(wind_mph=0.0, rain_in_hr=0.30, snow_in_hr=1.5)
        assert assess_checkpoint(sample, LIGHT_LOAD).driver == "rain"

    def test_load_override_lifts_the_checkpoint_level(self) -> None:
        sample = WeatherSample(wind_mph=38.0, rain_in_hr=0.0, snow_in_hr=0.0)

        light = assess_checkpoint(sample, 40_000.0)
        assert light.level is HIGH
        assert light.load_override_applied is False

        heavy = assess_checkpoint(sample, 40_000.01)
        assert heavy.level is SEVERE
        assert heavy.load_override_applied is True
        assert heavy.base_level is HIGH
        assert "Load override" in heavy.explanation

    def test_missing_sample_is_unknown(self) -> None:
        assessment = assess_checkpoint(None, LIGHT_LOAD)
        assert assessment.level is UNKNOWN
        assert assessment.driver is None
        assert assessment.level is not LOW

    def test_all_variables_missing_is_unknown(self) -> None:
        sample = WeatherSample(wind_mph=None, rain_in_hr=None, snow_in_hr=None)
        assert assess_checkpoint(sample, LIGHT_LOAD).level is UNKNOWN

    def test_partial_data_still_classifies_but_is_flagged(self) -> None:
        sample = WeatherSample(wind_mph=47.0, rain_in_hr=None, snow_in_hr=None)
        assessment = assess_checkpoint(sample, LIGHT_LOAD)
        assert assessment.level is SEVERE
        assert assessment.partial_data is True
        assert "unavailable" in assessment.explanation

    def test_complete_data_is_not_flagged_partial(self) -> None:
        assert assess_checkpoint(
            WeatherSample(wind_mph=10.0, rain_in_hr=0.0, snow_in_hr=0.0),
            LIGHT_LOAD,
        ).partial_data is False

    def test_gusts_do_not_affect_classification(self) -> None:
        """Approved assumption: classify on sustained wind only."""
        calm_gusty = WeatherSample(
            wind_mph=10.0, rain_in_hr=0.0, snow_in_hr=0.0, wind_gust_mph=70.0
        )
        assert assess_checkpoint(calm_gusty, LIGHT_LOAD).level is LOW

    def test_explanation_reports_every_condition(self) -> None:
        sample = WeatherSample(wind_mph=38.2, rain_in_hr=0.04, snow_in_hr=0.0)
        explanation = assess_checkpoint(sample, 42_000.0).explanation
        assert "Wind 38.2 mph" in explanation
        assert "Rain 0.04 in/hr" in explanation
        assert "Snow 0.00 in/hr" in explanation
        assert "Overall Severe" in explanation

    def test_classification_uses_unrounded_values(self) -> None:
        """A value that would cross a boundary if rounded must not cross it."""
        # Rounds to 25 mph (Moderate) at one decimal, but 24.96 is still Low.
        assert assess_checkpoint(
            WeatherSample(wind_mph=24.96, rain_in_hr=0.0, snow_in_hr=0.0),
            LIGHT_LOAD,
        ).level is LOW
        # Rounds to 0.10 in/hr (Moderate) at two decimals, but 0.0996 is Low.
        assert assess_checkpoint(
            WeatherSample(wind_mph=0.0, rain_in_hr=0.0996, snow_in_hr=0.0),
            LIGHT_LOAD,
        ).level is LOW
