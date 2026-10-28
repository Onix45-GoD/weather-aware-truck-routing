"""Snowfall unit verification -- the explicit acceptance criterion.

The assessment's snow thresholds (0.5 / 1.0 / 2.0 / 3.0 in/hr) are rates of
**snow depth**. Open-Meteo can return snowfall in centimetres or inches, and
separately reports `precipitation`, which is liquid-water equivalent. Reading
one as the other misclassifies snow by a factor of 7 (liquid vs depth) or 10
(mm vs cm), silently and in the unsafe direction.

These tests assert the conversion against the **genuine captured responses**
in ``tests/fixtures/openmeteo/real_*.json`` -- see ``PROVENANCE.md`` for how
they were captured and what they showed. No network access is needed: the
evidence was recorded once and is replayed here.
"""

from __future__ import annotations

from datetime import UTC, datetime

import httpx
import pytest
import respx

from apps.routing.domain.models import RiskLevel
from apps.routing.domain.risk import classify_snow
from apps.routing.providers.errors import InvalidProviderResponseError
from apps.routing.providers.openmeteo import OpenMeteoWeatherProvider
from apps.routing.tests.providers.conftest import DENVER, load_fixture

FORECAST_URL = "https://api.open-meteo.com/v1/forecast"
START = datetime(2026, 11, 2, 0, 0, tzinfo=UTC)
END = datetime(2026, 11, 2, 6, 0, tzinfo=UTC)
FIXED_NOW = datetime(2026, 11, 2, 0, 0, tzinfo=UTC)

CM_PER_INCH = 2.54
#: Open-Meteo's documented fixed snow-to-liquid ratio: 1 mm liquid -> 0.7 cm snow.
SNOW_TO_LIQUID_CM_PER_MM = 0.7


def om(name: str):
    return load_fixture("openmeteo", name)


@pytest.fixture
def provider(fast_client):
    return OpenMeteoWeatherProvider(
        client=fast_client("open-meteo"), now=lambda: FIXED_NOW
    )


class TestGenuineResponseEvidence:
    """Assertions against the real captured responses.

    If Open-Meteo ever changes what it returns, re-capturing the fixtures will
    break these tests rather than quietly changing how snow is scored.
    """

    def test_default_units_are_centimetres(self) -> None:
        metric = om("real_snowfall_metric.json")
        assert metric["hourly_units"]["snowfall"] == "cm"

    def test_requesting_inches_returns_inches(self) -> None:
        imperial = om("real_snowfall_imperial.json")
        assert imperial["hourly_units"]["snowfall"] == "inch"

    def test_the_wind_unit_string_is_mp_slash_h_not_mph(self) -> None:
        """A real trap: validating against "mph" would reject every response."""
        imperial = om("real_snowfall_imperial.json")
        assert imperial["hourly_units"]["wind_speed_10m"] == "mp/h"

    def test_the_capture_actually_contains_snowfall(self) -> None:
        """Without non-zero snow, the ratios below would prove nothing."""
        metric = om("real_snowfall_metric.json")
        snowy = [v for v in metric["hourly"]["snowfall"] if v]
        assert len(snowy) >= 3, "fixture must contain real snowfall to be evidence"

    def test_inch_and_cm_captures_differ_by_exactly_the_depth_factor(self) -> None:
        """2.54 cm per inch -- a plain length conversion of the same quantity.

        If the inch figure were a different physical quantity (liquid
        equivalent, say) this ratio would not be 2.54.
        """
        metric = om("real_snowfall_metric.json")
        imperial = om("real_snowfall_imperial.json")

        pairs = [
            (cm, inch)
            for cm, inch in zip(
                metric["hourly"]["snowfall"], imperial["hourly"]["snowfall"]
            )
            if cm and inch
        ]
        assert pairs, "no overlapping snowy hours to compare"

        for cm, inch in pairs:
            # The API rounds to 2-3 significant figures, so the tolerance
            # reflects its own precision, not slack in the assertion.
            assert cm / inch == pytest.approx(CM_PER_INCH, abs=0.05)

    def test_snowfall_is_depth_not_liquid_water_equivalent(self) -> None:
        """The decisive test.

        `snowfall_cm / precipitation_mm` is 0.7 throughout -- Open-Meteo's
        fixed 7:1 snow-to-liquid ratio. A liquid-equivalent `snowfall` would
        give 0.1 (1 mm == 0.1 cm). Depth is what the assessment's thresholds
        mean, so no further conversion is required.
        """
        metric = om("real_snowfall_metric.json")
        pairs = [
            (snow, precip)
            for snow, precip in zip(
                metric["hourly"]["snowfall"], metric["hourly"]["precipitation"]
            )
            if snow and precip
        ]
        assert pairs, "no snowy hours with precipitation to compare"

        for snow_cm, precip_mm in pairs:
            ratio = snow_cm / precip_mm
            assert ratio == pytest.approx(SNOW_TO_LIQUID_CM_PER_MM, abs=0.02)
            # Explicitly rule out the liquid-equivalent reading.
            assert ratio != pytest.approx(0.1, abs=0.02)

    @respx.mock
    def test_the_adapter_reads_the_real_capture_without_converting(
        self, provider
    ) -> None:
        """End to end on genuine data: inches in, inches out, untouched."""
        imperial = om("real_snowfall_imperial.json")
        respx.get(url__startswith=FORECAST_URL).mock(
            return_value=httpx.Response(200, json=imperial)
        )
        forecast = provider.hourly([DENVER], START, END)[0]

        expected = imperial["hourly"]["snowfall"]
        actual = [sample.snow_in_hr for sample in forecast.samples]
        assert actual == pytest.approx(expected)


class TestUnitConversion:
    """The conversion is driven by the response's own `hourly_units`.

    Not by what we asked for -- so if the provider ignores a unit parameter we
    still produce correct inches instead of misclassifying every checkpoint.
    """

    @respx.mock
    def test_metric_response_converts_to_the_same_values_as_imperial(
        self, provider
    ) -> None:
        """Two fixtures describing identical conditions in different units
        must parse to identical in/hr figures."""
        respx.get(url__startswith=FORECAST_URL).mock(
            return_value=httpx.Response(200, json=om("synthetic_boundaries.json"))
        )
        imperial = provider.hourly([DENVER], START, END)[0]

        respx.get(url__startswith=FORECAST_URL).mock(
            return_value=httpx.Response(
                200, json=om("synthetic_boundaries_metric.json")
            )
        )
        metric = provider.hourly([DENVER], START, END)[0]

        assert [s.snow_in_hr for s in metric.samples] == pytest.approx(
            [s.snow_in_hr for s in imperial.samples], abs=1e-6
        )
        assert [s.rain_in_hr for s in metric.samples] == pytest.approx(
            [s.rain_in_hr for s in imperial.samples], abs=1e-6
        )
        assert [s.wind_mph for s in metric.samples] == pytest.approx(
            [s.wind_mph for s in imperial.samples], abs=1e-3
        )

    @respx.mock
    @pytest.mark.parametrize(
        ("unit", "raw", "expected_inches"),
        [
            # Depth: 2.54 cm per inch.
            ("cm", 1.27, 0.5),
            ("cm", 2.54, 1.0),
            ("cm", 5.08, 2.0),
            ("cm", 7.62, 3.0),
            ("inch", 0.5, 0.5),
            ("inch", 3.0, 3.0),
            # A depth given in millimetres: 25.4 mm per inch.
            ("mm", 25.4, 1.0),
        ],
    )
    def test_snow_converts_at_each_risk_boundary(
        self, provider, unit, raw, expected_inches
    ) -> None:
        payload = om("synthetic_boundaries.json")
        payload["hourly_units"]["snowfall"] = unit
        payload["hourly"]["snowfall"] = [raw] * len(payload["hourly"]["time"])
        respx.get(url__startswith=FORECAST_URL).mock(
            return_value=httpx.Response(200, json=payload)
        )

        sample = provider.hourly([DENVER], START, END)[0].samples[0]
        assert sample.snow_in_hr == pytest.approx(expected_inches, abs=1e-9)

    @respx.mock
    @pytest.mark.parametrize(
        ("snow_cm", "expected_level"),
        [
            (1.2699, RiskLevel.LOW),       # just under 0.5 in
            (1.27, RiskLevel.MODERATE),    # exactly 0.5 in
            (2.54, RiskLevel.HIGH),        # exactly 1.0 in
            (5.08, RiskLevel.SEVERE),      # exactly 2.0 in
            (7.62, RiskLevel.SEVERE),      # exactly 3.0 in -> still Severe
            (7.63, RiskLevel.NO_TRAVEL),   # just over 3.0 in
        ],
    )
    def test_converted_values_land_in_the_right_risk_band(
        self, provider, snow_cm, expected_level
    ) -> None:
        """The conversion is only correct if it classifies correctly."""
        payload = om("synthetic_boundaries.json")
        payload["hourly_units"]["snowfall"] = "cm"
        payload["hourly"]["snowfall"] = [snow_cm] * len(payload["hourly"]["time"])
        respx.get(url__startswith=FORECAST_URL).mock(
            return_value=httpx.Response(200, json=payload)
        )

        sample = provider.hourly([DENVER], START, END)[0].samples[0]
        assert sample.snow_in_hr is not None
        assert classify_snow(sample.snow_in_hr) is expected_level

    @respx.mock
    def test_imperial_snow_reaches_the_risk_engine_unchanged(
        self, provider
    ) -> None:
        """The boundary fixture's inch values classify exactly as the
        assessment table says."""
        respx.get(url__startswith=FORECAST_URL).mock(
            return_value=httpx.Response(200, json=om("synthetic_boundaries.json"))
        )
        samples = provider.hourly([DENVER], START, END)[0].samples
        levels = [classify_snow(s.snow_in_hr) for s in samples]

        assert levels == [
            RiskLevel.LOW,        # 0.0
            RiskLevel.MODERATE,   # 0.5
            RiskLevel.HIGH,       # 1.0
            RiskLevel.SEVERE,     # 2.0
            RiskLevel.SEVERE,     # 3.0  (No Travel is strictly above 3.0)
            RiskLevel.NO_TRAVEL,  # 3.001
        ]

    @respx.mock
    def test_an_unrecognised_unit_raises_instead_of_guessing(
        self, provider
    ) -> None:
        """Guessing here would corrupt every snow classification silently."""
        respx.get(url__startswith=FORECAST_URL).mock(
            return_value=httpx.Response(200, json=om("synthetic_unknown_units.json"))
        )
        with pytest.raises(InvalidProviderResponseError) as exc:
            provider.hourly([DENVER], START, END)
        assert "furlongs" in str(exc.value)

    @respx.mock
    def test_absent_unit_metadata_raises(self, provider) -> None:
        payload = om("synthetic_boundaries.json")
        del payload["hourly_units"]["snowfall"]
        respx.get(url__startswith=FORECAST_URL).mock(
            return_value=httpx.Response(200, json=payload)
        )
        with pytest.raises(InvalidProviderResponseError, match="snowfall"):
            provider.hourly([DENVER], START, END)

    def test_snow_and_rain_use_different_divisors(self) -> None:
        """Guards the exact mistake this milestone was asked to avoid.

        Snow depth is cm-based (2.54 per inch); rain is mm-based (25.4 per
        inch). Collapsing them would be a factor-of-ten error.
        """
        from apps.routing.providers.openmeteo import _RAIN_PER_INCH, _SNOW_PER_INCH

        assert _SNOW_PER_INCH["cm"] == 2.54
        assert _RAIN_PER_INCH["mm"] == 25.4
        assert _SNOW_PER_INCH["cm"] != _RAIN_PER_INCH["mm"]

    def test_conversion_divides_rather_than_multiplying_a_reciprocal(self) -> None:
        """The threshold values must convert exactly, not to within an ULP.

        `5.08 cm / 2.54` is exactly 2.0, so it classifies SEVERE. Multiplying
        by `1/2.54` gives 1.9999999999999998, which classifies HIGH -- a real
        bug this suite caught, and the reason the unit tables store divisors.
        """
        from apps.routing.providers.openmeteo import _SNOW_PER_INCH

        divisor = _SNOW_PER_INCH["cm"]
        for centimetres, inches in [(1.27, 0.5), (2.54, 1.0), (5.08, 2.0), (7.62, 3.0)]:
            assert centimetres / divisor == inches  # exact, not approx
            assert classify_snow(centimetres / divisor) is classify_snow(inches)
