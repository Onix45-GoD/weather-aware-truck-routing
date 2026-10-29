"""Pounds to kilograms: the one conversion the routing request depends on."""

from __future__ import annotations

import pytest

from apps.routing.domain.units import KG_PER_LB, pounds_to_kilograms


class TestPoundsToKilograms:
    @pytest.mark.parametrize(
        ("pounds", "kilograms"),
        [
            (0, 0.0),
            (1, 0.45359237),
            (2204.62262185, 1000.0),  # one tonne
            (40_000, 18_143.6948),  # a typical cargo
            (75_000, 34_019.42775),  # cargo + tare, the number TomTom sees
            (80_000, 36_287.3896),  # US federal gross limit
        ],
    )
    def test_table(self, pounds: float, kilograms: float) -> None:
        assert pounds_to_kilograms(pounds) == pytest.approx(kilograms, abs=1e-6)

    def test_constant_is_the_exact_definition(self) -> None:
        assert KG_PER_LB == 0.45359237

    def test_negative_weight_is_rejected(self) -> None:
        with pytest.raises(ValueError):
            pounds_to_kilograms(-1)
