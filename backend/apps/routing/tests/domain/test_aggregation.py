"""Tests for segment-mile attribution and per-route aggregation."""

from __future__ import annotations

import pytest

from apps.routing.domain.aggregation import (
    assess_route,
    segment_miles,
    summarise_route,
)
from apps.routing.domain.checkpoints import generate_checkpoints
from apps.routing.domain.models import (
    Checkpoint,
    Coordinate,
    RiskLevel,
    WeatherSample,
)
from apps.routing.tests.conftest import (
    CALM,
    DEPARTURE,
    make_route,
    rain,
    snow,
    wind,
)

LIGHT_LOAD = 10_000.0


def _checkpoints_at(distances: list[float]) -> tuple[Checkpoint, ...]:
    """Minimal checkpoints at the given along-route distances."""
    last = len(distances) - 1
    return tuple(
        Checkpoint(
            index=index,
            coordinate=Coordinate(40.0 + index * 0.1, -100.0),
            distance_from_origin_miles=distance,
            eta=DEPARTURE,
            is_origin=index == 0,
            is_destination=index == last,
        )
        for index, distance in enumerate(distances)
    )


class TestSegmentAttribution:
    def test_forward_attribution_owns_the_stretch_ahead(self) -> None:
        owned = segment_miles(_checkpoints_at([0.0, 25.0, 50.0, 75.0, 100.0]))
        assert owned == (25.0, 25.0, 25.0, 25.0, 0.0)

    def test_first_segment_starts_at_the_origin(self) -> None:
        owned = segment_miles(_checkpoints_at([0.0, 25.0, 100.0]))
        assert owned[0] == 25.0

    def test_final_checkpoint_owns_no_forward_miles(self) -> None:
        owned = segment_miles(_checkpoints_at([0.0, 25.0, 100.0]))
        assert owned[-1] == 0.0

    def test_last_sampled_checkpoint_covers_through_to_the_destination(self) -> None:
        """A short final leg is owned by the checkpoint that enters it."""
        owned = segment_miles(_checkpoints_at([0.0, 50.0, 100.0, 110.0]))
        assert owned[2] == 10.0

    @pytest.mark.parametrize(
        "distances",
        [
            [0.0, 25.0, 50.0, 75.0, 100.0],
            [0.0, 50.0, 100.0, 110.0],
            [0.0, 7.0],
            [0.0, 10.0, 20.0, 30.0, 40.0, 50.0, 60.0, 63.5],
        ],
    )
    def test_miles_sum_to_the_route_distance(self, distances: list[float]) -> None:
        owned = segment_miles(_checkpoints_at(distances))
        assert sum(owned) == pytest.approx(distances[-1])

    def test_conservation_holds_for_generated_checkpoints(self) -> None:
        route = make_route(distance_miles=873.4)
        points = generate_checkpoints(route, 25.0, DEPARTURE)
        assert sum(segment_miles(points)) == pytest.approx(route.distance_miles)

    def test_no_double_counting(self) -> None:
        """Adjacent segments must abut, never overlap."""
        distances = [0.0, 25.0, 50.0, 75.0, 100.0]
        owned = segment_miles(_checkpoints_at(distances))
        running = 0.0
        for distance, miles in zip(distances, owned):
            assert running == pytest.approx(distance)
            running += miles
        assert running == pytest.approx(distances[-1])

    def test_rejects_a_single_checkpoint(self) -> None:
        with pytest.raises(ValueError, match="origin and a destination"):
            segment_miles(_checkpoints_at([0.0]))

    def test_rejects_non_monotonic_distances(self) -> None:
        with pytest.raises(ValueError, match="non-decreasing"):
            segment_miles(_checkpoints_at([0.0, 50.0, 25.0]))


class TestAssessRoute:
    def test_classifies_and_attributes_in_one_pass(self) -> None:
        points = _checkpoints_at([0.0, 25.0, 50.0, 75.0, 100.0])
        samples = [CALM, wind(40.0), CALM, rain(0.6), CALM]

        assessed = assess_route(points, samples, LIGHT_LOAD)

        assert [a.risk.level for a in assessed] == [
            RiskLevel.LOW,
            RiskLevel.HIGH,
            RiskLevel.LOW,
            RiskLevel.SEVERE,
            RiskLevel.LOW,
        ]
        assert [a.segment_miles for a in assessed] == [25.0, 25.0, 25.0, 25.0, 0.0]

    def test_rejects_a_sample_count_mismatch(self) -> None:
        with pytest.raises(ValueError, match="same length"):
            assess_route(_checkpoints_at([0.0, 50.0, 100.0]), [CALM], LIGHT_LOAD)


class TestRiskMileTotals:
    def test_miles_land_in_the_right_buckets(self) -> None:
        route = make_route(distance_miles=100.0)
        points = _checkpoints_at([0.0, 25.0, 50.0, 75.0, 100.0])
        samples = [CALM, wind(40.0), rain(0.6), CALM, CALM]

        metrics = summarise_route(route, assess_route(points, samples, LIGHT_LOAD))

        assert metrics.low_miles == pytest.approx(50.0)
        assert metrics.high_miles == pytest.approx(25.0)
        assert metrics.severe_miles == pytest.approx(25.0)
        assert metrics.moderate_miles == pytest.approx(0.0)
        assert metrics.no_travel_miles == pytest.approx(0.0)

    def test_totals_sum_to_the_route_distance(self) -> None:
        route = make_route(distance_miles=100.0)
        points = _checkpoints_at([0.0, 25.0, 50.0, 75.0, 100.0])
        samples = [CALM, wind(40.0), rain(0.6), None, CALM]

        metrics = summarise_route(route, assess_route(points, samples, LIGHT_LOAD))

        assert sum(metrics.miles_by_level.values()) == pytest.approx(100.0)

    def test_load_override_moves_miles_between_buckets(self) -> None:
        route = make_route(distance_miles=100.0)
        points = _checkpoints_at([0.0, 50.0, 100.0])
        samples = [wind(38.0), CALM, CALM]

        light = summarise_route(route, assess_route(points, samples, 40_000.0))
        heavy = summarise_route(route, assess_route(points, samples, 40_000.01))

        assert light.high_miles == pytest.approx(50.0)
        assert light.severe_miles == pytest.approx(0.0)
        assert heavy.high_miles == pytest.approx(0.0)
        assert heavy.severe_miles == pytest.approx(50.0)


class TestDistanceWeightedAverageRisk:
    def test_uniform_low_is_zero(self) -> None:
        route = make_route(distance_miles=100.0)
        points = _checkpoints_at([0.0, 50.0, 100.0])
        metrics = summarise_route(
            route, assess_route(points, [CALM, CALM, CALM], LIGHT_LOAD)
        )
        assert metrics.average_risk == pytest.approx(0.0)

    def test_weights_by_miles_not_by_checkpoint_count(self) -> None:
        """75 Low miles and 25 Severe miles average 0.75, not 1.5.

        An unweighted mean over the four mileage-bearing checkpoints would give
        (0+0+0+3)/4 = 0.75 here by coincidence, so the test uses uneven spacing
        where the two answers genuinely differ.
        """
        route = make_route(distance_miles=100.0)
        # 90 Low miles, then 10 Severe miles: two checkpoints, very different
        # weights. An unweighted mean would say 1.5.
        points = _checkpoints_at([0.0, 90.0, 100.0])
        samples = [CALM, rain(0.6), CALM]

        metrics = summarise_route(route, assess_route(points, samples, LIGHT_LOAD))

        assert metrics.average_risk == pytest.approx((0 * 90 + 3 * 10) / 100.0)
        assert metrics.average_risk == pytest.approx(0.3)

    def test_interval_invariance_under_constant_weather(self) -> None:
        """Sampling density must not change the score when weather is uniform.

        This is the property distance weighting buys: with the same constant
        conditions, a 10-mile and a 50-mile interval produce the same average.
        """
        route = make_route(distance_miles=500.0)
        results = []
        for interval in (10.0, 25.0, 50.0):
            points = generate_checkpoints(route, interval, DEPARTURE)
            samples = [wind(30.0)] * len(points)
            results.append(
                summarise_route(route, assess_route(points, samples, LIGHT_LOAD))
            )

        assert all(m.average_risk == pytest.approx(1.0) for m in results)
        assert all(m.moderate_miles == pytest.approx(500.0) for m in results)

    def test_ordinal_scores_map_as_specified(self) -> None:
        route = make_route(distance_miles=100.0)
        points = _checkpoints_at([0.0, 100.0])
        for sample, expected in [
            (CALM, 0.0),
            (wind(30.0), 1.0),
            (wind(40.0), 2.0),
            (wind(50.0), 3.0),
            (wind(60.0), 4.0),
        ]:
            metrics = summarise_route(
                route, assess_route(points, [sample, CALM], LIGHT_LOAD)
            )
            assert metrics.average_risk == pytest.approx(expected)


class TestUnknownWeatherHandling:
    def test_unknown_miles_are_tracked_separately(self) -> None:
        route = make_route(distance_miles=100.0)
        points = _checkpoints_at([0.0, 25.0, 50.0, 75.0, 100.0])
        samples = [CALM, None, None, CALM, CALM]

        metrics = summarise_route(route, assess_route(points, samples, LIGHT_LOAD))

        assert metrics.unknown_miles == pytest.approx(50.0)
        assert metrics.low_miles == pytest.approx(50.0)

    def test_unknown_miles_never_count_as_low(self) -> None:
        route = make_route(distance_miles=100.0)
        points = _checkpoints_at([0.0, 50.0, 100.0])

        known = summarise_route(route, assess_route(points, [CALM, CALM, CALM], 0.0))
        partly_unknown = summarise_route(
            route, assess_route(points, [None, CALM, CALM], 0.0)
        )

        assert known.low_miles == pytest.approx(100.0)
        assert partly_unknown.low_miles == pytest.approx(50.0)
        assert partly_unknown.unknown_miles == pytest.approx(50.0)

    def test_unknown_is_excluded_from_the_average(self) -> None:
        """The average describes the miles we can actually see."""
        route = make_route(distance_miles=100.0)
        points = _checkpoints_at([0.0, 50.0, 100.0])
        samples = [wind(40.0), None, CALM]  # 50 High miles, 50 unknown miles

        metrics = summarise_route(route, assess_route(points, samples, LIGHT_LOAD))

        assert metrics.average_risk == pytest.approx(2.0)
        assert metrics.known_miles == pytest.approx(50.0)

    def test_coverage_percentage_is_reported(self) -> None:
        route = make_route(distance_miles=100.0)
        points = _checkpoints_at([0.0, 25.0, 50.0, 75.0, 100.0])

        full = summarise_route(route, assess_route(points, [CALM] * 5, LIGHT_LOAD))
        partial = summarise_route(
            route, assess_route(points, [CALM, None, CALM, CALM, CALM], LIGHT_LOAD)
        )

        assert full.coverage_pct == pytest.approx(100.0)
        assert partial.coverage_pct == pytest.approx(75.0)

    def test_total_blackout_gives_no_average_and_zero_coverage(self) -> None:
        route = make_route(distance_miles=100.0)
        points = _checkpoints_at([0.0, 50.0, 100.0])

        metrics = summarise_route(
            route, assess_route(points, [None, None, None], LIGHT_LOAD)
        )

        assert metrics.average_risk is None
        assert metrics.coverage_pct == pytest.approx(0.0)
        assert metrics.unknown_miles == pytest.approx(100.0)
        assert metrics.max_risk is RiskLevel.UNKNOWN

    def test_partial_variable_coverage_still_classifies(self) -> None:
        route = make_route(distance_miles=100.0)
        points = _checkpoints_at([0.0, 100.0])
        sample = WeatherSample(wind_mph=50.0, rain_in_hr=None, snow_in_hr=None)

        assessed = assess_route(points, [sample, CALM], LIGHT_LOAD)
        metrics = summarise_route(route, assessed)

        assert metrics.severe_miles == pytest.approx(100.0)
        assert metrics.coverage_pct == pytest.approx(100.0)
        assert assessed[0].risk.partial_data is True


class TestNoTravelAndMaxRisk:
    def test_no_travel_miles_are_counted(self) -> None:
        route = make_route(distance_miles=100.0)
        points = _checkpoints_at([0.0, 50.0, 100.0])
        samples = [CALM, snow(4.0), CALM]

        metrics = summarise_route(route, assess_route(points, samples, LIGHT_LOAD))

        assert metrics.no_travel_miles == pytest.approx(50.0)
        assert metrics.blocked is True
        assert metrics.max_risk is RiskLevel.NO_TRAVEL

    def test_a_clear_route_is_not_blocked(self) -> None:
        route = make_route(distance_miles=100.0)
        points = _checkpoints_at([0.0, 50.0, 100.0])
        metrics = summarise_route(
            route, assess_route(points, [CALM, wind(40.0), CALM], LIGHT_LOAD)
        )
        assert metrics.blocked is False
        assert metrics.max_risk is RiskLevel.HIGH

    def test_no_travel_at_the_destination_still_blocks(self) -> None:
        """The destination owns zero forward miles but must not be ignored.

        A mileage-only test would miss a driver arriving into a 60 mph
        windstorm, so the checkpoint count backs it up.
        """
        route = make_route(distance_miles=100.0)
        points = _checkpoints_at([0.0, 50.0, 100.0])
        samples = [CALM, CALM, wind(60.0)]

        metrics = summarise_route(route, assess_route(points, samples, LIGHT_LOAD))

        assert metrics.no_travel_miles == pytest.approx(0.0)
        assert metrics.no_travel_checkpoints == 1
        assert metrics.blocked is True
        assert metrics.max_risk is RiskLevel.NO_TRAVEL

    def test_max_risk_spans_every_checkpoint(self) -> None:
        route = make_route(distance_miles=100.0)
        points = _checkpoints_at([0.0, 50.0, 100.0])
        metrics = summarise_route(
            route, assess_route(points, [CALM, CALM, rain(0.3)], LIGHT_LOAD)
        )
        assert metrics.max_risk is RiskLevel.HIGH

    def test_rejects_an_empty_assessment(self) -> None:
        with pytest.raises(ValueError, match="no assessed checkpoints"):
            summarise_route(make_route(), [])
